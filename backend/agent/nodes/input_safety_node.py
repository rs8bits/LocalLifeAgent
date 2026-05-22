"""Input Safety 节点"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.agent.input_safety import check_input_safety


async def input_safety_node(state: AgentState) -> AgentState:
    """检查用户输入安全性，必要时阻止后续规划"""
    await emit_event(state, {
        "event": "input_safety_start",
        "message": "正在进行输入安全检查...",
        "data": {},
    })

    message = state.get("user_message", "")
    result = await check_input_safety(message)
    state["input_safety_result"] = result

    if result.get("blocked"):
        state.setdefault("errors", []).append(result.get("safe_message", "输入包含不当内容"))
        await emit_event(state, {
            "event": "input_safety_blocked",
            "message": result.get("safe_message", "输入被拦截"),
            "data": result,
        })
    else:
        await emit_event(state, {
            "event": "input_safety_done",
            "message": "输入安全检查通过",
            "data": result,
        })

    return state
