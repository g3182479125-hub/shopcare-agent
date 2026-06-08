from __future__ import annotations

import re
import time
from typing import Any, Callable

from app.agent.policy import PolicyRAG
from app.schemas import ToolTrace
from app.services.repository import ShopcareRepository


INTENT_KEYWORDS = {
    "refund": ["退款", "退钱", "取消", "不想要", "没发货", "未发货", "仅退款"],
    "return_refund": ["退货", "退掉", "七天无理由", "不合适", "不满意"],
    "exchange": ["换货", "换码", "尺码", "型号不对", "颜色不对", "换新"],
    "reship": ["少发", "漏发", "缺失", "配件", "赠品", "补发"],
    "logistics": ["物流", "快递", "没收到", "签收", "配送", "超时"],
    "quality": ["坏", "故障", "破损", "质量", "不能用", "漏液", "不新鲜", "过敏", "异常", "损坏"],
    "invoice": ["发票", "抬头", "税号"],
    "complaint": ["投诉", "人工", "客服", "赔偿", "补偿"],
}


def detect_intent(message: str) -> str:
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(keyword in message for keyword in keywords):
            return intent
    return "general_after_sales"


def extract_order_id(message: str) -> str | None:
    match = re.search(r"\b(\d{7,})\b", message or "")
    return match.group(1) if match else None


class ShopcareTools:
    def __init__(self, repository: ShopcareRepository, policy_rag: PolicyRAG | None = None) -> None:
        self.repository = repository
        self.policy_rag = policy_rag or PolicyRAG()
        self.traces: list[ToolTrace] = []

    def record_trace(self, name: str, payload: dict[str, Any], output: Any, *, label: str | None = None, summary: str | None = None, status: str = "ok", elapsed_ms: int = 0) -> None:
        self.traces.append(ToolTrace(tool_name=name, label=label, input=payload, output=output, status=status, elapsed_ms=elapsed_ms, summary=summary))

    def call(self, name: str, payload: dict[str, Any], func: Callable[[], Any], *, label: str | None = None, summary: str | None = None) -> Any:
        start = time.perf_counter()
        status = "ok"
        try:
            output = func()
        except Exception as exc:
            status = "error"
            output = {"error": str(exc)}
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        self.traces.append(ToolTrace(tool_name=name, label=label, input=payload, output=output, status=status, elapsed_ms=elapsed_ms, summary=summary))
        return output

    def query_order(self, order_id: str) -> dict[str, Any] | None:
        return self.call("OrderTool", {"order_id": order_id}, lambda: self.repository.get_order(order_id), label="订单查询")

    def query_user(self, user_id: str) -> dict[str, Any] | None:
        return self.call("UserTool", {"user_id": user_id}, lambda: self.repository.get_user(user_id), label="用户画像")

    def search_cases(self, *, query: str, category: str | None, reason_code: str | None = None) -> list[dict[str, Any]]:
        return self.call(
            "CaseTool",
            {"query": query, "category": category, "reason_code": reason_code},
            lambda: self.repository.search_cases(query=query, category=category, reason_code=reason_code, limit=6),
            label="相似案例检索",
        )

    def search_policy(self, query: str) -> list[dict[str, Any]]:
        return self.call("PolicyRAGTool", {"query": query}, lambda: self.policy_rag.search(query), label="政策 RAG 检索")

    def decide(self, *, message: str, intent: str, order: dict[str, Any] | None, user: dict[str, Any] | None, policy_hits: list[dict[str, Any]]) -> dict[str, Any]:
        return self.call(
            "DecisionTool",
            {"intent": intent, "order_id": order.get("order_id") if order else None},
            lambda: decide_aftersales(message=message, intent=intent, order=order, user=user, policy_hits=policy_hits),
            label="售后决策",
        )


