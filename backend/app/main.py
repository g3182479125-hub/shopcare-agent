from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agent.orchestrator import ShopCareAgent
from app.config import get_settings
from app.db import ensure_database, get_connection
from app.schemas import ChatRequest, ChatResponse, DashboardSummary
from app.services.repository import ShopcareRepository

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    ensure_database()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.post("/api/agent/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    with get_connection() as conn:
        agent = ShopCareAgent(ShopcareRepository(conn))
        return agent.run(payload.message, payload.order_id)


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
