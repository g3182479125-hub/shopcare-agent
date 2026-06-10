from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.config import get_settings


def get_db_path() -> Path:
    path = get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
        """
    )
    conn.commit()


def _insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    quoted_columns = ", ".join(columns)
    sql = f"INSERT OR REPLACE INTO {table} ({quoted_columns}) VALUES ({placeholders})"
    conn.executemany(sql, [[row.get(column) for column in columns] for row in rows])


def load_demo_seed_if_empty(conn: sqlite3.Connection) -> None:
    order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
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
