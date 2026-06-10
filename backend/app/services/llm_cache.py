from __future__ import annotations

import hashlib
import time
from typing import Any

from app.db import get_connection


def build_cache_key(*, profile: str, provider: str, model: str, system: str, user: str) -> str:
    raw = "\n".join([profile, provider, model, normalize_prompt(system), normalize_prompt(user)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_prompt(value: str) -> str:
    return " ".join((value or "").split())


class LLMCache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = max(60, int(ttl_seconds or 86400))

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
        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO app_llm_cache
                    (cache_key, profile, provider, model, system_hash, user_hash, response, hit_count, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT hit_count FROM app_llm_cache WHERE cache_key = ?), 0), CURRENT_TIMESTAMP, ?)
                    """,
                    [
                        cache_key,
                        profile,
                        provider,
                        model,
                        hashlib.sha256(system.encode("utf-8")).hexdigest(),
                        hashlib.sha256(user.encode("utf-8")).hexdigest(),
                        response,
                        cache_key,
                        now + self.ttl_seconds,
                    ],
                )
                conn.execute("DELETE FROM app_llm_cache WHERE expires_at <= ?", [now])
                conn.commit()
        except Exception:
            return


def cache_meta(profile: str, provider: str, model: str, source: str) -> dict[str, Any]:
    return {"profile": profile, "provider": provider, "model": model, "source": source}
