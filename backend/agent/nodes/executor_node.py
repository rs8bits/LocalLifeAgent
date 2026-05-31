"""执行节点 - 仅确认阶段使用"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.agent.executor import execute_plan, choose_available_slot
from backend.mock_api.storage import read_json


async def executor_node(state: AgentState) -> AgentState:
    """执行预约、订位和 Mock 订单"""
    session = {
        "user_id": state.get("user_id", "user_001"),
        "intent": state.get("intent", {}),
        "plans": state.get("plans", []),
    }

    plan_id = state.get("selected_plan_id", "")
    if not plan_id and state["plans"]:
        plan_id = state["plans"][0].get("plan_id", "")

    selected = None
    for p in state["plans"]:
        if p.get("plan_id") == plan_id:
            selected = p
            break

    if not selected:
        state.setdefault("errors", []).append(f"计划 {plan_id} 不存在")
        await emit_event(state, {"event": "error", "message": f"计划 {plan_id} 不存在", "data": {}})
        return state

    # 活动预约
    activity = selected.get("activity")
    if activity and activity.get("bookable"):
        await emit_event(state, {
            "event": "booking_start",
            "message": f"正在预约活动: {activity.get('name', '')}",
            "data": {"type": "activity"},
        })
    elif activity:
        await emit_event(state, {
            "event": "booking_start",
            "message": f"活动「{activity.get('name', '')}」不支持在线预约，跳过",
            "data": {"type": "activity", "skipped": True},
        })

    # 餐厅订位
    for restaurant in _plan_restaurants(selected):
        if restaurant and restaurant.get("bookable") and restaurant.get("available"):
            await emit_event(state, {
                "event": "booking_start",
                "message": f"正在订位餐厅: {restaurant.get('name', '')}",
                "data": {"type": "restaurant"},
            })

    # 团购券订单
    deals = selected.get("deals", [])
    if deals:
        await emit_event(state, {
            "event": "order_start",
            "message": f"正在创建 Mock 订单...",
            "data": {"deals_count": len(deals)},
        })

    # 执行
    result = await execute_plan(session, plan_id)

    # booking/order done events
    for b in result.get("bookings", []):
        await emit_event(state, {
            "event": "booking_done",
            "message": b.get("message", ""),
            "data": b,
        })
    for o in result.get("orders", []):
        await emit_event(state, {
            "event": "order_done",
            "message": f"订单 {o.get('order_id', '')}",
            "data": o,
        })

    state["execution_result"] = result

    if result.get("errors"):
        for err in result["errors"]:
            state.setdefault("errors", []).append(err)

    return state


def _plan_restaurants(plan: dict) -> list[dict]:
    entries = plan.get("meal_restaurants") or []
    restaurants = [
        entry.get("restaurant") for entry in entries
        if isinstance(entry, dict) and entry.get("restaurant")
    ]
    if restaurants:
        return restaurants
    restaurant = plan.get("restaurant")
    return [restaurant] if restaurant else []
