"""用户记忆节点"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.agent.planner import _load_user_memory


async def memory_node(state: AgentState) -> AgentState:
    """读取用户长期记忆"""
    user_id = state.get("user_id", "user_001")
    memory = _load_user_memory(user_id)
    state["user_profile"] = memory.get("preferences", {}) if memory else {}

    prefs = state["user_profile"]
    info_parts = []
    if prefs.get("home_location"):
        info_parts.append(f"位置: {prefs['home_location']}")
    if prefs.get("child_age"):
        info_parts.append(f"孩子: {prefs['child_age']}岁")
    if prefs.get("max_distance_km"):
        info_parts.append(f"最远: {prefs['max_distance_km']}km")

    await emit_event(state, {
        "event": "memory_loaded",
        "message": "已读取用户偏好: " + (", ".join(info_parts) if info_parts else "无历史偏好"),
        "data": {"user_profile": state["user_profile"]},
    })

    return state
