"""消息生成节点"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.agent.message_generator import generate_share_message


async def message_node(state: AgentState) -> AgentState:
    """生成转发消息"""
    execution = state.get("execution_result") or {}
    bookings = execution.get("bookings", [])
    orders = execution.get("orders", [])

    plan = {}
    plan_id = state.get("selected_plan_id", "")
    for p in state.get("plans", []):
        if p.get("plan_id") == plan_id:
            plan = p
            break
    if not plan and state["plans"]:
        plan = state["plans"][0]

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
        "data": {"share_message": share_msg},
    })

    return state
