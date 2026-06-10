from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from app.db import row_to_dict
from app.security import hash_password, verify_password


VALID_ROLES = {"user", "merchant"}


class AccountService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_user(self, *, email: str, password: str, username: str, role: str) -> dict[str, Any]:
        role = normalize_role(role)
        clean_email = email.strip().lower()
        if not clean_email or "@" not in clean_email:
            raise ValueError("请输入有效邮箱")
        if len(password) < 6:
            raise ValueError("密码至少 6 位")
        user = {
            "id": uuid.uuid4().hex,
            "email": clean_email,
            "username": username.strip() or clean_email.split("@")[0],
            "role": role,
            "password_hash": hash_password(password),
        }
        try:
            self.conn.execute(
                "INSERT INTO app_users (id, email, username, role, password_hash) VALUES (?, ?, ?, ?, ?)",
                [user["id"], user["email"], user["username"], user["role"], user["password_hash"]],
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("这个邮箱已经注册过了") from exc
        return public_user(user)

    def authenticate(self, *, email: str, password: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM app_users WHERE email = ?", [email.strip().lower()]).fetchone()
        user = row_to_dict(row)
        if not user or not verify_password(password, str(user.get("password_hash", ""))):
            return None
        self.conn.execute("UPDATE app_users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", [user["id"]])
        self.conn.commit()
        return public_user(user)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM app_users WHERE id = ?", [user_id]).fetchone()
        user = row_to_dict(row)
        return public_user(user) if user else None

    def ensure_demo_user(self, role: str) -> tuple[dict[str, Any], str]:
        role = normalize_role(role)
        email = "customer@shopcare.demo" if role == "user" else "merchant@shopcare.demo"
        password = "shopcare123"
        user = self.authenticate(email=email, password=password)
        if user:
            return user, password
        username = "售后体验用户" if role == "user" else "商家分析用户"
        return self.create_user(email=email, password=password, username=username, role=role), password


def normalize_role(role: str) -> str:
    clean = (role or "user").strip().lower()
    if clean not in VALID_ROLES:
        raise ValueError("role must be user or merchant")
    return clean


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "username": user["username"],
        "role": user["role"],
        "created_at": user.get("created_at"),
        "last_login": user.get("last_login"),
    }
