from __future__ import annotations

import re
from typing import Any


def normalize_history(history: list[dict[str, str]] | None, *, limit: int = 12) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in (history or [])[-limit:]:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            items.append({"role": role, "content": content[:1200]})
    return items


def extract_order_from_text(text: str) -> str | None:
    match = re.search(r"\b(\d{7,})\b", text or "")
    return match.group(1) if match else None


def build_context_snapshot(message: str, history: list[dict[str, str]] | None) -> dict[str, Any]:
    clean_history = normalize_history(history)
    history_text = "\n".join(f"{item['role']}: {item['content']}" for item in clean_history)
    last_order_id = extract_order_from_text(message) or extract_order_from_text(history_text)
    last_user_need = ""
    for item in reversed(clean_history):
        if item["role"] == "user":
            last_user_need = item["content"]
            break
    return {
        "history": clean_history,
        "history_text": history_text,
        "last_order_id": last_order_id,
        "last_user_need": last_user_need,
        "turn_count": len(clean_history),
        "summary": summarize_history(clean_history),
    }


def summarize_history(history: list[dict[str, str]]) -> str:
    if not history:
        return "无历史上下文"
    recent = history[-6:]
    parts = []
    for item in recent:
        label = "用户" if item["role"] == "user" else "助手"
        parts.append(f"{label}: {item['content'][:90]}")
    return "；".join(parts)


def build_agent_plan(*, has_image: bool, has_order: bool, intent: str) -> list[dict[str, str]]:
    plan = []
    if has_image:
        plan.append({"step": "image_evidence", "goal": "调用 Kimi 视觉模型识别商品凭证"})
    plan.append({"step": "context", "goal": "合并当前问题和最近会话上下文"})
    if has_order:
        plan.append({"step": "order_lookup", "goal": "查询订单和用户画像"})
    else:
        plan.append({"step": "need_order", "goal": "要求用户补充订单号"})
    plan.append({"step": "retrieval", "goal": f"围绕 {intent} 检索售后政策和相似案例"})
    plan.append({"step": "decision", "goal": "执行售后规则决策并进行安全校验"})
    plan.append({"step": "response", "goal": "生成面向用户的售后答复"})
    return plan


def validate_decision(*, order: dict[str, Any] | None, decision: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    fixed = dict(decision)
    guardrails: list[str] = []
    if not order:
        if fixed.get("refund_amount", 0):
            fixed["refund_amount"] = 0
            guardrails.append("无订单时禁止给出退款金额")
        fixed["status"] = "need_info"
        fixed["resolution"] = "need_order_id"
        fixed["need_human_review"] = False
        return fixed, guardrails

    amount = float(order.get("amount") or 0)
    refund_amount = float(fixed.get("refund_amount") or 0)
    if refund_amount > amount:
        fixed["refund_amount"] = round(amount, 2)
        guardrails.append("退款金额不得超过订单金额")

    status = str(order.get("order_status") or "")
    if status in {"Pending", "Paid", "PendingShipment"} and fixed.get("resolution") in {"return_refund", "exchange"}:
        fixed["resolution"] = "refund_only"
        fixed["refund_amount"] = round(amount, 2)
        guardrails.append("未发货订单优先走取消/仅退款，不能要求退货或换货")

    if fixed.get("priority") not in {"P0", "P1", "P2", "P3"}:
        fixed["priority"] = "P2"
        guardrails.append("修正非法优先级")

    return fixed, guardrails
