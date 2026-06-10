from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from app.db import get_connection


def build_cache_key(*, profile: str, provider: str, model: str, system: str, user: str) -> str:
    raw = "\n".join([profile, provider, model, normalize_prompt(system), normalize_prompt(user)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_prompt(value: str) -> str:
    return " ".join((value or "").split())


class LLMCache:
    def __init__(self, ttl_seconds: int, *, semantic_enabled: bool = True, semantic_threshold: float = 0.88, max_candidates: int = 80) -> None:
        self.ttl_seconds = max(60, int(ttl_seconds or 86400))
        self.semantic_enabled = semantic_enabled
        self.semantic_threshold = min(0.99, max(0.5, float(semantic_threshold or 0.88)))
        self.max_candidates = max(10, min(300, int(max_candidates or 80)))

    def get(self, *, cache_key: str) -> str | None:
        now = int(time.time())
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT response FROM app_llm_cache WHERE cache_key = ? AND expires_at > ?",
                    [cache_key, now],
                ).fetchone()
                if not row:
                    return None
                conn.execute(
                    "UPDATE app_llm_cache SET hit_count = hit_count + 1, updated_at = CURRENT_TIMESTAMP WHERE cache_key = ?",
                    [cache_key],
                )
                conn.commit()
                return str(row["response"])
        except Exception:
            return None

    def get_semantic(
        self,
        *,
        profile: str,
        provider: str,
        model: str,
        system: str,
        user: str,
    ) -> tuple[str | None, float]:
        if not self.semantic_enabled:
            return None, 0.0
        now = int(time.time())
        terms = semantic_terms(system=system, user=user)
        if len(terms) < 3:
            return None, 0.0
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT cache_key, response, semantic_terms
                    FROM app_llm_cache
                    WHERE profile = ? AND provider = ? AND model = ? AND expires_at > ? AND semantic_terms IS NOT NULL
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    [profile, provider, model, now, self.max_candidates],
                ).fetchall()
                best_score = 0.0
                best_row = None
                for row in rows:
                    candidate_terms = set(json.loads(row["semantic_terms"] or "[]"))
                    score = jaccard(terms, candidate_terms)
                    if score > best_score:
                        best_score = score
                        best_row = row
                if not best_row or best_score < self.semantic_threshold:
                    return None, best_score
                conn.execute(
                    "UPDATE app_llm_cache SET hit_count = hit_count + 1, updated_at = CURRENT_TIMESTAMP WHERE cache_key = ?",
                    [best_row["cache_key"]],
                )
                conn.commit()
                return str(best_row["response"]), best_score
        except Exception:
            return None, 0.0

    def set(
        self,
        *,
        cache_key: str,
        profile: str,
        provider: str,
        model: str,
        system: str,
        user: str,
        response: str,
    ) -> None:
        if not response:
            return
        now = int(time.time())
        terms = sorted(semantic_terms(system=system, user=user))
        semantic_key = hashlib.sha256(" ".join(terms).encode("utf-8")).hexdigest() if terms else None
        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO app_llm_cache
                    (cache_key, profile, provider, model, system_hash, user_hash, semantic_key, semantic_terms, prompt_preview, response, hit_count, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT hit_count FROM app_llm_cache WHERE cache_key = ?), 0), CURRENT_TIMESTAMP, ?)
                    """,
                    [
                        cache_key,
                        profile,
                        provider,
                        model,
                        hashlib.sha256(system.encode("utf-8")).hexdigest(),
                        hashlib.sha256(user.encode("utf-8")).hexdigest(),
                        semantic_key,
                        json.dumps(terms, ensure_ascii=False),
                        normalize_prompt(user)[:500],
                        response,
                        cache_key,
                        now + self.ttl_seconds,
                    ],
                )
                conn.execute("DELETE FROM app_llm_cache WHERE expires_at <= ?", [now])
                conn.commit()
        except Exception:
            return

    def stats(self) -> dict[str, Any]:
        try:
            with get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS entries,
                        COALESCE(SUM(hit_count), 0) AS hits,
                        COALESCE(SUM(CASE WHEN semantic_terms IS NOT NULL THEN 1 ELSE 0 END), 0) AS semantic_entries
                    FROM app_llm_cache
                    WHERE expires_at > ?
                    """,
                    [int(time.time())],
                ).fetchone()
                return {
                    "entries": int(row["entries"] or 0),
                    "hits": int(row["hits"] or 0),
                    "semantic_entries": int(row["semantic_entries"] or 0),
                }
        except Exception:
            return {"entries": 0, "hits": 0, "semantic_entries": 0}


def cache_meta(profile: str, provider: str, model: str, source: str) -> dict[str, Any]:
    return {"profile": profile, "provider": provider, "model": model, "source": source}


def semantic_terms(*, system: str, user: str) -> set[str]:
    text = extract_semantic_text(user) or user
    text = normalize_prompt(text).lower()
    raw_terms = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text)
    terms: set[str] = set()
    for term in raw_terms:
        if term in STOP_TERMS:
            continue
        terms.add(term)
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 2:
            terms.update(term[index : index + 2] for index in range(len(term) - 1))
    system_hash = hashlib.sha1(normalize_prompt(system).encode("utf-8")).hexdigest()[:10]
    terms.add(f"sys:{system_hash}")
    return terms


def extract_semantic_text(user: str) -> str:
    try:
        start = user.find("{")
        end = user.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(user[start : end + 1])
            pieces: list[str] = []
            for key in ("message", "intent", "focus", "context_summary"):
                value = payload.get(key)
                if value:
                    pieces.append(str(value))
            history = payload.get("conversation_history") or []
            if isinstance(history, list):
                pieces.extend(str(item.get("content", "")) for item in history[-4:] if isinstance(item, dict))
            decision = payload.get("decision") or {}
            if isinstance(decision, dict):
                pieces.extend(str(decision.get(key, "")) for key in ("status", "resolution", "reason"))
            image = payload.get("image_analysis") or {}
            if isinstance(image, dict):
                pieces.extend(str(image.get(key, "")) for key in ("product_condition", "business_signal", "suggested_action"))
            knowledge = payload.get("knowledge_hits") or []
            if isinstance(knowledge, list):
                pieces.extend(str(item.get("snippet", "")) for item in knowledge[:3] if isinstance(item, dict))
            return " ".join(piece for piece in pieces if piece)
    except Exception:
        return ""
    return ""


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


STOP_TERMS = {
    "json",
    "answer",
    "user",
    "assistant",
    "message",
    "order",
    "history",
    "context",
    "data",
    "null",
    "true",
    "false",
}
