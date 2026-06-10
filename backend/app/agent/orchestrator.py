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
        self.text_llm = OptionalLLMClient(self.settings, profile="agent")

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
        if conversation_intent == "confirm" and not image_bytes:
            return self._confirmation_reply(
                message=message,
                tools=tools,
                session_id=session_id,
                history=history,
                context_snapshot=context_snapshot,
                resolved_order_id=resolved_order_id,
            )
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
        if image_analysis:
            fallback_answer = self._compose_image_answer(
                order=order,
                policy_hits=policy_hits,
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
                meta = self.text_llm.last_meta
                llm_provider = f"{meta['provider']}:{meta['model']}:{meta['source']}"

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

    def _confirmation_reply(
        self,
        *,
        message: str,
        tools: ShopcareTools,
        session_id: str | None,
        history: list[dict[str, str]],
        context_snapshot: dict[str, Any],
        resolved_order_id: str | None,
    ) -> ChatResponse:
        recent_assistant = ""
        for item in reversed(history):
            if item.get("role") == "assistant":
                recent_assistant = item.get("content", "")
                break

        last_order_id = resolved_order_id or context_snapshot.get("last_order_id")
        looks_like_approval = any(
            word in recent_assistant
            for word in ["可以吗", "我这就", "提交", "申请", "退款", "换货", "处理结论", "回复“可以”", "回复\"可以\""]
        )
        if looks_like_approval:
            order_part = f"订单 {last_order_id} " if last_order_id else "这次售后 "
            answer = (
                f"可以，我已经把{order_part}按刚才的结论整理好了：当前可以进入售后申请/商家审核这一步。"
                "我会保留前面的图片和聊天上下文，后面你继续问“进度到哪了”或者“改成人工处理”，我都能接着这单往下说。\n\n"
                "这里先说明一下：现在演示系统还没有接入真实电商后台的打款接口，所以我不会假装已经退款到账；接入后台后，这一步就可以变成真正的提交退款/换货工单。"
            )
            summary = "承接上一轮确认"
        else:
            answer = (
                "好，我在。你可以直接把订单号、问题描述或者图片发我，我会接着当前会话继续判断，"
                "不用从头再讲一遍。"
            )
            summary = "普通确认"

        tools.record_trace(
            "ConfirmationRouter",
            {"message": message, "history_turns": len(history), "last_order_id": last_order_id},
            {"answer": answer, "used_previous_assistant": bool(recent_assistant)},
            label="确认承接",
            summary=summary,
        )
        conversation_memory.append(session_id, role="user", content=message)
        conversation_memory.append(session_id, role="assistant", content=answer)
        return ChatResponse(
            answer=answer,
            intent="confirm",
            decision={
                "status": "confirmed",
                "resolution": "continue_previous_plan",
                "priority": "P3",
                "need_human_review": False,
                "refund_amount": 0,
                "compensation_amount": 0,
                "reason": "用户确认上一轮处理建议，系统承接上下文继续推进。",
                "next_steps": ["保留当前会话上下文，继续跟进售后申请"],
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

    def _compose_image_answer(
        self,
        *,
        order: dict[str, Any] | None,
        policy_hits: list[dict[str, Any]],
        decision: dict[str, Any],
        image_analysis: dict[str, Any],
    ) -> str:
        condition = image_analysis.get("product_condition") or "问题比较明显"
        evidence_valid = bool(image_analysis.get("evidence_valid"))
        resolution = decision.get("resolution") or "manual_review"
        status = decision.get("status") or "need_info"
        refund_amount = float(decision.get("refund_amount") or 0)
        compensation = float(decision.get("compensation_amount") or 0)

        if not evidence_valid:
            return "图看到了，但还不够清楚。再补一张商品整体、破损处和外包装的照片。"

        if decision.get("need_human_review") or status in {"need_info", "manual_review"}:
            return f"图看到了，{condition}。这单需要人工复核，我帮你转接？"

        if resolution == "refund_only":
            amount_text = f"退 {refund_amount:.2f}" if refund_amount else "可以退款"
            coupon_text = f"，另外补 {compensation:.2f} 券" if compensation else ""
            return f"图看到了，{condition}。{amount_text}，不用寄回{coupon_text}。我帮你提交？"

        if resolution in {"exchange", "replacement"}:
            return f"图看到了，{condition}。可以换货，你要换同款吗？"

        return f"图看到了，{condition}。这单可以继续处理，我帮你提交？"

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
            return "哪个订单？"

        status = decision.get("status")
        resolution = decision.get("resolution")
        refund_amount = float(decision.get("refund_amount") or 0)
        compensation = float(decision.get("compensation_amount") or 0)

        if decision.get("need_human_review") or status in {"need_info", "manual_review"}:
            return "这单还差一点凭证，需要人工复核。我帮你转接？"

        if resolution == "refund_only":
            amount_text = f"退 {refund_amount:.2f}" if refund_amount else "可以退款"
            coupon_text = f"，另外补 {compensation:.2f} 券" if compensation else ""
            return f"{amount_text}，不用寄回{coupon_text}。我帮你提交？"

        if resolution in {"exchange", "replacement"}:
            return "可以换货。你要换同款吗？"

        if intent in {"logistics", "shipping"}:
            return "物流确实异常了。我帮你催一下，如果今天还不动，可以申请补发。"

        return "可以继续处理。我帮你提交？"


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
