from __future__ import annotations

from typing import Any

from app.config import Settings
from app.services.llm_cache import LLMCache, build_cache_key, cache_meta


class OptionalLLMClient:
    def __init__(self, settings: Settings, *, profile: str = "agent") -> None:
        self.settings = settings
        self.profile = profile
        self.profile_config = settings.llm_profile(profile)
        self.enabled = bool(self.profile_config["api_key"].strip())
        self._client = None
        self._client_key: tuple[str, str] | None = None
        self.cache = LLMCache(settings.llm_cache_ttl_seconds) if settings.llm_cache_enabled else None
        self.last_meta = cache_meta(profile, self.profile_config["provider"], self.profile_config["model"], "disabled")

    def _ensure_client(self):
        if not self.enabled:
            return None
        client_key = (self.profile_config["base_url"], self.profile_config["api_key"])
        if self._client is None or self._client_key != client_key:
            try:
                from openai import OpenAI
            except ImportError:
                self.enabled = False
                return None

            kwargs: dict[str, Any] = {
                "api_key": self.profile_config["api_key"],
                "timeout": self.settings.llm_timeout_seconds,
            }
            if self.profile_config["base_url"]:
                kwargs["base_url"] = self.profile_config["base_url"]
            self._client = OpenAI(**kwargs)
            self._client_key = client_key
        return self._client

    def complete(self, *, system: str, user: str) -> str | None:
        cache_key = build_cache_key(
            profile=self.profile,
            provider=self.profile_config["provider"],
            model=self.profile_config["model"],
            system=system,
            user=user,
        )
        if self.cache:
            cached = self.cache.get(cache_key=cache_key)
            if cached:
                self.last_meta = cache_meta(self.profile, self.profile_config["provider"], self.profile_config["model"], "cache")
                return cached

        client = self._ensure_client()
        if client is None:
            self.last_meta = cache_meta(self.profile, self.profile_config["provider"], self.profile_config["model"], "disabled")
            return None
        try:
            response = client.chat.completions.create(
                model=self.profile_config["model"],
                temperature=self.settings.llm_temperature,
                max_tokens=200,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            answer = response.choices[0].message.content
            if answer and self.cache:
                self.cache.set(
                    cache_key=cache_key,
                    profile=self.profile,
                    provider=self.profile_config["provider"],
                    model=self.profile_config["model"],
                    system=system,
                    user=user,
                    response=answer,
                )
            self.last_meta = cache_meta(self.profile, self.profile_config["provider"], self.profile_config["model"], "api")
            return answer
        except Exception:
            self.last_meta = cache_meta(self.profile, self.profile_config["provider"], self.profile_config["model"], "error")
            return None
