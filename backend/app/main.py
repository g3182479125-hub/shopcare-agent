from __future__ import annotations

import json
import asyncio
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agent.merchant_agent import MerchantAnalyticsAgent
from app.agent.orchestrator import ShopCareAgent
from app.config import get_settings
from app.db import database_status, ensure_database, get_connection
from app.schemas import (
    AuthRequest,
    AuthResponse,
    ChatRequest,
    ChatResponse,
    ConversationCreateRequest,
    ConversationItem,
    ConversationUpdateRequest,
    DashboardSummary,
    DemoAuthRequest,
    GraphQueryRequest,
    MerchantChatRequest,
    MerchantChatResponse,
)
from app.security import create_access_token, decode_access_token
from app.services.account_service import AccountService
from app.services.agent_run_store import AgentRunStore
from app.services.conversation_store import ConversationStore
from app.services.graph_rag import GraphRAGService
from app.services.knowledge_base import KnowledgeBase
from app.services.llm_cache import LLMCache
from app.services.repository import ShopcareRepository
from app.services.vector_index import vector_backend_status
from app.services.web_search import WebSearchClient

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(
        dict.fromkeys(
            [
                *settings.cors_origins,
                "https://shopcare-agent.vercel.app",
                "https://shopcare-agent-api.vercel.app",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:5174",
                "http://127.0.0.1:5174",
            ]
        )
    ),
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:\d+|http://127\.0\.0\.1:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logger(request: Request, call_next):
    response = await call_next(request)
    print(json.dumps({"path": request.url.path, "method": request.method, "status": response.status_code}, ensure_ascii=False))
    return response


@app.on_event("startup")
def startup() -> None:
    ensure_database()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/llm/status")
def llm_status() -> dict[str, Any]:
    return {
        "cache_enabled": settings.llm_cache_enabled,
        "database": database_status(),
        "cache_ttl_seconds": settings.llm_cache_ttl_seconds,
        "semantic_cache_enabled": settings.llm_semantic_cache_enabled,
        "semantic_cache_threshold": settings.llm_semantic_cache_threshold,
        "semantic_cache_max_candidates": settings.llm_semantic_cache_max_candidates,
        "cache_stats": LLMCache(settings.llm_cache_ttl_seconds).stats(),
        "web_search": WebSearchClient(settings).status(),
        "knowledge_vector_index": vector_backend_status(),
        "graph_rag": GraphRAGService(settings).status(),
        "profiles": {
            "chat": safe_profile(settings.llm_profile("chat")),
            "reason": safe_profile(settings.llm_profile("reason")),
            "agent": safe_profile(settings.llm_profile("agent")),
        },
    }


@app.post("/api/auth/register", response_model=AuthResponse)
def register(payload: AuthRequest) -> AuthResponse:
    with get_connection() as conn:
        try:
            user = AccountService(conn).create_user(
                email=payload.email,
                password=payload.password,
                username=payload.username or "",
                role=payload.role,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _auth_response(user)


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: AuthRequest) -> AuthResponse:
    with get_connection() as conn:
        user = AccountService(conn).authenticate(email=payload.email, password=payload.password)
        if not user or user["role"] != payload.role:
            raise HTTPException(status_code=401, detail="邮箱、密码或身份不匹配")
        return _auth_response(user)


@app.post("/api/auth/demo", response_model=AuthResponse)
def demo_login(payload: DemoAuthRequest) -> AuthResponse:
    with get_connection() as conn:
        try:
            user, _ = AccountService(conn).ensure_demo_user(payload.role)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _auth_response(user)


@app.get("/api/auth/me")
def me(request: Request) -> dict[str, Any]:
    return {"user": _current_user(request)}


@app.post("/api/conversations")
def create_conversation(request: Request, payload: ConversationCreateRequest) -> dict[str, Any]:
    user = _current_user(request)
    with get_connection() as conn:
        return ConversationStore(conn).create(user_id=user["id"], role=payload.role, title=payload.title)


@app.get("/api/conversations")
def list_conversations(request: Request, role: str | None = None) -> dict[str, Any]:
    user = _current_user(request)
    with get_connection() as conn:
        return {"items": ConversationStore(conn).list_for_user(user_id=user["id"], role=role)}


@app.get("/api/conversations/{conversation_id}/messages")
def list_conversation_messages(request: Request, conversation_id: str) -> dict[str, Any]:
    user = _current_user(request)
    with get_connection() as conn:
        store = ConversationStore(conn)
        conversation = store.get(conversation_id, user_id=user["id"])
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"conversation": conversation, "items": store.list_messages(conversation_id, user_id=user["id"])}


