from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import row_to_dict


class AgentRunStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        *,
        user_id: str | None,
        role: str,
        workflow_name: str,
        state: dict[str, Any],
        current_node: str = "start",
        status: str = "running",
    ) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        self.conn.execute(
            """
            INSERT INTO agent_workflow_runs
            (id, user_id, role, workflow_name, status, current_node, state)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [run_id, user_id, role, workflow_name, status, current_node, json.dumps(state, ensure_ascii=False, default=str)],
        )
        self.conn.commit()
        return self.get(run_id, user_id=user_id) or {"id": run_id}

    def record_completed(
        self,
        *,
        user_id: str | None,
        role: str,
        workflow_name: str,
        state: dict[str, Any],
        result: dict[str, Any],
        current_node: str = "done",
    ) -> dict[str, Any]:
        run = self.create(
            user_id=user_id,
            role=role,
            workflow_name=workflow_name,
            state=state,
            current_node=current_node,
            status="completed",
        )
        self.conn.execute(
            """
            UPDATE agent_workflow_runs
            SET result = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [json.dumps(result, ensure_ascii=False, default=str), run["id"]],
        )
        self.conn.commit()
        return self.get(run["id"], user_id=user_id) or run

    def checkpoint(
        self,
        *,
        run_id: str,
        user_id: str | None,
        current_node: str,
        state: dict[str, Any],
        status: str = "running",
    ) -> dict[str, Any] | None:
        self.conn.execute(
            """
            UPDATE agent_workflow_runs
            SET current_node = ?, state = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND (? IS NULL OR user_id = ?)
            """,
            [current_node, json.dumps(state, ensure_ascii=False, default=str), status, run_id, user_id, user_id],
        )
        self.conn.commit()
        return self.get(run_id, user_id=user_id)

    def get(self, run_id: str, *, user_id: str | None) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM agent_workflow_runs
            WHERE id = ? AND (? IS NULL OR user_id = ?)
            """,
            [run_id, user_id, user_id],
        ).fetchone()
        return decode_run(row_to_dict(row))

    def list_for_user(self, *, user_id: str, role: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        params: list[Any] = [user_id]
        where = "user_id = ?"
        if role:
            where += " AND role = ?"
            params.append(role)
        params.append(max(1, min(limit, 100)))
        rows = self.conn.execute(
            f"""
            SELECT * FROM agent_workflow_runs
            WHERE {where}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [decode_run(row_to_dict(row)) for row in rows if row]


def decode_run(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    for field in ("state", "result"):
        raw = row.get(field)
        if isinstance(raw, str) and raw:
            try:
                row[field] = json.loads(raw)
            except json.JSONDecodeError:
                row[field] = raw
    return row
