from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ConversationItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    order_id: Optional[str] = None
    session_id: Optional[str] = None
    conversation_history: list[ConversationItem] = Field(default_factory=list)


class MerchantChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    conversation_history: list[ConversationItem] = Field(default_factory=list)


class MerchantChatResponse(BaseModel):
    answer: str
    focus: str
    chart_directive: dict[str, Any]
    image_analysis: Optional[dict[str, Any]] = None
    llm_used: bool = False
    llm_provider: Optional[str] = None
    context_used: dict[str, Any] = Field(default_factory=dict)


class ToolTrace(BaseModel):
    tool_name: str
    input: Any
    output: Any
    status: str = "ok"
    elapsed_ms: int = 0
    label: Optional[str] = None
    summary: Optional[str] = None


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
    llm_provider: Optional[str] = None
    image_analysis: Optional[dict[str, Any]] = None


class DashboardSummary(BaseModel):
    orders: dict[str, Any]
    users: dict[str, Any]
    aftersales: dict[str, Any]
