from __future__ import annotations

from typing import Any

from app.agent.kimi_vision_agent import KimiVisionAgent
from app.agent.llm import OptionalLLMClient
from app.agent.memory import conversation_memory
from app.agent.prompts import TEXT_RESPONSE_SYSTEM_PROMPT, build_text_response_user_prompt
from app.agent.runtime import build_agent_plan, build_context_snapshot, detect_conversation_intent, normalize_history, validate_decision
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
        history = normalize_history(conversation_history) or conversation_memory.get(session_id)
        context_snapshot = build_context_snapshot(message, history)
        history_text = context_snapshot["history_text"]
        resolved_order_id = order_id or extract_order_id(message) or context_snapshot.get("last_order_id")

        tools.record_trace(
            "ContextManager",
            {"session_id": session_id, "history_turns": len(history)},
            context_snapshot,
            label="上下文管理",
            summary=f"历史 {len(history)} 条，订单 {resolved_order_id or '待补充'}",
        )

        conversation_intent = detect_conversation_intent(message)
        if conversation_intent and not image_bytes:
            return self._conversation_reply(
                message=message,
                intent=conversation_intent,
                tools=tools,
                session_id=session_id,
                history=history,
            )

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
        plan = build_agent_plan(has_image=bool(image_bytes), has_order=bool(resolved_order_id), intent=intent)
        tools.record_trace("PlanningAgent", {"intent": intent}, plan, label="任务规划", summary=" -> ".join(step["step"] for step in plan))

        order = tools.query_order(resolved_order_id) if resolved_order_id else None
        user = tools.query_user(order["user_id"]) if order and order.get("user_id") else None
        category = order.get("category") if order else None
        policy_query = " ".join([message, history_text, intent, category or ""])
        policy_hits = tools.search_policy(policy_query)
        similar_cases = tools.search_cases(query=" ".join([message, history_text]), category=category) if order else tools.search_cases(query=message, category=None)
        decision = tools.decide(message=message, intent=intent, order=order, user=user, policy_hits=policy_hits)
        decision, guardrails = validate_decision(order=order, decision=decision)
        tools.record_trace(
            "DecisionGuardrail",
            {"order_id": order.get("order_id") if order else None},
            {"decision": decision, "guardrails": guardrails},
            label="决策校验",
            summary="; ".join(guardrails) if guardrails else "无需修正",
        )

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
                context_summary=context_snapshot["summary"],
                agent_plan=plan,
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

    def _conversation_reply(
        self,
        *,
        message: str,
        intent: str,
        tools: ShopcareTools,
        session_id: str | None,
        history: list[dict[str, str]],
    ) -> ChatResponse:
        answers = {
            "identity": "我是安心购的智能售后助手，你可以把我当成一个一直在线的售后搭子。退款、退货、换货、物流异常、商品破损这些事，我都能先帮你看一遍：能自动处理的我直接给方案，需要补凭证的我会告诉你该传什么，不让你来回猜。",
            "greeting": "我在呢。你把订单号和遇到的问题发我就行；如果商品有破损，也可以直接传照片，我会结合订单和售后规则一起帮你判断。",
            "thanks": "不客气，这事我继续帮你盯着。后面你只要补一句“我要退款”或者“我想换货”，我会接着前面的订单继续处理。",
            "help": "你可以这样用：先发订单号和问题，比如“3000029 包装破损想退款”；如果有照片就一起上传。之后你可以直接追问“那能换货吗”“要不要人工”，我会记住前面的上下文继续回答。",
            "smalltalk": "我在。你可以直接说遇到的售后问题，我会按当前订单和前面的聊天继续帮你判断。",
        }
        answer = answers.get(intent, answers["smalltalk"])
        tools.record_trace(
            "ConversationRouter",
            {"message": message, "history_turns": len(history)},
            {"intent": intent, "answer": answer},
            label="轻对话路由",
            summary=f"识别为 {intent}",
        )
        conversation_memory.append(session_id, role="user", content=message)
        conversation_memory.append(session_id, role="assistant", content=answer)
        return ChatResponse(
            answer=answer,
            intent=intent,
            decision={
                "status": "informational",
                "resolution": "conversation",
                "priority": "P3",
                "need_human_review": False,
                "refund_amount": 0,
                "compensation_amount": 0,
                "reason": "用户当前是在进行轻对话，不需要进入售后决策流程。",
                "next_steps": ["继续描述售后问题，或上传商品凭证"],
            },
            order=None,
            user_profile=None,
            similar_cases=[],
            policy_evidence=[],
            traces=tools.traces,
            llm_used=False,
            llm_provider=None,
            image_analysis=None,
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
        return self.text_llm.complete(
            system=TEXT_RESPONSE_SYSTEM_PROMPT,
            user=build_text_response_user_prompt(payload),
        )

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
            return "我先帮你接住这个问题，不过现在还缺订单号。你把订单号发我一下，我就能看订单状态，再判断是退款、退货、换货还是补发更合适。"

        lines = [
            f"我先帮你看了这单：{order.get('order_id')}，商品是 {order.get('product_name')}，现在状态是 {order.get('order_status')}。"
        ]
        if user:
            if user.get("user_tier") in {"VIP", "HighValue"}:
                lines.append("你是平台的高价值用户，这类售后我会优先按更稳妥的方式处理。")
        if image_analysis:
            details = "、".join(image_analysis.get("damage_details") or [])
            valid_text = "有效" if image_analysis.get("evidence_valid") else "暂不充分"
            lines.append(
                f"Kimi 图片凭证分析显示：{image_analysis.get('product_condition')}。"
                f"损坏详情：{details or '未识别到明确损坏点'}；凭证判断：{valid_text}。"
            )
        lines.append(
            f"这单我建议走 {decision.get('resolution')}。当前判断是 {decision.get('status')}，主要原因是：{decision.get('reason')}"
        )
        next_steps = "；".join(decision.get("next_steps") or [])
        if next_steps:
            lines.append(f"你接下来先做这一步就好：{next_steps}。")
        if policy_hits:
            lines.append(f"处理依据：{policy_hits[0].get('title')}。")
        if similar_cases:
            lines.append(f"系统检索到 {len(similar_cases)} 条相似售后案例，常见处理方式包括 {similar_cases[0].get('resolution')}。")
        lines.append("这类情况我建议让人工再复核一下，避免你后面来回补材料。" if decision.get("need_human_review") else "目前看不需要先转人工，我可以继续帮你往下办。")
        return "\n".join(lines).strip()


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
