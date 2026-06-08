from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    order_id: Optional[str] = None


class ToolTrace(BaseModel):
    tool_name: str
    input: dict[str, Any]
    output: Any
    status: str = "ok"
    elapsed_ms: int = 0


class ChatResponse(BaseModel):
    answer: str
    intent: str
    decision: dict[str, Any]
    order: Optional[dict[str, Any]] = None
    user_profile: Optional[dict[str, Any]] = None
    similar_cases: list[dict[str, Any]] = Field(default_factory=list)
    policy_evidence: list[dict[str, Any]] = Field(default_factory=list)
    traces: list[ToolTrace] = Field(default_factory=list)
    llm_used: bool = False


class DashboardSummary(BaseModel):
    orders: dict[str, Any]
    users: dict[str, Any]
    aftersales: dict[str, Any]
