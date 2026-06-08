from __future__ import annotations

import json
from typing import Any

from app.agent.llm import OptionalLLMClient
from app.agent.tools import ShopcareTools, detect_intent, extract_order_id
from app.config import get_settings
from app.schemas import ChatResponse
from app.services.repository import ShopcareRepository


class ShopCareAgent:
    def __init__(self, repository: ShopcareRepository) -> None:
        self.repository = repository
        self.llm = OptionalLLMClient(get_settings())

    def run(self, message: str, order_id: str | None = None) -> ChatResponse:
        tools = ShopcareTools(self.repository)
        resolved_order_id = order_id or extract_order_id(message)
        intent = detect_intent(message)

        order = tools.query_order(resolved_order_id) if resolved_order_id else None
        user = tools.query_user(order["user_id"]) if order and order.get("user_id") else None
        category = order.get("category") if order else None
        policy_query = " ".join([message, intent, category or ""])
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
        )
        llm_answer = self._llm_rewrite(
            message=message,
            intent=intent,
            order=order,
            user=user,
            policy_hits=policy_hits,
            similar_cases=similar_cases,
            decision=decision,
        )

        return ChatResponse(
            answer=llm_answer or fallback_answer,
            intent=intent,
            decision=decision,
            order=order,
            user_profile=user,
            similar_cases=similar_cases,
            policy_evidence=policy_hits,
            traces=tools.traces,
            llm_used=bool(llm_answer),
        )

    def _llm_rewrite(self, **payload: Any) -> str | None:
        if not self.llm.enabled:
            return None
        system = (
            "你是电商售后智能客服。你只能基于给定 JSON 里的订单、用户、政策、相似案例和决策输出回答，"
            "不得虚构退款金额、订单状态或政策。回答要简洁、专业，并说明处理依据。"
        )
        user = "请根据以下结构化上下文生成中文售后答复：\n" + json.dumps(payload, ensure_ascii=False, default=str)
        return self.llm.complete(system=system, user=user)

    def _compose_answer(self, *, message: str, intent: str, order: dict[str, Any] | None, user: dict[str, Any] | None, policy_hits: list[dict[str, Any]], similar_cases: list[dict[str, Any]], decision: dict[str, Any]) -> str:
        if not order:
            return "我需要先确认订单号，才能判断是否支持退款、退货、换货或补发。请提供订单号，并简单描述商品问题。"

        order_line = f"订单 {order.get('order_id')} 当前状态为 {order.get('order_status')}，商品为 {order.get('product_name')}，类目 {order.get('category')}，金额 {order.get('amount')} 元。"
        user_line = ""
        if user:
            user_line = f"用户等级为 {user.get('user_tier')}，历史购买 {user.get('total_purchase_times')} 次，累计消费 {user.get('total_purchase_amount')} 元。"
        decision_line = f"建议处理：{decision.get('resolution')}，当前判断为 {decision.get('status')}。原因：{decision.get('reason')}"
        next_steps = "；".join(decision.get("next_steps") or [])
        policy_line = ""
        if policy_hits:
            policy_line = f"参考政策：{policy_hits[0].get('title')}。"
        cases_line = ""
        if similar_cases:
            cases_line = f"系统检索到 {len(similar_cases)} 条相似售后案例，常见处理方式包括 {similar_cases[0].get('resolution')}。"
        human_line = "该问题建议转人工复核。" if decision.get("need_human_review") else "暂不需要人工介入，可按流程继续处理。"
        return "\n".join([order_line, user_line, decision_line, f"下一步：{next_steps}", policy_line, cases_line, human_line]).strip()
