from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.agent.llm import OptionalLLMClient
from app.config import Settings


MERCHANT_SYSTEM_PROMPT = """你是 ShopCare Merchant 的商家数据分析 Agent。

你面对的是电商商家，不是消费者。你的目标是把订单、用户、类目、品牌、城市、履约和售后信号转成可执行经营建议。

回复风格：
1. 直接给结论，不写报告。
2. 说人话，最多 4 句话。
3. 必须基于给定经营数据、会话上下文和图片分析结论。
4. 不要虚构没有给出的指标。
5. 如果商家问怎么做，给 2-3 个动作，不要泛泛而谈。
6. 可以在最后加 1 个贴合语气的 emoji。

如果用户上传图片，图片已经由 Kimi 先分析过，你只需要结合图片结论和经营数据回答，不要重复图片识别过程。
"""

MERCHANT_IMAGE_SYSTEM_PROMPT = """你是商家经营分析场景的图片理解 Agent。
用户可能上传经营截图、商品图、报表图、售后截图或竞品截图。

必须返回严格 JSON，不要 markdown，不要解释。
字段：
{
  "image_summary": "一句话说明图片是什么",
  "business_signal": "图片里对经营分析有用的信号",
  "risk_or_opportunity": "风险或机会",
  "suggested_analysis_focus": "gmv|category|brand|city|users|fulfillment|aftersales|conversion|overview",
  "evidence_valid": true
}
"""


class MerchantAnalyticsAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.text_llm = OptionalLLMClient(settings)
        self.data = load_merchant_analytics()

    async def run(
        self,
        *,
        message: str,
        conversation_history: list[dict[str, str]] | None = None,
        image_bytes: bytes | None = None,
        image_type: str | None = None,
    ) -> dict[str, Any]:
        history = normalize_history(conversation_history)
        image_analysis = None
        image_llm_used = False
        if image_bytes:
            image_result = await analyze_merchant_image(
                settings=self.settings,
                image_bytes=image_bytes,
                image_type=image_type or "image/jpeg",
            )
            image_analysis = image_result.get("analysis") if image_result.get("success") else None
            image_llm_used = bool(image_analysis)

        focus = detect_focus(message, image_analysis)
        fallback = fallback_answer(message=message, data=self.data, focus=focus, image_analysis=image_analysis)
        answer = self._deepseek_answer(
            message=message,
            history=history,
            focus=focus,
            image_analysis=image_analysis,
        ) or fallback
        chart_directive = build_chart_directive(focus, self.data)

        return {
            "answer": clean_answer(answer),
            "focus": focus,
            "chart_directive": chart_directive,
            "image_analysis": image_analysis,
            "llm_used": bool(answer != fallback) or image_llm_used,
            "llm_provider": "deepseek" if answer != fallback else ("kimi" if image_llm_used else "rules"),
            "context_used": {
                "history_turns": len(history),
                "has_image": bool(image_analysis),
                "data_generated_at": self.data.get("generated_at"),
            },
        }

    def _deepseek_answer(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        focus: str,
        image_analysis: dict[str, Any] | None,
    ) -> str | None:
        if not self.text_llm.enabled:
            return None
        payload = {
            "message": message,
            "focus": focus,
            "conversation_history": history[-12:],
            "image_analysis": image_analysis,
            "merchant_data": compact_merchant_data(self.data),
        }
        return self.text_llm.complete(
            system=MERCHANT_SYSTEM_PROMPT,
            user="只输出给商家看的最终回复，不要 JSON，不要 markdown。\n" + json.dumps(payload, ensure_ascii=False, default=str),
        )


def load_merchant_analytics() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "data" / "merchant_analytics.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_history(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in (history or [])[-12:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            result.append({"role": role, "content": str(content)[:600]})
    return result


