from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import row_to_dict


class ConversationStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, *, user_id: str, role: str, title: str | None = None) -> dict[str, Any]:
        conversation = {
            "id": uuid.uuid4().hex,
            "user_id": user_id,
            "role": role,
            "title": (title or "新的售后会话" if role == "user" else title or "新的经营分析").strip()[:80],
        }
        self.conn.execute(
            "INSERT INTO app_conversations (id, user_id, role, title) VALUES (?, ?, ?, ?)",
            [conversation["id"], conversation["user_id"], conversation["role"], conversation["title"]],
        )
        self.conn.commit()
        return self.get(conversation["id"], user_id=user_id) or conversation

    def list_for_user(self, *, user_id: str, role: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [user_id]
        where = "user_id = ? AND status = 'active'"
        if role:
            where += " AND role = ?"
            params.append(role)
        rows = self.conn.execute(
            f"SELECT * FROM app_conversations WHERE {where} ORDER BY updated_at DESC LIMIT 50",
            params,
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def get(self, conversation_id: str, *, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM app_conversations WHERE id = ? AND user_id = ? AND status = 'active'",
            [conversation_id, user_id],
        ).fetchone()
        return row_to_dict(row)

    def update_title(self, conversation_id: str, *, user_id: str, title: str) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE app_conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            [title.strip()[:80] or "未命名会话", conversation_id, user_id],
        )
        self.conn.commit()
        return self.get(conversation_id, user_id=user_id)

    def delete(self, conversation_id: str, *, user_id: str) -> bool:
        cur = self.conn.execute(
            "UPDATE app_conversations SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            [conversation_id, user_id],
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_messages(self, conversation_id: str, *, user_id: str, limit: int = 80) -> list[dict[str, Any]]:
        if not self.get(conversation_id, user_id=user_id):
            return []
        rows = self.conn.execute(
            """
            SELECT id, conversation_id, sender, content, payload, created_at
            FROM app_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            [conversation_id, limit],
        ).fetchall()
        return [normalize_message(row_to_dict(row)) for row in rows]

    def append_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        sender: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        conversation = self.get(conversation_id, user_id=user_id)
        if not conversation:
            return None
        message_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO app_messages (id, conversation_id, sender, content, payload) VALUES (?, ?, ?, ?, ?)",
            [message_id, conversation_id, sender, content, json.dumps(payload or {}, ensure_ascii=False)],
        )
        title = conversation.get("title") or ""
        if title.startswith("新的") and sender == "user" and content.strip():
            self.conn.execute(
                "UPDATE app_conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [content.strip()[:28], conversation_id],
            )
        else:
            self.conn.execute("UPDATE app_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", [conversation_id])
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM app_messages WHERE id = ?", [message_id]).fetchone()
        return normalize_message(row_to_dict(row))


def normalize_message(message: dict[str, Any] | None) -> dict[str, Any]:
    if not message:
        return {}
    try:
        payload = json.loads(message.get("payload") or "{}")
    except json.JSONDecodeError:
        payload = {}
    message["payload"] = payload
    return message
