"""Rewrite 节点"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.agent.rewrite import rewrite_message


async def rewrite_node(state: AgentState) -> AgentState:
    """Rewrite 用户消息，结合用户记忆整理为清晰的规划上下文"""
    await emit_event(state, {
        "event": "rewrite_start",
        "message": "正在整理上下文...",
        "data": {},
    })

    safety = state.get("input_safety_result", {})
    if not safety.get("passed", True):
        state["rewrite_result"] = {}
        return state

    message = state.get("user_message", "")
    user_profile = state.get("user_profile", {})

    result = await rewrite_message(message, user_profile)
    state["rewrite_result"] = result

    await emit_event(state, {
        "event": "rewrite_done",
        "message": "上下文整理完成",
        "data": result,
    })

    return state
