from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from app.config import Settings


class KimiVisionAgent:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.kimi_api_key
        self.base_url = settings.kimi_base_url.rstrip("/")
        self.model = settings.kimi_model

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

        system_prompt = """你是电商售后图片分析专家。
用户会上传商品问题图片，请详细分析并返回严格的 JSON 格式。
不要输出任何 JSON 以外的内容，不要加 markdown 代码块。
JSON 格式如下：
{
  "product_condition": "商品外观状态的详细描述",
  "damage_details": ["损坏点1", "损坏点2"],
  "severity": "轻微|中等|严重",
  "evidence_valid": true,
  "evidence_description": "该图片能否作为售后凭证的说明",
  "suggested_action": "建议的处理方向"
}"""

        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image_type};base64,{image_b64}"},
            },
            {
                "type": "text",
                "text": f"请分析这张商品图片的问题，并判断它能否作为售后凭证。{context_str}",
            },
        ]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "max_tokens": 500,
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