@app.put("/api/conversations/{conversation_id}")
def update_conversation(request: Request, conversation_id: str, payload: ConversationUpdateRequest) -> dict[str, Any]:
    user = _current_user(request)
    with get_connection() as conn:
        conversation = ConversationStore(conn).update_title(conversation_id, user_id=user["id"], title=payload.title)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(request: Request, conversation_id: str) -> dict[str, bool]:
    user = _current_user(request)
    with get_connection() as conn:
        ok = ConversationStore(conn).delete(conversation_id, user_id=user["id"])
        if not ok:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"ok": True}


@app.post("/api/agent/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    message: str | None = Form(default=None),
    order_id: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    conversation_id: str | None = Form(default=None),
    conversation_history: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
) -> ChatResponse:
    content_type = request.headers.get("content-type", "")
    image_bytes: bytes | None = None
    image_type: str | None = None
    history_items: list[dict[str, str]] = []

    if content_type.startswith("application/json"):
        try:
            payload = ChatRequest.model_validate(await request.json())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc
        message = payload.message
        order_id = payload.order_id
        session_id = payload.session_id
        conversation_id = payload.conversation_id
        history_items = [item.model_dump() for item in payload.conversation_history[-12:]]
    else:
        if not message or not message.strip():
            raise HTTPException(status_code=400, detail="message is required")
        history_items = _parse_history(conversation_history)
        if image:
            image_type = image.content_type or "application/octet-stream"
            if not image_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="只支持 image/* 类型的图片")
            image_bytes = await image.read()
            if len(image_bytes) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="图片不能超过5MB")

    with get_connection() as conn:
        agent = ShopCareAgent(ShopcareRepository(conn))
        result = await agent.run(
            message=message.strip(),
            order_id=order_id,
            image_bytes=image_bytes,
            image_type=image_type,
            session_id=session_id,
            conversation_history=history_items,
        )
        result.conversation_id = _persist_exchange(
            request=request,
            conn=conn,
            role="user",
            conversation_id=conversation_id,
            user_message=message.strip() + ("（含图片）" if image_bytes else ""),
            assistant_message=result.answer,
            payload=result.model_dump(),
        )
        result.agent_run_id = _record_agent_run(
            request=request,
            conn=conn,
            role="user",
            workflow_name="shopcare_after_sales",
            state={"message": message.strip(), "order_id": order_id, "has_image": bool(image_bytes)},
            result=result.model_dump(),
        )
        return result


@app.post("/api/agent/chat/stream")
async def chat_stream(request: Request, payload: ChatRequest) -> StreamingResponse:
    with get_connection() as conn:
        agent = ShopCareAgent(ShopcareRepository(conn))
        result = await agent.run(
            message=payload.message.strip(),
            order_id=payload.order_id,
            session_id=payload.session_id,
            conversation_history=[item.model_dump() for item in payload.conversation_history[-12:]],
        )
        result.conversation_id = _persist_exchange(
            request=request,
            conn=conn,
            role="user",
            conversation_id=payload.conversation_id,
            user_message=payload.message.strip(),
            assistant_message=result.answer,
            payload=result.model_dump(),
        )
        result.agent_run_id = _record_agent_run(
            request=request,
            conn=conn,
            role="user",
            workflow_name="shopcare_after_sales_stream",
            state={"message": payload.message.strip(), "order_id": payload.order_id, "has_image": False},
            result=result.model_dump(),
        )
    return StreamingResponse(_sse_answer(result.answer, result.model_dump()), media_type="text/event-stream")


@app.post("/api/merchant/agent/chat", response_model=MerchantChatResponse)
async def merchant_chat(
    request: Request,
    message: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    conversation_id: str | None = Form(default=None),
    conversation_history: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
) -> MerchantChatResponse:
    content_type = request.headers.get("content-type", "")
    image_bytes: bytes | None = None
    image_type: str | None = None
    history_items: list[dict[str, str]] = []

    if content_type.startswith("application/json"):
        try:
            payload = MerchantChatRequest.model_validate(await request.json())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc
        message = payload.message
        session_id = payload.session_id
        conversation_id = payload.conversation_id
        history_items = [item.model_dump() for item in payload.conversation_history[-12:]]
    else:
        if not message or not message.strip():
            raise HTTPException(status_code=400, detail="message is required")
        history_items = _parse_history(conversation_history)
        if image:
            image_type = image.content_type or "application/octet-stream"
            if not image_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="Only image/* files are supported")
            image_bytes = await image.read()
            if len(image_bytes) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Image must be under 5MB")

    with get_connection() as conn:
        agent = MerchantAnalyticsAgent(settings, conn)
        result = await agent.run(
            message=(message or "").strip(),
            conversation_history=history_items,
            image_bytes=image_bytes,
            image_type=image_type,
        )
        result["conversation_id"] = _persist_exchange(
            request=request,
            conn=conn,
            role="merchant",
            conversation_id=conversation_id,
            user_message=(message or "").strip() + ("（含图片）" if image_bytes else ""),
            assistant_message=result["answer"],
            payload=result,
        )
        result["agent_run_id"] = _record_agent_run(
            request=request,
            conn=conn,
            role="merchant",
            workflow_name="merchant_analytics",
            state={"message": (message or "").strip(), "has_image": bool(image_bytes), "focus": result.get("focus")},
            result=result,
        )
        return MerchantChatResponse(**result)


