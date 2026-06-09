from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from app.agent.prompts import KIMI_VISION_SYSTEM_PROMPT
from app.config import Settings


class KimiVisionAgent:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.kimi_api_key
        self.base_url = settings.kimi_base_url.rstrip("/")
        self.model = settings.kimi_model
        self.timeout_seconds = settings.kimi_timeout_seconds

    async def analyze_image(
        self,
        *,
        image_bytes: bytes,
        image_type: str,
        order_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        if not self.api_key:
            return {
                "success": False,
                "analysis": None,
                "error": "KIMI_API_KEY is not configured",
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        context_str = ""
        if order_context:
            context_str = (
                "\n相关订单信息："
                f"\n- 商品：{order_context.get('product_name', '未知')}"
                f"\n- 类目：{order_context.get('category', '未知')}"
                f"\n- 金额：{order_context.get('amount', '未知')}元"
            )

        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image_type};base64,{image_b64}"},
            },
            {
                "type": "text",
                "text": f"请分析这张商品问题图片，判断它能否作为售后凭证。{context_str}",
            },
        ]

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": KIMI_VISION_SYSTEM_PROMPT},
                            {"role": "user", "content": user_content},
                        ],
                        "max_tokens": 200,
                        "temperature": 0.7,
                    },
                )
                response.raise_for_status()
                result = response.json()
                raw_text = result["choices"][0]["message"]["content"]
                analysis = _parse_json_object(raw_text)
                _normalize_analysis(analysis)
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


def _parse_json_object(text: str) -> dict[str, Any]:
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


def _normalize_analysis(analysis: dict[str, Any]) -> None:
    analysis.setdefault("product_condition", "未能识别明确商品状态")
    details = analysis.get("damage_details")
    if not isinstance(details, list):
        analysis["damage_details"] = [str(details)] if details else []
    severity = analysis.get("severity")
    if severity not in {"轻微", "中等", "严重"}:
        analysis["severity"] = "中等"
    analysis["evidence_valid"] = bool(analysis.get("evidence_valid"))
    analysis.setdefault("evidence_description", "")
    analysis.setdefault("suggested_action", "")
