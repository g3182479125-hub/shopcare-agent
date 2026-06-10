from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from app.config import Settings, get_settings
from app.db import row_to_dict

READ_ONLY_CYPHER_PREFIXES = ("match", "with", "return", "call db.", "call apoc.meta")
BLOCKED_CYPHER_WORDS = {"create", "merge", "delete", "detach", "set", "remove", "drop", "load csv"}


class GraphRAGService:
    def __init__(self, settings: Settings | None = None, conn: sqlite3.Connection | None = None) -> None:
        self.settings = settings or get_settings()
        self.conn = conn

    def status(self) -> dict[str, Any]:
        neo4j_configured = bool(self.settings.neo4j_uri and self.settings.neo4j_password)
        driver_available = self._neo4j_driver_available()
        backend = "neo4j" if self.settings.graph_rag_enabled and neo4j_configured and driver_available else "local"
        return {
            "enabled": self.settings.graph_rag_enabled,
            "backend": backend,
            "neo4j_configured": neo4j_configured,
            "neo4j_driver_available": driver_available,
            "database": self.settings.neo4j_database if neo4j_configured else None,
        }

    def query(self, *, question: str, role: str = "merchant", limit: int = 8) -> dict[str, Any]:
        started = time.perf_counter()
        if not self.settings.graph_rag_enabled:
            return self._empty(question, "disabled", started)
        cypher = text_to_cypher(question, role=role, limit=limit)
        if not is_read_only_cypher(cypher):
            return self._empty(question, "blocked_cypher", started, cypher=cypher)
        if self.status()["backend"] == "neo4j":
            result = self._query_neo4j(cypher)
        else:
            result = self._query_local(question=question, role=role, limit=limit)
        result.update({
            "question": question,
            "cypher": cypher,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        })
        return result

    def _query_neo4j(self, cypher: str) -> dict[str, Any]:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except Exception as exc:
            return {"backend": "neo4j", "status": "driver_missing", "items": [], "error": str(exc)}
        try:
            driver = GraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            with driver.session(database=self.settings.neo4j_database) as session:
                rows = session.run(cypher, timeout=self.settings.graph_query_timeout_seconds)
                items = [dict(record) for record in rows]
            driver.close()
            return {"backend": "neo4j", "status": "ok", "items": items}
        except Exception as exc:
            return {"backend": "neo4j", "status": "error", "items": [], "error": str(exc)}

    def _query_local(self, *, question: str, role: str, limit: int) -> dict[str, Any]:
        focus = detect_graph_focus(question)
        if self.conn is None:
            return {"backend": "local", "status": "no_connection", "focus": focus, "items": []}
        if focus == "category":
            items = self._local_category(limit)
        elif focus == "brand":
            items = self._local_brand(limit)
        elif focus == "city":
            items = self._local_city(limit)
        elif focus == "aftersales":
            items = self._local_aftersales(limit)
        elif focus == "users":
            items = self._local_users(limit)
        else:
            items = self._local_overview(limit)
        return {"backend": "local", "status": "ok", "focus": focus, "items": items, "summary": summarize_graph_items(focus, items)}

    def _local_category(self, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT category, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv, ROUND(AVG(amount), 2) AS avg_order_value
            FROM orders
            GROUP BY category
            ORDER BY gmv DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def _local_brand(self, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT brand, category, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv
            FROM orders
            GROUP BY brand, category
            ORDER BY gmv DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def _local_city(self, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT shipping_city, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv, ROUND(AVG(fulfillment_time), 2) AS avg_fulfillment_hours
            FROM orders
            GROUP BY shipping_city
            ORDER BY gmv DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def _local_aftersales(self, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT reason_code, category, COUNT(*) AS cases, ROUND(AVG(refund_amount), 2) AS avg_refund, ROUND(AVG(satisfaction_score), 2) AS satisfaction
            FROM aftersales_cases
            GROUP BY reason_code, category
            ORDER BY cases DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def _local_users(self, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT user_tier, register_channel, COUNT(*) AS users, ROUND(AVG(total_purchase_amount), 2) AS avg_ltv
            FROM users
            GROUP BY user_tier, register_channel
            ORDER BY users DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def _local_overview(self, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT 'orders' AS node, COUNT(*) AS count, ROUND(SUM(amount), 2) AS gmv FROM orders
            UNION ALL
            SELECT 'users' AS node, COUNT(*) AS count, ROUND(SUM(total_purchase_amount), 2) AS gmv FROM users
            UNION ALL
            SELECT 'aftersales_cases' AS node, COUNT(*) AS count, ROUND(SUM(refund_amount), 2) AS gmv FROM aftersales_cases
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def _neo4j_driver_available(self) -> bool:
        try:
            import neo4j  # type: ignore  # noqa: F401

            return True
        except Exception:
            return False

    def _empty(self, question: str, status: str, started: float, *, cypher: str | None = None) -> dict[str, Any]:
        return {
            "question": question,
            "backend": self.status().get("backend", "local"),
            "status": status,
            "items": [],
            "cypher": cypher,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }


def text_to_cypher(question: str, *, role: str = "merchant", limit: int = 8) -> str:
    focus = detect_graph_focus(question)
    clean_limit = max(1, min(limit, 20))
    if focus == "category":
        return f"MATCH (c:Category)<-[:IN_CATEGORY]-(o:Order) RETURN c.name AS category, count(o) AS orders, sum(o.amount) AS gmv ORDER BY gmv DESC LIMIT {clean_limit}"
    if focus == "brand":
        return f"MATCH (b:Brand)<-[:MADE_BY]-(p:Product)<-[:CONTAINS]-(o:Order) RETURN b.name AS brand, count(o) AS orders, sum(o.amount) AS gmv ORDER BY gmv DESC LIMIT {clean_limit}"
    if focus == "city":
        return f"MATCH (city:City)<-[:SHIPPED_TO]-(o:Order) RETURN city.name AS city, count(o) AS orders, avg(o.fulfillment_time) AS avg_fulfillment_hours ORDER BY orders DESC LIMIT {clean_limit}"
    if focus == "aftersales":
        return f"MATCH (case:AfterSalesCase)-[:FOR_ORDER]->(o:Order) RETURN case.reason_code AS reason, count(case) AS cases, avg(case.refund_amount) AS avg_refund ORDER BY cases DESC LIMIT {clean_limit}"
    if focus == "users":
        return f"MATCH (u:User)-[:PLACED]->(o:Order) RETURN u.user_tier AS tier, count(DISTINCT u) AS users, avg(u.total_purchase_amount) AS avg_ltv ORDER BY users DESC LIMIT {clean_limit}"
    return f"MATCH (n) RETURN labels(n) AS labels, count(n) AS count LIMIT {clean_limit}"


def detect_graph_focus(question: str) -> str:
    text = (question or "").lower()
    if any(word in text for word in ["category", "??", "??", "??"]):
        return "category"
    if any(word in text for word in ["brand", "??", "??", "apple", "??"]):
        return "brand"
    if any(word in text for word in ["city", "??", "??", "??", "??"]):
        return "city"
    if any(word in text for word in ["after", "??", "??", "??", "??", "??", "??"]):
        return "aftersales"
    if any(word in text for word in ["user", "??", "??", "??", "??"]):
        return "users"
    return "overview"


def is_read_only_cypher(cypher: str) -> bool:
    clean = re.sub(r"\s+", " ", (cypher or "").strip().lower())
    if not clean:
        return False
    if any(re.search(rf"\b{re.escape(word)}\b", clean) for word in BLOCKED_CYPHER_WORDS):
        return False
    return clean.startswith(READ_ONLY_CYPHER_PREFIXES)


def summarize_graph_items(focus: str, items: list[dict[str, Any]]) -> str:
    if not items:
        return "No graph facts found."
    first = items[0]
    if focus == "category":
        return f"Top category is {first.get('category')} with GMV {first.get('gmv')}."
    if focus == "brand":
        return f"Top brand is {first.get('brand')} with GMV {first.get('gmv')}."
    if focus == "city":
        return f"Top city is {first.get('shipping_city')} with GMV {first.get('gmv')}."
    if focus == "aftersales":
        return f"Top aftersales reason is {first.get('reason_code')} with {first.get('cases')} cases."
    if focus == "users":
        return f"Largest user segment is {first.get('user_tier')} from {first.get('register_channel')}."
    return "Graph overview is available."