@app.post("/api/merchant/agent/chat/stream")
async def merchant_chat_stream(request: Request, payload: MerchantChatRequest) -> StreamingResponse:
    with get_connection() as conn:
        agent = MerchantAnalyticsAgent(settings, conn)
        result = await agent.run(
            message=payload.message.strip(),
            conversation_history=[item.model_dump() for item in payload.conversation_history[-12:]],
        )
        result["conversation_id"] = _persist_exchange(
            request=request,
            conn=conn,
            role="merchant",
            conversation_id=payload.conversation_id,
            user_message=payload.message.strip(),
            assistant_message=result["answer"],
            payload=result,
        )
        result["agent_run_id"] = _record_agent_run(
            request=request,
            conn=conn,
            role="merchant",
            workflow_name="merchant_analytics_stream",
            state={"message": payload.message.strip(), "has_image": False, "focus": result.get("focus")},
            result=result,
        )
    return StreamingResponse(_sse_answer(result["answer"], result), media_type="text/event-stream")


@app.get("/api/agent/runs")
def list_agent_runs(request: Request, role: str | None = None, limit: int = 30) -> dict[str, Any]:
    user = _current_user(request)
    with get_connection() as conn:
        return {"items": AgentRunStore(conn).list_for_user(user_id=user["id"], role=role, limit=limit)}


@app.get("/api/agent/runs/{run_id}")
def get_agent_run(request: Request, run_id: str) -> dict[str, Any]:
    user = _current_user(request)
    with get_connection() as conn:
        run = AgentRunStore(conn).get(run_id, user_id=user["id"])
        if not run:
            raise HTTPException(status_code=404, detail="Agent run not found")
        return run


@app.post("/api/agent/runs/{run_id}/resume")
def resume_agent_run(request: Request, run_id: str) -> dict[str, Any]:
    user = _current_user(request)
    with get_connection() as conn:
        run = AgentRunStore(conn).get(run_id, user_id=user["id"])
        if not run:
            raise HTTPException(status_code=404, detail="Agent run not found")
        if run.get("status") == "completed":
            return {"status": "completed", "run": run}
        return {"status": "resumable", "current_node": run.get("current_node"), "state": run.get("state"), "run": run}


def _parse_history(raw: str | None) -> list[dict[str, str]]:
    if not raw:
        return []
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    items: list[dict[str, str]] = []
    for item in parsed[-12:]:
        try:
            model = ConversationItem.model_validate(item)
        except Exception:
            continue
        items.append(model.model_dump())
    return items


def _auth_response(user: dict[str, Any]) -> AuthResponse:
    token = create_access_token(
        {"sub": user["id"], "email": user["email"], "role": user["role"]},
        secret=settings.auth_secret,
        expires_in=settings.auth_token_expires_seconds,
    )
    return AuthResponse(access_token=token, user=user)


def _current_user(request: Request, *, required: bool = True) -> dict[str, Any] | None:
    raw = request.headers.get("authorization", "")
    token = raw.removeprefix("Bearer ").strip() if raw.lower().startswith("bearer ") else ""
    payload = decode_access_token(token, secret=settings.auth_secret) if token else None
    if not payload:
        if required:
            raise HTTPException(status_code=401, detail="请先登录")
        return None
    with get_connection() as conn:
        user = AccountService(conn).get_user(str(payload.get("sub") or ""))
    if not user and required:
        raise HTTPException(status_code=401, detail="登录已失效")
    return user


def _record_agent_run(
    *,
    request: Request,
    conn,
    role: str,
    workflow_name: str,
    state: dict[str, Any],
    result: dict[str, Any],
) -> str | None:
    user = _current_user(request, required=False)
    if not user:
        return None
    run = AgentRunStore(conn).record_completed(
        user_id=user["id"],
        role=role,
        workflow_name=workflow_name,
        state=state,
        result=result,
    )
    return run.get("id")


