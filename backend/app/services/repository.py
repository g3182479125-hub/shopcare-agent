from __future__ import annotations

import sqlite3
from typing import Any

from app.db import row_to_dict


class ShopcareRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return row_to_dict(row)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row_to_dict(row)

    def get_cases_for_order(self, order_id: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM aftersales_cases WHERE order_id = ? ORDER BY created_at DESC LIMIT ?",
            (order_id, limit),
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def search_cases(self, *, query: str = "", category: str | None = None, reason_code: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if reason_code:
            clauses.append("reason_code = ?")
            params.append(reason_code)
        if query:
            clauses.append("(user_description LIKE ? OR policy_basis LIKE ? OR product_name LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM aftersales_cases{where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]

    def dashboard_summary(self) -> dict[str, Any]:
        def scalar(sql: str) -> Any:
            return self.conn.execute(sql).fetchone()[0]

        def top(sql: str) -> list[dict[str, Any]]:
            return [dict(row) for row in self.conn.execute(sql).fetchall()]

        return {
            "orders": {
                "count": scalar("SELECT COUNT(*) FROM orders"),
                "amount_sum": round(float(scalar("SELECT COALESCE(SUM(amount), 0) FROM orders")), 2),
                "status_top": top("SELECT order_status AS name, COUNT(*) AS value FROM orders GROUP BY order_status ORDER BY value DESC"),
                "category_top": top("SELECT category AS name, COUNT(*) AS value FROM orders GROUP BY category ORDER BY value DESC LIMIT 8"),
            },
            "users": {
                "count": scalar("SELECT COUNT(*) FROM users"),
                "tier_top": top("SELECT user_tier AS name, COUNT(*) AS value FROM users GROUP BY user_tier ORDER BY value DESC"),
            },
            "aftersales": {
                "count": scalar("SELECT COUNT(*) FROM aftersales_cases"),
                "status_top": top("SELECT case_status AS name, COUNT(*) AS value FROM aftersales_cases GROUP BY case_status ORDER BY value DESC"),
                "reason_top": top("SELECT reason_code AS name, COUNT(*) AS value FROM aftersales_cases GROUP BY reason_code ORDER BY value DESC LIMIT 10"),
                "priority_top": top("SELECT priority AS name, COUNT(*) AS value FROM aftersales_cases GROUP BY priority ORDER BY value DESC"),
                "refund_sum": round(float(scalar("SELECT COALESCE(SUM(refund_amount), 0) FROM aftersales_cases")), 2),
            },
        }
