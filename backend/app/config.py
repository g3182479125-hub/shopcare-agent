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
        self.llm_temperature = float(get("LLM_TEMPERATURE", "0.7") or "0.7")
        self.llm_timeout_seconds = float(get("LLM_TIMEOUT_SECONDS", "6") or "6")
        self.llm_cache_enabled = get("LLM_CACHE_ENABLED", "true").lower() not in {"0", "false", "no"}
        self.llm_cache_ttl_seconds = int(get("LLM_CACHE_TTL_SECONDS", str(60 * 60 * 24)) or str(60 * 60 * 24))
        self.llm_semantic_cache_enabled = get("LLM_SEMANTIC_CACHE_ENABLED", "true").lower() not in {"0", "false", "no"}
        self.llm_semantic_cache_threshold = float(get("LLM_SEMANTIC_CACHE_THRESHOLD", "0.88") or "0.88")
        self.llm_semantic_cache_max_candidates = int(get("LLM_SEMANTIC_CACHE_MAX_CANDIDATES", "80") or "80")

        self.llm_chat_provider = get("LLM_CHAT_PROVIDER", self.llm_provider)
        self.llm_chat_model = get("LLM_CHAT_MODEL", self.llm_model)
        self.llm_reason_provider = get("LLM_REASON_PROVIDER", self.llm_provider)
        self.llm_reason_model = get("LLM_REASON_MODEL", get("LLM_DEEP_THINK_MODEL", self.llm_model))
        self.llm_agent_provider = get("LLM_AGENT_PROVIDER", self.llm_provider)
        self.llm_agent_model = get("LLM_AGENT_MODEL", self.llm_model)

        self.ollama_base_url = get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.ollama_api_key = get("OLLAMA_API_KEY", "ollama")
        self.ollama_chat_model = get("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
        self.ollama_reason_model = get("OLLAMA_REASON_MODEL", "deepseek-r1:7b")
        self.ollama_agent_model = get("OLLAMA_AGENT_MODEL", self.ollama_chat_model)

        self.kimi_api_key = get("KIMI_API_KEY")
        self.kimi_base_url = get("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
        self.kimi_model = get("KIMI_MODEL", "moonshot-v1-8k-vision-preview")
        self.kimi_timeout_seconds = float(get("KIMI_TIMEOUT_SECONDS", "6") or "6")
        self.auth_secret = get("AUTH_SECRET", get("SECRET_KEY", "shopcare-local-dev-secret"))
        self.auth_token_expires_seconds = int(get("AUTH_TOKEN_EXPIRES_SECONDS", str(60 * 60 * 24 * 7)))

        self.web_search_enabled = get("WEB_SEARCH_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
        self.web_search_provider = get("WEB_SEARCH_PROVIDER", "serpapi")
        self.web_search_api_key = get("WEB_SEARCH_API_KEY", get("SERPAPI_API_KEY", ""))
        self.web_search_base_url = get("WEB_SEARCH_BASE_URL", "https://serpapi.com/search.json")
        self.web_search_timeout_seconds = float(get("WEB_SEARCH_TIMEOUT_SECONDS", "8") or "8")
        self.web_search_max_results = int(get("WEB_SEARCH_MAX_RESULTS", "5") or "5")
        self.knowledge_vector_provider = get("KNOWLEDGE_VECTOR_PROVIDER", "auto")
        self.knowledge_vector_dimensions = int(get("KNOWLEDGE_VECTOR_DIMENSIONS", "384") or "384")

        self.graph_rag_enabled = get("GRAPH_RAG_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
        self.neo4j_uri = get("NEO4J_URI", "")
        self.neo4j_user = get("NEO4J_USER", "neo4j")
        self.neo4j_password = get("NEO4J_PASSWORD", "")
        self.neo4j_database = get("NEO4J_DATABASE", "neo4j")
        self.graph_query_timeout_seconds = float(get("GRAPH_QUERY_TIMEOUT_SECONDS", "6") or "6")

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

    def llm_profile(self, profile: str = "agent") -> dict[str, str]:
        clean = (profile or "agent").lower()
        provider = {
            "chat": self.llm_chat_provider,
            "reason": self.llm_reason_provider,
            "agent": self.llm_agent_provider,
        }.get(clean, self.llm_agent_provider)
        model = {
            "chat": self.llm_chat_model,
            "reason": self.llm_reason_model,
            "agent": self.llm_agent_model,
        }.get(clean, self.llm_agent_model)
        if provider.lower() == "ollama":
            model = {
                "chat": self.ollama_chat_model,
                "reason": self.ollama_reason_model,
                "agent": self.ollama_agent_model,
            }.get(clean, model)
            return {
                "provider": "ollama",
                "api_key": self.ollama_api_key,
                "base_url": self.ollama_base_url,
                "model": model,
            }
        return {
            "provider": provider,
            "api_key": self.llm_api_key,
            "base_url": self.llm_base_url,
            "model": model,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
