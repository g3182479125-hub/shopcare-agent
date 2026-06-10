from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.config import get_settings


class CompatRow(dict):
    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)
        self._values = list(data.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class MySQLResult:
    def __init__(self, cursor) -> None:
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return CompatRow(row) if isinstance(row, dict) else row

    def fetchall(self):
        return [CompatRow(row) if isinstance(row, dict) else row for row in self.cursor.fetchall()]


class MySQLConnection:
    is_mysql = True

    def __init__(self, raw) -> None:
        self.raw = raw

    def execute(self, sql: str, params: Any = None):
        cursor = self.raw.cursor()
        cursor.execute(translate_sql(sql), normalize_params(params))
        return MySQLResult(cursor)

    def executemany(self, sql: str, rows: list[Any]):
        cursor = self.raw.cursor()
        cursor.executemany(translate_sql(sql), rows)
        return MySQLResult(cursor)

    def executescript(self, script: str) -> None:
        for statement in split_sql_script(script):
            try:
                self.execute(statement)
            except Exception as exc:
                if is_duplicate_mysql_index(exc):
                    continue
                raise

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            self.rollback()
        self.close()


def get_db_path() -> Path:
    path = get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection():
    settings = get_settings()
    if should_use_mysql(settings):
        return get_mysql_connection(settings)
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_mysql_connection(settings):
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as exc:
        raise RuntimeError("PyMySQL is required when DATABASE_URL or MYSQL_HOST is configured.") from exc

    options = mysql_options(settings)
    raw = pymysql.connect(cursorclass=DictCursor, charset="utf8mb4", autocommit=False, **options)
    return MySQLConnection(raw)


def mysql_options(settings) -> dict[str, Any]:
    if settings.database_url:
        parsed = urlparse(settings.database_url)
        if parsed.scheme not in {"mysql", "mysql+pymysql"}:
            raise RuntimeError("DATABASE_URL must use mysql:// or mysql+pymysql:// for MySQL.")
        database = parsed.path.lstrip("/") or settings.mysql_database
        options = {
            "host": parsed.hostname or settings.mysql_host,
            "port": parsed.port or settings.mysql_port,
            "user": unquote(parsed.username or settings.mysql_user),
            "password": unquote(parsed.password or settings.mysql_password),
            "database": database,
        }
    else:
        options = {
            "host": settings.mysql_host,
            "port": settings.mysql_port,
            "user": settings.mysql_user,
            "password": settings.mysql_password,
            "database": settings.mysql_database,
        }
    if not settings.mysql_ssl_disabled:
        options["ssl"] = {}
    return options


def row_to_dict(row) -> dict | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


def is_mysql_connection(conn: Any) -> bool:
    return bool(getattr(conn, "is_mysql", False))


def should_use_mysql(settings) -> bool:
    if settings.mysql_host:
        return True
    if not settings.database_url:
        return False
    return urlparse(settings.database_url).scheme in {"mysql", "mysql+pymysql"}


def database_status() -> dict[str, Any]:
    settings = get_settings()
    mysql_url = bool(settings.database_url and urlparse(settings.database_url).scheme in {"mysql", "mysql+pymysql"})
    ignored_database_url = bool(settings.database_url and not mysql_url and not settings.mysql_host)
    return {
        "backend": "mysql" if should_use_mysql(settings) else "sqlite",
        "mysql_configured": bool(settings.mysql_host or mysql_url),
        "ignored_database_url": ignored_database_url,
        "database": settings.mysql_database if should_use_mysql(settings) else str(get_db_path()),
    }


def init_schema(conn) -> None:
    if is_mysql_connection(conn):
        conn.executescript(MYSQL_SCHEMA)
    else:
        conn.executescript(SQLITE_SCHEMA)
    _ensure_columns(
        conn,
        "app_llm_cache",
        {
            "semantic_key": "TEXT",
            "semantic_terms": "TEXT",
            "prompt_preview": "TEXT",
        },
    )
    conn.commit()


def _ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    existing = column_names(conn, table)
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {mysql_type(definition) if is_mysql_connection(conn) else definition}")


def column_names(conn, table: str) -> set[str]:
    if is_mysql_connection(conn):
        rows = conn.execute(
            """
            SELECT COLUMN_NAME AS name
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?
            """,
            [table],
        ).fetchall()
        return {row["name"] for row in rows}
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _insert_rows(conn, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    quoted_columns = ", ".join(columns)
    op = "REPLACE" if is_mysql_connection(conn) else "INSERT OR REPLACE"
    sql = f"{op} INTO {table} ({quoted_columns}) VALUES ({placeholders})"
    conn.executemany(sql, [[row.get(column) for column in columns] for row in rows])


def load_demo_seed_if_empty(conn) -> None:
    order_count = conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()[0]
    if order_count:
        return

    seed_path = Path(__file__).resolve().parent / "data" / "demo_seed.json"
    if not seed_path.exists():
        return

    seed = json.loads(seed_path.read_text(encoding="utf-8-sig"))
    _insert_rows(conn, "orders", seed.get("orders", []))
    _insert_rows(conn, "users", seed.get("users", []))
    _insert_rows(conn, "aftersales_cases", seed.get("aftersales_cases", []))
    conn.commit()


def ensure_database() -> None:
    with get_connection() as conn:
        init_schema(conn)
        load_demo_seed_if_empty(conn)


def translate_sql(sql: str) -> str:
    clean = sql.strip()
    clean = re.sub(r"\bINSERT\s+OR\s+REPLACE\b", "REPLACE", clean, flags=re.I)
    clean = clean.replace("?", "%s")
    return clean


def normalize_params(params: Any) -> Any:
    if params is None:
        return None
    if isinstance(params, tuple):
        return params
    if isinstance(params, list):
        return tuple(params)
    return params


def split_sql_script(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";") if statement.strip()]


def mysql_type(definition: str) -> str:
    upper = definition.upper()
    if upper == "TEXT":
        return "LONGTEXT"
    return definition


def is_integrity_error(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    return exc.__class__.__name__ == "IntegrityError"


def is_duplicate_mysql_index(exc: Exception) -> bool:
    args = getattr(exc, "args", ())
    code = args[0] if args else None
    message = str(exc).lower()
    return code == 1061 or "duplicate key name" in message


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    user_id TEXT,
    product_id TEXT,
    order_time TEXT,
    quantity INTEGER,
    amount REAL,
    payment_method TEXT,
    promotion_type TEXT,
    order_status TEXT,
    shipping_city TEXT,
    fulfillment_time INTEGER,
    gender TEXT,
    age INTEGER,
    user_province_name TEXT,
    product_name TEXT,
    brand TEXT,
    category TEXT,
    price REAL,
    is_hot INTEGER,
    launch_date TEXT,
    product_region_id TEXT,
    product_province_name TEXT,
    product_region_level TEXT,
    description TEXT
);
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    user_name TEXT,
    gender TEXT,
    age INTEGER,
    register_time TEXT,
    register_channel TEXT,
    user_region_id TEXT,
    user_province_name TEXT,
    user_region_level TEXT,
    user_province_population INTEGER,
    user_province_gdp REAL,
    total_purchase_times INTEGER,
    total_purchase_amount REAL,
    last_purchase_time TEXT,
    click_count INTEGER,
    cart_count INTEGER,
    user_tier TEXT
);
CREATE TABLE IF NOT EXISTS aftersales_cases (
    case_id TEXT PRIMARY KEY,
    order_id TEXT,
    user_id TEXT,
    product_id TEXT,
    created_at TEXT,
    case_channel TEXT,
    case_type TEXT,
    reason_code TEXT,
    user_description TEXT,
    order_status TEXT,
    category TEXT,
    brand TEXT,
    product_name TEXT,
    amount REAL,
    payment_method TEXT,
    shipping_city TEXT,
    fulfillment_time_hours INTEGER,
    user_tier TEXT,
    total_purchase_times INTEGER,
    total_purchase_amount REAL,
    priority TEXT,
    risk_flags TEXT,
    agent_decision TEXT,
    resolution TEXT,
    refund_amount REAL,
    compensation_amount REAL,
    case_status TEXT,
    sla_hours INTEGER,
    resolved_at TEXT,
    satisfaction_score REAL,
    policy_basis TEXT,
    need_human_review INTEGER,
    source_order_time TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(order_status);
CREATE INDEX IF NOT EXISTS idx_orders_category ON orders(category);
CREATE INDEX IF NOT EXISTS idx_cases_order_id ON aftersales_cases(order_id);
CREATE INDEX IF NOT EXISTS idx_cases_reason ON aftersales_cases(reason_code);
CREATE INDEX IF NOT EXISTS idx_cases_category ON aftersales_cases(category);
CREATE INDEX IF NOT EXISTS idx_cases_priority ON aftersales_cases(priority);
CREATE TABLE IF NOT EXISTS app_users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'merchant')),
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS app_conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'merchant')),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES app_users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS app_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    sender TEXT NOT NULL CHECK(sender IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(conversation_id) REFERENCES app_conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_app_users_email ON app_users(email);
CREATE INDEX IF NOT EXISTS idx_app_conversations_user ON app_conversations(user_id, role, updated_at);
CREATE INDEX IF NOT EXISTS idx_app_messages_conversation ON app_messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS app_llm_cache (
    cache_key TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    system_hash TEXT NOT NULL,
    user_hash TEXT NOT NULL,
    semantic_key TEXT,
    semantic_terms TEXT,
    prompt_preview TEXT,
    response TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_llm_cache_expires ON app_llm_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_app_llm_cache_profile_model ON app_llm_cache(profile, provider, model, expires_at);
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'merchant')),
    title TEXT NOT NULL,
    source_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES app_users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'merchant')),
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_user_role ON knowledge_documents(user_id, role, created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_role ON knowledge_chunks(role, document_id);
CREATE TABLE IF NOT EXISTS agent_workflow_runs (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    role TEXT NOT NULL CHECK(role IN ('user', 'merchant', 'system')),
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    current_node TEXT NOT NULL DEFAULT 'start',
    state TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES app_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_workflow_runs_user ON agent_workflow_runs(user_id, role, updated_at);
CREATE INDEX IF NOT EXISTS idx_agent_workflow_runs_status ON agent_workflow_runs(status, updated_at);
"""

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64),
    product_id VARCHAR(64),
    order_time VARCHAR(64),
    quantity INTEGER,
    amount DOUBLE,
    payment_method VARCHAR(64),
    promotion_type VARCHAR(128),
    order_status VARCHAR(64),
    shipping_city VARCHAR(128),
    fulfillment_time INTEGER,
    gender VARCHAR(32),
    age INTEGER,
    user_province_name VARCHAR(128),
    product_name VARCHAR(255),
    brand VARCHAR(128),
    category VARCHAR(128),
    price DOUBLE,
    is_hot INTEGER,
    launch_date VARCHAR(64),
    product_region_id VARCHAR(64),
    product_province_name VARCHAR(128),
    product_region_level VARCHAR(64),
    description TEXT
);
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(64) PRIMARY KEY,
    user_name VARCHAR(128),
    gender VARCHAR(32),
    age INTEGER,
    register_time VARCHAR(64),
    register_channel VARCHAR(128),
    user_region_id VARCHAR(64),
    user_province_name VARCHAR(128),
    user_region_level VARCHAR(64),
    user_province_population INTEGER,
    user_province_gdp DOUBLE,
    total_purchase_times INTEGER,
    total_purchase_amount DOUBLE,
    last_purchase_time VARCHAR(64),
    click_count INTEGER,
    cart_count INTEGER,
    user_tier VARCHAR(64)
);
CREATE TABLE IF NOT EXISTS aftersales_cases (
    case_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64),
    user_id VARCHAR(64),
    product_id VARCHAR(64),
    created_at VARCHAR(64),
    case_channel VARCHAR(128),
    case_type VARCHAR(128),
    reason_code VARCHAR(128),
    user_description TEXT,
    order_status VARCHAR(64),
    category VARCHAR(128),
    brand VARCHAR(128),
    product_name VARCHAR(255),
    amount DOUBLE,
    payment_method VARCHAR(64),
    shipping_city VARCHAR(128),
    fulfillment_time_hours INTEGER,
    user_tier VARCHAR(64),
    total_purchase_times INTEGER,
    total_purchase_amount DOUBLE,
    priority VARCHAR(64),
    risk_flags TEXT,
    agent_decision VARCHAR(128),
    resolution VARCHAR(128),
    refund_amount DOUBLE,
    compensation_amount DOUBLE,
    case_status VARCHAR(64),
    sla_hours INTEGER,
    resolved_at VARCHAR(64),
    satisfaction_score DOUBLE,
    policy_basis TEXT,
    need_human_review INTEGER,
    source_order_time VARCHAR(64)
);
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_status ON orders(order_status);
CREATE INDEX idx_orders_category ON orders(category);
CREATE INDEX idx_cases_order_id ON aftersales_cases(order_id);
CREATE INDEX idx_cases_reason ON aftersales_cases(reason_code);
CREATE INDEX idx_cases_category ON aftersales_cases(category);
CREATE INDEX idx_cases_priority ON aftersales_cases(priority);
CREATE TABLE IF NOT EXISTS app_users (
    id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(128) NOT NULL,
    role VARCHAR(32) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL
);
CREATE TABLE IF NOT EXISTS app_conversations (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES app_users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS app_messages (
    id VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(64) NOT NULL,
    sender VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    payload LONGTEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(conversation_id) REFERENCES app_conversations(id) ON DELETE CASCADE
);
CREATE INDEX idx_app_conversations_user ON app_conversations(user_id, role, updated_at);
CREATE INDEX idx_app_messages_conversation ON app_messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS app_llm_cache (
    cache_key VARCHAR(64) PRIMARY KEY,
    profile VARCHAR(64) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    model VARCHAR(128) NOT NULL,
    system_hash VARCHAR(64) NOT NULL,
    user_hash VARCHAR(64) NOT NULL,
    semantic_key VARCHAR(64),
    semantic_terms TEXT,
    prompt_preview TEXT,
    response LONGTEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at BIGINT NOT NULL
);
CREATE INDEX idx_app_llm_cache_expires ON app_llm_cache(expires_at);
CREATE INDEX idx_app_llm_cache_profile_model ON app_llm_cache(profile, provider, model, expires_at);
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(128) NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES app_users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id VARCHAR(64) PRIMARY KEY,
    document_id VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL,
    chunk_index INTEGER NOT NULL,
    content LONGTEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
);
CREATE INDEX idx_knowledge_documents_user_role ON knowledge_documents(user_id, role, created_at);
CREATE INDEX idx_knowledge_chunks_role ON knowledge_chunks(role, document_id);
CREATE TABLE IF NOT EXISTS agent_workflow_runs (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64),
    role VARCHAR(32) NOT NULL,
    workflow_name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    current_node VARCHAR(128) NOT NULL DEFAULT 'start',
    state LONGTEXT NOT NULL,
    result LONGTEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES app_users(id) ON DELETE SET NULL
);
CREATE INDEX idx_agent_workflow_runs_user ON agent_workflow_runs(user_id, role, updated_at);
CREATE INDEX idx_agent_workflow_runs_status ON agent_workflow_runs(status, updated_at);
"""
