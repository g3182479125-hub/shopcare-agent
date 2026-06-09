from __future__ import annotations

from typing import Any

from app.config import Settings


class OptionalLLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = bool(settings.llm_api_key.strip())
        self._client = None

    def _ensure_client(self):
        if not self.enabled:
            return None
        if self._client is None:
            from openai import OpenAI

            kwargs: dict[str, Any] = {
                "api_key": self.settings.llm_api_key,
                "timeout": self.settings.llm_timeout_seconds,
            }
            if self.settings.llm_base_url:
                kwargs["base_url"] = self.settings.llm_base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def complete(self, *, system: str, user: str) -> str | None:
        client = self._ensure_client()
        if client is None:
            return None
        try:
            response = client.chat.completions.create(
                model=self.settings.llm_model,
                temperature=0.7,
                max_tokens=200,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return response.choices[0].message.content
        except Exception:
            return None
