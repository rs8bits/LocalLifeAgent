"""Guardrails 节点 - 安全边界校验"""

from backend.agent.state import AgentState
from backend.mock_api.storage import read_json


async def guardrails_node(state: AgentState) -> AgentState:
    """校验方案的安全边界"""
    events: list[dict] = state.get("stream_events", [])
    events.append({"event": "guardrails_start", "message": "正在进行安全校验...", "data": {}})

    issues: list[str] = []
    blocked = False

    plans = state.get("plans", [])
    phase = state.get("phase", "planning")

    # 加载所有合法 ID
    valid_activity_ids = {a["id"] for a in read_json("activities.json")}
    valid_restaurant_ids = {r["id"] for r in read_json("restaurants.json")}
    valid_deal_ids = {d["id"] for d in read_json("deals.json")}
    valid_drink_ids = {d["id"] for d in read_json("drinks.json")}

    for plan in plans:
        activity = plan.get("activity") or {}
        restaurant = plan.get("restaurant") or {}
        drink = plan.get("drink") or {}
        deals = plan.get("deals", [])

        # 1. POI 来源校验
        act_id = activity.get("id", "")
        if act_id and act_id not in valid_activity_ids:
            issues.append(f"活动 ID {act_id} 不在合法数据中")
            blocked = True

        rest_id = restaurant.get("id", "")
        if rest_id and rest_id not in valid_restaurant_ids:
            issues.append(f"餐厅 ID {rest_id} 不在合法数据中")
            blocked = True

        drink_id = drink.get("id", "")
        if drink_id and drink_id not in valid_drink_ids:
            issues.append(f"饮品 ID {drink_id} 不在合法数据中")
            blocked = True

        for deal in deals:
            deal_id = deal.get("id", "")
            if deal_id and deal_id not in valid_deal_ids:
                issues.append(f"团购券 ID {deal_id} 不在合法数据中")
                blocked = True

        # 2. 规划阶段不得有 booking_id / order_id
        if phase == "planning":
            if "booking_id" in plan:
                issues.append("规划阶段方案不应包含 booking_id")
                blocked = True
            if "order_id" in plan:
                issues.append("规划阶段方案不应包含 order_id")
                blocked = True

        # 3. 儿童年龄校验
        if state.get("intent", {}).get("scene") == "family":
            child_age = state.get("intent", {}).get("child_age")
            if child_age and activity:
                age_min = activity.get("suitable_age_min", 0)
                age_max = activity.get("suitable_age_max", 99)
                if not (age_min <= child_age <= age_max):
                    issues.append(
                        f"家庭场景中活动「{activity.get('name')}」不适合{child_age}岁儿童"
                    )
                    blocked = True

    # 4. share_message 内容校验
    share_msg = state.get("share_message") or ""
    forbidden = ["真实支付成功", "已真实下单", "已真实预约", "保证有位", "保证免排队"]
    for phrase in forbidden:
        if phrase in share_msg:
            issues.append(f"share_message 包含违规内容: {phrase}")
            blocked = True

    # 5. 规划阶段不得写入 bookings/orders 已由 API 层保证，这里做声明性检查
    result = {"passed": not blocked, "issues": issues, "blocked": blocked}
    state["guardrail_result"] = result

    events.append({
        "event": "guardrails_done",
        "message": f"安全校验完成: {'通过' if not blocked else '被阻止'} ({len(issues)}个问题)",
        "data": result,
    })

    state["stream_events"] = events
    return state
