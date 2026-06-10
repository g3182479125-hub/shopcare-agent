from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings


REALTIME_SEARCH_KEYWORDS = {
    "latest",
    "today",
    "news",
    "current",
    "now",
    "trend",
    "competitor",
    "industry",
    "policy update",
    "search",
    "google",
    "web",
    "online",
    "最新",
    "今天",
    "现在",
    "实时",
    "新闻",
    "趋势",
    "竞品",
    "行业",
    "政策更新",
    "市场",
    "搜索",
    "上网",
    "联网",
    "搜一下",
    "查一下",
    "查查",
    "全网",
    "网上",
}


MERCHANT_SEARCH_KEYWORDS = {
    "怎么增长",
    "怎么降",
    "投放",
    "竞对",
    "大盘",
    "机会",
}



def needs_realtime_search(message: str, *, role: str = "user") -> bool:
    text = (message or "").lower()
    if any(keyword in text for keyword in REALTIME_SEARCH_KEYWORDS):
        return True
    if role == "merchant" and any(word in text for word in MERCHANT_SEARCH_KEYWORDS):
        return True
    return False


class WebSearchClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.web_search_enabled and self.settings.web_search_api_key.strip())

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.web_search_enabled,
            "provider": self.settings.web_search_provider,
            "configured": bool(self.settings.web_search_api_key.strip()),
            "max_results": self.settings.web_search_max_results,
        }

    def search(self, query: str, *, max_results: int | None = None) -> dict[str, Any]:
        start = time.perf_counter()
        limit = max(1, min(max_results or self.settings.web_search_max_results, 10))
        if not self.settings.web_search_enabled:
            return self._empty(query, "disabled", start)
        if not self.settings.web_search_api_key.strip():
            return self._empty(query, "missing_api_key", start)
        if self.settings.web_search_provider.lower() != "serpapi":
            return self._empty(query, "unsupported_provider", start)

        try:
            with httpx.Client(timeout=self.settings.web_search_timeout_seconds) as client:
                response = client.get(
                    self.settings.web_search_base_url,
                    params={
                        "engine": "google",
                        "q": query,
                        "api_key": self.settings.web_search_api_key,
                        "num": limit,
                        "hl": "zh-cn",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            return {
                "query": query,
                "status": "error",
                "error": str(exc),
                "items": [],
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        items = []
        for raw in payload.get("organic_results", [])[:limit]:
            link = str(raw.get("link") or "")
            parsed = urlparse(link)
            items.append(
                {
                    "title": str(raw.get("title") or "")[:160],
                    "link": link,
                    "snippet": str(raw.get("snippet") or raw.get("description") or "")[:360],
                    "source": parsed.netloc or "web",
                    "position": raw.get("position"),
                }
            )
        return {
            "query": query,
            "status": "ok",
            "provider": "serpapi",
            "items": items,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }

    def _empty(self, query: str, status: str, start: float) -> dict[str, Any]:
        return {
            "query": query,
            "status": status,
            "provider": self.settings.web_search_provider,
            "items": [],
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }
