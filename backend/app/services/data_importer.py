from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from app.db import get_connection, init_schema


def normalize_header(name: str | None) -> str:
    return (name or "").replace("\ufeff", "").replace("锘縪", "o").strip()


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def user_tier(total_amount: float, total_times: int) -> str:
    if total_amount >= 5000 or total_times >= 8:
        return "VIP"
    if total_amount >= 1500 or total_times >= 4:
        return "HighValue"
    if total_amount >= 500 or total_times >= 2:
        return "Regular"
    return "New"


def read_rows(path: Path, encoding: str) -> Iterable[dict[str, str]]:
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield {normalize_header(k): (v or "").strip() for k, v in row.items()}


def import_orders(path: Path) -> int:
    rows = []
    count = 0
    with get_connection() as conn:
        conn.execute("DELETE FROM orders")
        for row in read_rows(path, "utf-8"):
            rows.append((
                row.get("order_id"), row.get("user_id"), row.get("product_id"), row.get("order_time"),
                to_int(row.get("quantity")), to_float(row.get("amount")), row.get("payment_method"),
                row.get("promotion_type"), row.get("order_status"), row.get("shipping_city"),
                to_int(row.get("fulfillment_time")), row.get("gender"), to_int(row.get("age")),
                row.get("user_province_name"), row.get("product_name"), row.get("brand"), row.get("category"),
                to_float(row.get("price")), to_int(row.get("is_hot")), row.get("launch_date"),
                row.get("product_region_id"), row.get("product_province_name"), row.get("product_region_level"),
                row.get("description"),
            ))
            count += 1
            if len(rows) >= 5000:
                conn.executemany("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                rows.clear()
        if rows:
            conn.executemany("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    return count


def import_users(path: Path) -> int:
    rows = []
    count = 0
    with get_connection() as conn:
        conn.execute("DELETE FROM users")
        for row in read_rows(path, "utf-8"):
            total_times = to_int(row.get("total_purchase_times"))
            total_amount = to_float(row.get("total_purchase_amount"))
            rows.append((
                row.get("user_id"), row.get("user_name"), row.get("gender"), to_int(row.get("age")),
                row.get("register_time"), row.get("register_channel"), row.get("user_region_id"),
                row.get("user_province_name"), row.get("user_region_level"), to_int(row.get("user_province_population")),
                to_float(row.get("user_province_gdp")), total_times, total_amount, row.get("last_purchase_time"),
                to_int(row.get("click_count")), to_int(row.get("cart_count")), user_tier(total_amount, total_times),
            ))
            count += 1
            if len(rows) >= 5000:
                conn.executemany("INSERT OR REPLACE INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                rows.clear()
        if rows:
            conn.executemany("INSERT OR REPLACE INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    return count


def import_cases(path: Path) -> int:
    rows = []
    count = 0
    with get_connection() as conn:
        conn.execute("DELETE FROM aftersales_cases")
        for row in read_rows(path, "utf-8-sig"):
            rows.append((
                row.get("case_id"), row.get("order_id"), row.get("user_id"), row.get("product_id"), row.get("created_at"),
                row.get("case_channel"), row.get("case_type"), row.get("reason_code"), row.get("user_description"),
                row.get("order_status"), row.get("category"), row.get("brand"), row.get("product_name"),
                to_float(row.get("amount")), row.get("payment_method"), row.get("shipping_city"),
                to_int(row.get("fulfillment_time_hours")), row.get("user_tier"), to_int(row.get("total_purchase_times")),
                to_float(row.get("total_purchase_amount")), row.get("priority"), row.get("risk_flags"),
                row.get("agent_decision"), row.get("resolution"), to_float(row.get("refund_amount")),
                to_float(row.get("compensation_amount")), row.get("case_status"), to_int(row.get("sla_hours")),
                row.get("resolved_at"), to_float(row.get("satisfaction_score")), row.get("policy_basis"),
                to_int(row.get("need_human_review")), row.get("source_order_time"),
            ))
            count += 1
            if len(rows) >= 5000:
                conn.executemany("INSERT OR REPLACE INTO aftersales_cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                rows.clear()
        if rows:
            conn.executemany("INSERT OR REPLACE INTO aftersales_cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    return count


def import_all(order_csv: Path, user_csv: Path, aftersales_csv: Path, report_path: Path | None = None) -> dict[str, Any]:
    with get_connection() as conn:
        init_schema(conn)
    report = {
        "orders": import_orders(order_csv),
        "users": import_users(user_csv),
        "aftersales_cases": import_cases(aftersales_csv),
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
