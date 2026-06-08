from __future__ import annotations

import json
from typing import Any

from app.agent.kimi_vision_agent import KimiVisionAgent
from app.agent.llm import OptionalLLMClient
from app.agent.memory import conversation_memory
from app.agent.tools import ShopcareTools, detect_intent, extract_order_id
from app.config import get_settings
from app.schemas import ChatResponse, ToolTrace
from app.services.repository import ShopcareRepository


class ShopCareAgent:
    def __init__(self, repository: ShopcareRepository) -> None:
        self.repository = repository
        self.settings = get_settings()
        self.text_llm = OptionalLLMClient(self.settings)

    async def run(
        self,
        message: str,
        order_id: str | None = None,
        *,
        image_bytes: bytes | None = None,
        image_type: str | None = None,
        session_id: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> ChatResponse:
        tools = ShopcareTools(self.repository)
        history = (conversation_history or [])[-12:] or conversation_memory.get(session_id)
        history_text = _format_history(history)
        resolved_order_id = order_id or extract_order_id(message) or extract_order_id(history_text)
        image_analysis: dict[str, Any] | None = None
        image_llm_used = False

        if image_bytes:
            image_trace, image_analysis = await self._analyze_image(
                image_bytes=image_bytes,
                image_type=image_type or "image/jpeg",
                order_id=resolved_order_id,
            )
            tools.traces.append(image_trace)
            image_llm_used = image_trace.status == "ok"
            if image_analysis:
                message = message + "\n" + _format_image_context(image_analysis)

        intent = detect_intent(message)
        order = tools.query_order(resolved_order_id) if resolved_order_id else None
        user = tools.query_user(order["user_id"]) if order and order.get("user_id") else None
        category = order.get("category") if order else None
        policy_query = " ".join([message, history_text, intent, category or ""])
        policy_hits = tools.search_policy(policy_query)
        similar_cases = tools.search_cases(query=message, category=category) if order else tools.search_cases(query=message, category=None)
        decision = tools.decide(message=message, intent=intent, order=order, user=user, policy_hits=policy_hits)

        fallback_answer = self._compose_answer(
            message=message,
            intent=intent,
            order=order,
            user=user,
            policy_hits=policy_hits,
            similar_cases=similar_cases,
            decision=decision,
            image_analysis=image_analysis,
        )

        # Model routing:
        # - With an image, Kimi is the only model provider. We use its multimodal
        #   evidence and keep the final decision deterministic for speed.
        # - Without an image, DeepSeek/OpenAI-compatible text LLM rewrites the reply.
        llm_answer: str | None = None
        llm_provider: str | None = None
        if image_bytes:
            llm_provider = "kimi" if image_llm_used else None
        else:
            llm_answer = self._deepseek_rewrite(
                message=message,
                intent=intent,
                order=order,
                user=user,
                policy_hits=policy_hits,
                similar_cases=similar_cases,
                decision=decision,
                image_analysis=image_analysis,
                session_id=session_id,
                conversation_history=history,
            )
            if llm_answer:
                llm_provider = self.settings.llm_provider or "deepseek"

        final_answer = llm_answer or fallback_answer
        conversation_memory.append(session_id, role="user", content=message)
        conversation_memory.append(session_id, role="assistant", content=final_answer)

        return ChatResponse(
            answer=final_answer,
            intent=intent,
            decision=decision,
            order=order,
            user_profile=user,
            similar_cases=similar_cases,
            policy_evidence=policy_hits,
            traces=tools.traces,
            llm_used=bool(llm_answer) or image_llm_used,
            llm_provider=llm_provider,
            image_analysis=image_analysis,
        )

    async def _analyze_image(
        self,
        *,
        image_bytes: bytes,
        image_type: str,
        order_id: str | None,
    ) -> tuple[ToolTrace, dict[str, Any] | None]:
        order_context: dict[str, Any] = {}
        if order_id:
            order = self.repository.get_order(order_id)
            if order:
                order_context = {
                    "product_name": order.get("product_name"),
                    "category": order.get("category"),
                    "amount": order.get("amount"),
                }

        result = await KimiVisionAgent(self.settings).analyze_image(
            image_bytes=image_bytes,
            image_type=image_type,
            order_context=order_context,
        )
        analysis = result.get("analysis") if result.get("success") else None
        trace = ToolTrace(
            tool_name="ImageAnalysisAgent",
            label="Kimi 视觉 Agent",
            input={"image_type": image_type, "size_bytes": len(image_bytes), "order_id": order_id},
            output=analysis or {"error": result.get("error", "image analysis failed")},
            status="ok" if result.get("success") else "error",
            elapsed_ms=int(result.get("elapsed_ms") or 0),
            summary=(analysis or {}).get("product_condition", "")[:30] if analysis else None,
        )
        return trace, analysis

    def _deepseek_rewrite(self, **payload: Any) -> str | None:
        if not self.text_llm.enabled:
            return None
        system = (
            "你是电商售后智能客服。你只能基于给定 JSON 里的订单、用户、政策、"
            "相似案例和决策输出回答，不得虚构退款金额、订单状态或政策。"
            "回答要简洁、专业，并说明处理依据。"
        )
        user = "请根据以下结构化上下文生成中文售后答复：\n" + json.dumps(payload, ensure_ascii=False, default=str)
        return self.text_llm.complete(system=system, user=user)

    def _compose_answer(
        self,
        *,
        message: str,
        intent: str,
        order: dict[str, Any] | None,
        user: dict[str, Any] | None,
        policy_hits: list[dict[str, Any]],
        similar_cases: list[dict[str, Any]],
        decision: dict[str, Any],
        image_analysis: dict[str, Any] | None,
    ) -> str:
        if not order:
            return "我需要先确认订单号，才能判断是否支持退款、退货、换货或补发。请提供订单号，并简单描述商品问题。"

        lines = [
            f"您好，订单 {order.get('order_id')} 当前状态为 {order.get('order_status')}，商品为 {order.get('product_name')}，类目为 {order.get('category')}，金额 {order.get('amount')} 元。"
        ]
        if user:
            lines.append(
                f"您的用户等级为 {user.get('user_tier')}，历史购买 {user.get('total_purchase_times')} 次，累计消费 {user.get('total_purchase_amount')} 元。"
            )
        if image_analysis:
            details = "、".join(image_analysis.get("damage_details") or [])
            valid_text = "有效" if image_analysis.get("evidence_valid") else "暂不充分"
            lines.append(
                f"Kimi 图片凭证分析显示：{image_analysis.get('product_condition')}。"
                f"损坏详情：{details or '未识别到明确损坏点'}；凭证判断：{valid_text}。"
            )
        lines.append(
            f"建议处理方案：{decision.get('resolution')}，当前判断为 {decision.get('status')}。原因：{decision.get('reason')}"
        )
        next_steps = "；".join(decision.get("next_steps") or [])
        if next_steps:
            lines.append(f"下一步：{next_steps}。")
        if policy_hits:
            lines.append(f"处理依据：{policy_hits[0].get('title')}。")
        if similar_cases:
            lines.append(f"系统检索到 {len(similar_cases)} 条相似售后案例，常见处理方式包括 {similar_cases[0].get('resolution')}。")
        lines.append("该问题建议转人工复核。" if decision.get("need_human_review") else "暂不需要人工介入，可按流程继续处理。")
        return "\n".join(lines).strip()


def _format_history(history: list[dict[str, str]]) -> str:
    if not history:
        return ""
    recent = history[-8:]
    lines = [f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in recent]
    return "\n".join(lines)


def _format_image_context(analysis: dict[str, Any]) -> str:
    details = "、".join(analysis.get("damage_details") or [])
    return f"""
[图片分析结果（来自 Kimi 视觉 Agent）]
商品状态：{analysis.get('product_condition')}
损坏详情：{details}
严重程度：{analysis.get('severity')}
凭证有效：{'是' if analysis.get('evidence_valid') else '否'}
建议方向：{analysis.get('suggested_action')}
""".strip()
