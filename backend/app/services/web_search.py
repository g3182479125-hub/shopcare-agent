from __future__ import annotations

import html
import re
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

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
    "\u6700\u65b0",
    "\u4eca\u5929",
    "\u73b0\u5728",
    "\u5b9e\u65f6",
    "\u65b0\u95fb",
    "\u8d8b\u52bf",
    "\u7ade\u54c1",
    "\u884c\u4e1a",
    "\u653f\u7b56\u66f4\u65b0",
    "\u5e02\u573a",
    "\u641c\u7d22",
    "\u4e0a\u7f51",
    "\u8054\u7f51",
    "\u641c\u4e00\u4e0b",
    "\u67e5\u4e00\u4e0b",
    "\u67e5\u67e5",
    "\u5168\u7f51",
    "\u7f51\u4e0a",
}


MERCHANT_SEARCH_KEYWORDS = {
    "\u600e\u4e48\u589e\u957f",
    "\u600e\u4e48\u964d",
    "\u6295\u653e",
    "\u7ade\u5bf9",
    "\u5927\u76d8",
    "\u673a\u4f1a",
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
        return bool(self.settings.web_search_enabled)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.web_search_enabled,
            "provider": self.settings.web_search_provider,
            "configured": bool(self.settings.web_search_enabled),
            "serpapi_configured": bool(self.settings.web_search_api_key.strip()),
            "fallback_provider": "duckduckgo_html",
            "max_results": self.settings.web_search_max_results,
        }

    def search(self, query: str, *, max_results: int | None = None) -> dict[str, Any]:
        start = time.perf_counter()
        limit = max(1, min(max_results or self.settings.web_search_max_results, 10))
        if not self.settings.web_search_enabled:
            return self._empty(query, "disabled", start)

        provider = self.settings.web_search_provider.lower()
        if provider == "serpapi" and self.settings.web_search_api_key.strip():
            return self._search_serpapi(query, limit=limit, start=start)
        if provider in {"auto", "serpapi", "duckduckgo", "duckduckgo_html"}:
            return self._search_duckduckgo(query, limit=limit, start=start)
        return self._empty(query, "unsupported_provider", start)

    def _search_serpapi(self, query: str, *, limit: int, start: float) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self.settings.web_search_timeout_seconds, follow_redirects=True) as client:
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
            fallback = self._search_duckduckgo(query, limit=limit, start=start)
            fallback["serpapi_error"] = str(exc)
            return fallback

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

    def _search_duckduckgo(self, query: str, *, limit: int, start: float) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self.settings.web_search_timeout_seconds, follow_redirects=True) as client:
                response = client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 ShopCareAgent/1.0"},
                )
                response.raise_for_status()
                body = response.text
        except Exception as exc:
            return {
                "query": query,
                "status": "error",
                "provider": "duckduckgo_html",
                "error": str(exc),
                "items": [],
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        items = parse_duckduckgo_html(body, limit=limit)
        return {
            "query": query,
            "status": "ok" if items else "empty",
            "provider": "duckduckgo_html",
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


def parse_duckduckgo_html(body: str, *, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.S,
    )
    for match in pattern.finditer(body):
        href = html.unescape(match.group("href"))
        title = clean_html(match.group("title"))
        snippet = clean_html(match.group("snippet"))
        link = normalize_duckduckgo_link(href)
        if not title or not link:
            continue
        parsed = urlparse(link)
        results.append(
            {
                "title": title[:160],
                "link": link,
                "snippet": snippet[:360],
                "source": parsed.netloc or "web",
                "position": len(results) + 1,
            }
        )
        if len(results) >= limit:
            break
    return results


def clean_html(value: str) -> str:
    value = re.sub(r"<.*?>", " ", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_duckduckgo_link(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        raw = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(raw)
    return href
