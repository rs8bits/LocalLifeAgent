"""LLM 消息生成节点"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.agent.llm_message_generator import generate_share_message_llm
from backend.agent.message_generator import generate_share_message


async def message_llm_node(state: AgentState) -> AgentState:
    """使用 LLM 生成转发消息，规则兜底"""
    is_retry = bool(state.get("guardrail_feedback", {}).get("retryable_issues"))
    event_type = "message_retry" if is_retry else "message_start"

    await emit_event(state, {
        "event": event_type,
        "message": "正在重新生成转发消息..." if is_retry else "正在生成转发消息...",
        "data": {},
    })

    execution = state.get("execution_result") or {}
    bookings = execution.get("bookings", [])
    orders = execution.get("orders", [])

    plan = {}
    plan_id = state.get("selected_plan_id", "")
    for p in state.get("plans", []):
        if p.get("plan_id") == plan_id:
            plan = p
            break
    if not plan and state.get("plans"):
        plan = state["plans"][0]

    guardrail_feedback = state.get("guardrail_feedback", {})

    result = await generate_share_message_llm(
        original_user_message=state.get("user_message", ""),
        intent=state.get("intent", {}),
        selected_plan=plan,
        execution_result=execution,
        guardrail_feedback=guardrail_feedback if guardrail_feedback.get("retryable_issues") else None,
    )

    share_msg = result.get("share_message", "")

    # 如果 LLM 失败（空消息），规则兜底
    if not share_msg:
        share_msg = generate_share_message(
            plan=plan,
            intent=state.get("intent", {}),
            bookings=bookings,
            orders=orders,
        )

    state["share_message"] = share_msg

    await emit_event(state, {
        "event": "message_done",
        "message": "转发消息已生成",
        "data": {"share_message": share_msg, "tone": result.get("tone", "general")},
    })

    return state
