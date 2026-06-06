"""Agent API 请求 / 响应 Schema"""

from pydantic import BaseModel, Field


class AgentPlanRequest(BaseModel):
    user_id: str = "user_001"
    message: str


class AgentReviseRequest(BaseModel):
    session_id: str
    message: str
    base_plan_id: str | None = None


class AgentPlanResponse(BaseModel):
    session_id: str
    user_id: str
    message: str
    intent: dict
    plans: list[dict]
    tool_logs: list[dict]
    errors: list[str] = Field(default_factory=list)
    input_safety_result: dict = Field(default_factory=dict)
    rewrite_result: dict = Field(default_factory=dict)
    reflection_result: dict = Field(default_factory=dict)
    guardrail_result: dict = Field(default_factory=dict)


class AgentConfirmRequest(BaseModel):
    session_id: str
    plan_id: str


class AgentConfirmResponse(BaseModel):
    status: str  # "success" | "partial_success" | "failed"
    session_id: str
    plan_id: str
    selected_plan: dict | None = None
    execution_result: dict = Field(default_factory=dict)
    bookings: list[dict] = Field(default_factory=list)
    orders: list[dict] = Field(default_factory=list)
    share_message: str | None = None
    errors: list[str] = Field(default_factory=list)
    message_guardrail_result: dict = Field(default_factory=dict)