async def analyze_merchant_image(
    *,
    settings: Settings,
    image_bytes: bytes,
    image_type: str,
) -> dict[str, Any]:
    start = time.perf_counter()
    if not settings.kimi_api_key:
        return {
            "success": False,
            "analysis": None,
            "error": "KIMI_API_KEY is not configured",
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    user_content = [
        {"type": "image_url", "image_url": {"url": f"data:{image_type};base64,{image_b64}"}},
        {"type": "text", "text": "请分析这张商家经营相关图片，提取对经营分析有用的信号。"},
    ]
    try:
        async with httpx.AsyncClient(timeout=settings.kimi_timeout_seconds) as client:
            response = await client.post(
                f"{settings.kimi_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.kimi_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.kimi_model,
                    "messages": [
                        {"role": "system", "content": MERCHANT_IMAGE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 220,
                    "temperature": 0.5,
                },
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            analysis = parse_json_object(raw)
            normalize_merchant_image(analysis)
            return {
                "success": True,
                "analysis": analysis,
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }
    except Exception as exc:
        return {
            "success": False,
            "analysis": None,
            "error": str(exc),
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }


def parse_json_object(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.strip("`").strip()
        if clean.startswith("json"):
            clean = clean[4:].strip()
    if not clean.startswith("{"):
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            clean = clean[start : end + 1]
    parsed = json.loads(clean)
    if not isinstance(parsed, dict):
        raise ValueError("Kimi response is not a JSON object")
    return parsed


def normalize_merchant_image(analysis: dict[str, Any]) -> None:
    analysis.setdefault("image_summary", "图片内容可用于经营参考")
    analysis.setdefault("business_signal", "")
    analysis.setdefault("risk_or_opportunity", "")
    focus = analysis.get("suggested_analysis_focus")
    if focus not in FOCUS_LABELS:
        analysis["suggested_analysis_focus"] = "overview"
    analysis["evidence_valid"] = bool(analysis.get("evidence_valid", True))


FOCUS_LABELS = {
    "overview": "经营大盘",
    "gmv": "GMV趋势",
    "category": "类目表现",
    "brand": "品牌机会",
    "city": "城市投放",
    "users": "用户分层",
    "fulfillment": "履约时效",
    "aftersales": "售后压力",
    "conversion": "转化效率",
}


def detect_focus(message: str, image_analysis: dict[str, Any] | None = None) -> str:
    if image_analysis and image_analysis.get("suggested_analysis_focus") in FOCUS_LABELS:
        return str(image_analysis["suggested_analysis_focus"])
    text = message.lower()
    checks = [
        ("fulfillment", ["履约", "发货", "物流", "慢", "时效"]),
        ("category", ["类目", "品类", "商品结构", "卖得好"]),
        ("brand", ["品牌", "爆品", "产品"]),
        ("city", ["城市", "地区", "省份", "投放"]),
        ("users", ["用户", "会员", "复购", "人群", "分层"]),
        ("conversion", ["转化", "加购", "点击", "漏斗"]),
        ("aftersales", ["售后", "退款", "投诉", "客服"]),
        ("gmv", ["gmv", "销售", "趋势", "增长", "营收", "订单"]),
    ]
    for focus, words in checks:
        if any(word in text for word in words):
            return focus
    return "overview"


def compact_merchant_data(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "overview": data.get("overview", {}),
        "monthly_latest": (data.get("monthly") or [])[-3:],
        "top_categories": (data.get("categories") or [])[:6],
        "top_brands": (data.get("brands") or [])[:6],
        "top_cities": (data.get("cities") or [])[:6],
        "tiers": data.get("tiers", []),
        "channels": data.get("channels", []),
        "agent_insights": data.get("agent_insights", []),
    }


def build_chart_directive(focus: str, data: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "overview": {"chart": "monthly", "title": "全年 GMV 趋势"},
        "gmv": {"chart": "monthly", "title": "GMV 与订单趋势"},
        "category": {"chart": "categories", "title": "类目经营表现"},
        "brand": {"chart": "brands", "title": "品牌 GMV 机会"},
        "city": {"chart": "cities", "title": "城市投放机会"},
        "users": {"chart": "tiers", "title": "用户分层"},
        "fulfillment": {"chart": "fulfillment", "title": "履约时效风险"},
        "aftersales": {"chart": "categories", "title": "售后压力关联类目"},
        "conversion": {"chart": "channels", "title": "渠道与转化效率"},
    }
    directive = mapping.get(focus, mapping["overview"]).copy()
    directive["focus"] = focus
    directive["label"] = FOCUS_LABELS.get(focus, "经营大盘")
    return directive


def fallback_answer(
    *,
    message: str,
    data: dict[str, Any],
    focus: str,
    image_analysis: dict[str, Any] | None,
) -> str:
    overview = data.get("overview", {})
    categories = data.get("categories") or []
    top_category = categories[0] if categories else {}
    slow_category = max(categories, key=lambda item: item.get("avg_fulfillment", 0), default={})
    if image_analysis:
        signal = image_analysis.get("business_signal") or image_analysis.get("image_summary")
        return f"图我看到了，关键信号是：{signal}。我会把左侧图表切到{FOCUS_LABELS.get(focus, '经营大盘')}，先看对应指标。📊"
    if focus == "category":
        return f"{top_category.get('name', '头部类目')}是当前主力，GMV {format_money(top_category.get('gmv'))}。建议先保资源位，再看履约和售后压力。📊"
    if focus == "fulfillment":
        return f"{slow_category.get('name', '部分类目')}履约最慢，平均 {slow_category.get('avg_fulfillment', '-')} 小时。建议设发货预警，先压这条链路。🚚"
    if focus == "users":
        return f"全年用户 {format_int(overview.get('users'))}，平均购买 {overview.get('avg_purchase_frequency')} 次。优先做高价值用户复购，比泛投放更稳。👥"
    if focus == "conversion":
        return f"整体加购率 {float(overview.get('cart_rate') or 0) * 100:.1f}%。可以用券、包邮门槛和限时提醒拉转化。📈"
    return f"我先看大盘：GMV {format_money(overview.get('gmv'))}，订单 {format_int(overview.get('orders'))}，客单价 {format_money(overview.get('aov'))}。当前重点是放大高 GMV 类目，同时压履约慢的类目。📊"


def format_money(value: Any) -> str:
    num = float(value or 0)
    if num >= 100000000:
        return f"{num / 100000000:.2f}亿"
    if num >= 10000:
        return f"{num / 10000:.1f}万"
    return f"{num:.0f}"


def format_int(value: Any) -> str:
    return f"{int(float(value or 0)):,}"


def clean_answer(answer: str) -> str:
    return answer.replace("**", "").strip()