def decide_aftersales(*, message: str, intent: str, order: dict[str, Any] | None, user: dict[str, Any] | None, policy_hits: list[dict[str, Any]]) -> dict[str, Any]:
    if not order:
        return {
            "status": "need_info",
            "resolution": "need_order_id",
            "priority": "P3",
            "need_human_review": False,
            "refund_amount": 0,
            "compensation_amount": 0,
            "reason": "需要订单号才能查询订单状态并判断售后路径。",
            "next_steps": ["补充订单号", "说明商品问题和期望处理方式"],
        }

    status = str(order.get("order_status") or "")
    category = str(order.get("category") or "")
    amount = float(order.get("amount") or 0)
    fulfillment_hours = int(order.get("fulfillment_time") or 0)
    tier = str((user or {}).get("user_tier") or "Regular")
    priority = "P1" if amount >= 5000 else ("P2" if tier in {"VIP", "HighValue"} else "P3")
    has_valid_image_evidence = "凭证有效：是" in message or "凭证判断：有效" in message
    image_severe = "严重程度：严重" in message

    decision = {
        "status": "need_info",
        "resolution": "manual_review",
        "priority": priority,
        "need_human_review": priority == "P1",
        "refund_amount": 0.0,
        "compensation_amount": 0.0,
        "reason": "需要补充商品照片、物流状态或问题凭证后再处理。",
        "next_steps": ["上传商品问题照片或物流截图", "客服核验后给出最终处理"],
    }

    if status in {"Pending", "Paid", "PendingShipment"} and intent in {"refund", "general_after_sales"}:
        decision.update(
            status="approved",
            resolution="refund_only",
            refund_amount=round(amount, 2),
            need_human_review=False,
            reason="订单尚未发货，支持取消订单并原路退款。",
            next_steps=["确认取消订单", "退款将按原支付渠道退回"],
        )
        return decision

    if status == "Cancelled":
        decision.update(
            status="need_info",
            resolution="refund_consult",
            reason="订单已取消，需要查询支付渠道退款到账状态。",
            next_steps=["核对支付方式", "查询退款流水", "必要时转人工处理"],
        )
        return decision

    if intent == "logistics" or (status == "Shipped" and "物流" in message):
        compensation = 15.0 if tier in {"VIP", "HighValue"} else 8.0
        decision.update(
            status="need_info",
            resolution="logistics_claim",
            compensation_amount=compensation,
            reason="已发货订单需要先核验物流轨迹；若超时或异常，可进行催派、拦截或补偿。",
            next_steps=["核验最新物流轨迹", "联系承运商确认包裹状态", "异常成立后补偿或退款"],
        )
        return decision

    is_food = any(word in category for word in ["食品", "生鲜", "饮料"])
    if is_food and (intent in {"quality", "refund"} or has_valid_image_evidence):
        decision.update(
            status="approved" if has_valid_image_evidence else "need_info",
            resolution="refund_only",
            refund_amount=round(amount if has_valid_image_evidence else amount * 0.8, 2),
            compensation_amount=10.0 if has_valid_image_evidence else 0.0,
            need_human_review=amount >= 5000,
            reason="食品类商品涉及新鲜度、包装破损或食用安全，凭有效图片证据可优先仅退款或补偿。",
            next_steps=["保留商品和包装照片", "核验后发起仅退款", "必要时追加补偿券"],
        )
        return decision

    if any(word in category for word in ["美妆", "护肤"]) and any(word in message for word in ["过敏", "不适", "红肿"]):
        decision.update(
            status="escalated",
            resolution="manual_review",
            priority="P1",
            need_human_review=True,
            reason="美妆护肤个体不适涉及安全风险，需要人工审核凭证。",
            next_steps=["暂停使用商品", "上传商品批次和不适凭证", "转人工客服审核"],
        )
        return decision

    if intent == "reship":
        decision.update(
            status="approved",
            resolution="reship",
            reason="少发、漏发或配件缺失可核验后优先补发。",
            next_steps=["核对订单明细", "确认缺失内容", "创建补发工单"],
        )
        return decision

    if intent == "exchange" or (any(word in category for word in ["服装", "鞋帽"]) and "尺码" in message):
        decision.update(
            status="approved",
            resolution="exchange",
            reason="符合售后期内换货路径，可创建换货申请。",
            next_steps=["确认目标尺码/颜色/型号", "生成换货寄回地址", "仓库收货后寄出换货商品"],
        )
        return decision

    if intent in {"return_refund", "quality"}:
        if fulfillment_hours <= 168 or intent == "quality":
            decision.update(
                status="approved" if intent == "return_refund" or has_valid_image_evidence else "need_info",
                resolution="manual_review" if image_severe else "return_refund",
                refund_amount=round(amount, 2) if intent == "return_refund" else 0,
                need_human_review=image_severe or priority == "P1",
                reason="符合售后期内退货退款路径；质量问题会结合图片凭证判断是否需要人工复核。",
                next_steps=["确认商品状态或上传质量问题照片", "生成退货地址", "仓库验收后退款"],
            )
        else:
            decision.update(
                status="need_info",
                resolution="manual_review",
                reason="订单可能超过 7 天无理由期限，需要人工判断是否符合特殊售后规则。",
                next_steps=["补充商品状态", "说明申请原因", "转人工审核"],
            )
        return decision

    if intent == "invoice":
        decision.update(
            status="approved",
            resolution="invoice_support",
            reason="发票问题不影响订单履约，可直接进入发票补开或重开流程。",
            next_steps=["补充发票抬头和税号", "确认邮箱或下载入口"],
        )
        return decision

    return decision