def _persist_exchange(
    *,
    request: Request,
    conn,
    role: str,
    conversation_id: str | None,
    user_message: str,
    assistant_message: str,
    payload: dict[str, Any],
) -> str | None:
    user = _current_user(request, required=False)
    if not user:
        return conversation_id
    store = ConversationStore(conn)
    conversation = store.get(conversation_id or "", user_id=user["id"]) if conversation_id else None
    if not conversation:
        conversation = store.create(user_id=user["id"], role=role, title=user_message[:28] or None)
    store.append_message(conversation_id=conversation["id"], user_id=user["id"], sender="user", content=user_message)
    store.append_message(conversation_id=conversation["id"], user_id=user["id"], sender="assistant", content=assistant_message, payload=payload)
    return conversation["id"]


async def _sse_answer(answer: str, payload: dict[str, Any]):
    for chunk in _chunk_text(answer):
        yield f"data: {json.dumps({'type': 'delta', 'content': chunk}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.018)
    yield f"data: {json.dumps({'type': 'done', 'payload': payload}, ensure_ascii=False)}\n\n"


def _chunk_text(text: str, size: int = 8) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


def safe_profile(profile: dict[str, str]) -> dict[str, str]:
    return {
        "provider": profile.get("provider", ""),
        "base_url": profile.get("base_url", ""),
        "model": profile.get("model", ""),
        "configured": "yes" if profile.get("api_key") else "no",
    }


@app.post("/api/knowledge/documents")
async def upload_knowledge_document(
    request: Request,
    role: str = Form(default="user"),
    title: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    user = _current_user(request)
    if role != user["role"]:
        raise HTTPException(status_code=403, detail="Knowledge documents must match your current role")
    content = await file.read()
    with get_connection() as conn:
        try:
            document = KnowledgeBase(conn).add_document(
                user_id=user["id"],
                role=role,
                title=title or file.filename or "Knowledge document",
                source_name=file.filename or "upload.txt",
                mime_type=file.content_type or "text/plain",
                content_bytes=content,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"document": document}


@app.get("/api/knowledge/documents")
def list_knowledge_documents(request: Request, role: str | None = None) -> dict[str, Any]:
    user = _current_user(request)
    selected_role = role or user["role"]
    if selected_role != user["role"]:
        raise HTTPException(status_code=403, detail="Cannot read another role's knowledge documents")
    with get_connection() as conn:
        return {"items": KnowledgeBase(conn).list_documents(user_id=user["id"], role=selected_role)}


@app.get("/api/knowledge/search")
def search_knowledge(request: Request, q: str, role: str | None = None, limit: int = 5) -> dict[str, Any]:
    user = _current_user(request)
    selected_role = role or user["role"]
    if selected_role != user["role"]:
        raise HTTPException(status_code=403, detail="Cannot search another role's knowledge documents")
    with get_connection() as conn:
        return {"items": KnowledgeBase(conn).search(role=selected_role, query=q, limit=max(1, min(limit, 10)))}


@app.get("/api/graph/status")
def graph_status() -> dict[str, Any]:
    return GraphRAGService(settings).status()


@app.post("/api/graph/query")
def graph_query(request: Request, payload: GraphQueryRequest) -> dict[str, Any]:
    user = _current_user(request)
    if payload.role != user["role"]:
        raise HTTPException(status_code=403, detail="Graph role must match your current role")
    with get_connection() as conn:
        return GraphRAGService(settings, conn).query(
            question=payload.question,
            role=payload.role,
            limit=payload.limit,
        )


@app.get("/api/search")
def web_search(request: Request, q: str, limit: int = 5) -> dict[str, Any]:
    _current_user(request)
    return WebSearchClient(settings).search(q, max_results=max(1, min(limit, 10)))


@app.delete("/api/knowledge/documents/{document_id}")
def delete_knowledge_document(request: Request, document_id: str) -> dict[str, bool]:
    user = _current_user(request)
    with get_connection() as conn:
        ok = KnowledgeBase(conn).delete_document(document_id=document_id, user_id=user["id"])
        if not ok:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        return {"ok": True}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str) -> dict:
    with get_connection() as conn:
        repo = ShopcareRepository(conn)
        order = repo.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        user = repo.get_user(order["user_id"]) if order.get("user_id") else None
        cases = repo.get_cases_for_order(order_id)
        return {"order": order, "user": user, "cases": cases}


@app.get("/api/cases/search")
def search_cases(query: str = "", category: str | None = None, reason_code: str | None = None) -> dict:
    with get_connection() as conn:
        repo = ShopcareRepository(conn)
        return {"items": repo.search_cases(query=query, category=category, reason_code=reason_code)}


@app.get("/api/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary() -> DashboardSummary:
    with get_connection() as conn:
        repo = ShopcareRepository(conn)
        return DashboardSummary(**repo.dashboard_summary())
