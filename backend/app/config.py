from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


class Settings:
    def __init__(self) -> None:
        env_path = Path(__file__).resolve().parents[1] / ".env"
        file_env = _load_env_file(env_path)

        def get(name: str, default: str = "") -> str:
            return os.getenv(name, file_env.get(name, default))

        self.app_name = get("APP_NAME", "ShopCare Agent")
        self.app_env = get("APP_ENV", "local")
        self.shopcare_db_path = get("SHOPCARE_DB_PATH", "./data/shopcare.db")
        self.order_csv_path = get("ORDER_CSV_PATH")
        self.user_csv_path = get("USER_CSV_PATH")
        self.aftersales_csv_path = get("AFTERSALES_CSV_PATH", "E:/agnet/aftersales_cases.csv")

        self.llm_provider = get("LLM_PROVIDER", "deepseek")
        self.llm_api_key = get("LLM_API_KEY")
        self.llm_base_url = get("LLM_BASE_URL", "https://api.deepseek.com")
        self.llm_model = get("LLM_MODEL", "deepseek-chat")
        self.llm_temperature = float(get("LLM_TEMPERATURE", "0.2") or "0.2")
        self.llm_timeout_seconds = float(get("LLM_TIMEOUT_SECONDS", "12") or "12")

        self.kimi_api_key = get("KIMI_API_KEY")
        self.kimi_base_url = get("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
        self.kimi_model = get("KIMI_MODEL", "moonshot-v1-8k-vision-preview")
        self.kimi_timeout_seconds = float(get("KIMI_TIMEOUT_SECONDS", "8") or "8")

        self.allow_origins = get(
            "ALLOW_ORIGINS",
            get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"),
        )

    @property
    def db_path(self) -> Path:
        path = Path(self.shopcare_db_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path

    @property
    def cors_origins(self) -> List[str]:
        return [item.strip() for item in self.allow_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
