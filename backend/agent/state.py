"""统一 AgentState"""

from typing import TypedDict, Any

DEFAULT_MAX_RETRIES = 2


class AgentState(TypedDict, total=False):
    session_id: str | None
    user_id: str
    user_message: str

    intent: dict[str, Any]
    user_profile: dict[str, Any]

    candidate_activities: list[dict[str, Any]]
    candidate_restaurants: list[dict[str, Any]]
    candidate_drinks: list[dict[str, Any]]
    candidate_delivery_items: list[dict[str, Any]]
    candidate_routes: list[dict[str, Any]]
    candidate_deals: list[dict[str, Any]]
    weather: dict[str, Any] | None

    plans: list[dict[str, Any]]
    selected_plan_id: str | None

    tag_resolve_result: dict[str, Any]
    tool_logs: list[dict[str, Any]]
    reflection_result: dict[str, Any]
    guardrail_result: dict[str, Any]

    execution_result: dict[str, Any] | None
    share_message: str | None
    errors: list[str]
    stream_events: list[dict[str, Any]]
    event_queue: Any
    phase: str  # "planning" | "execution"

    # P0: Input Safety
    input_safety_result: dict[str, Any]

    # P1: Rewrite
    rewrite_result: dict[str, Any]

    # P3: Guardrails Retry
    guardrail_feedback: dict[str, Any]
    planner_retry_count: int
    message_retry_count: int
    max_retries: int
