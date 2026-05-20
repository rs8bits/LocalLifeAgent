"""转发消息生成器 - 纯规则，不调用 LLM"""


def generate_share_message(plan: dict, intent: dict, bookings: list[dict], orders: list[dict]) -> str:
    """根据方案和执行结果生成可转发消息"""
    scene = intent.get("scene", "general")
    timeline = plan.get("timeline", [])
    drink = plan.get("drink") or {}

    parts = []

    if scene == "family":
        parts.append("下午安排好了：")
    elif scene == "friends":
        parts.append("行程定了：")
    else:
        parts.append("安排好了：")

    # 按时间线顺序描述
    time_parts = []
    for item in timeline:
        if item.get("type") == "transit":
            continue
        t = item.get("time", "")
        name = item.get("title", "")
        slot_type = item.get("type", "")
        if slot_type == "activity":
            time_parts.append(f"{t} 去{name}")
        elif slot_type == "drink":
            time_parts.append(f"{t} 喝{name}")
        elif slot_type == "restaurant":
            time_parts.append(f"{t} 去{name}吃饭")
        elif slot_type == "delivery":
            time_parts.append(f"{t} 安排{name}")

    if time_parts:
        parts.append("，然后".join(time_parts) + "。")
    else:
        # fallback
        activity = plan.get("activity") or {}
        restaurant = plan.get("restaurant") or {}
        if activity.get("name"):
            parts.append(f"先去{activity['name']}")
        if drink.get("name"):
            parts.append(f"，喝杯{drink['name']}")
        if restaurant.get("name"):
            parts.append(f"，再去{restaurant['name']}吃饭")
        parts.append("。")

    if scene == "family":
        activity = plan.get("activity") or {}
        restaurant = plan.get("restaurant") or {}
        if activity.get("child_friendly"):
            parts.append("孩子能玩，")
        if restaurant.get("low_calorie_options"):
            parts.append("餐厅也比较清淡健康。")
        else:
            parts.append("整体离家不远。")

    elif scene == "friends":
        all_tags = set()
        for item in timeline:
            poi = None
            pid = item.get("poi_id", "")
            if pid.startswith("act_"):
                poi = plan.get("activity") or {}
            elif pid.startswith("rest_"):
                poi = plan.get("restaurant") or {}
            elif pid.startswith("drink_"):
                poi = plan.get("drink") or {}
            if poi:
                all_tags.update(poi.get("tags", []))
        if "拍照" in all_tags:
            parts.append("路线顺，适合聊天拍照，")
        else:
            parts.append("路线顺，适合聚会，")

    # 预约结果
    failed_bookings = [b for b in bookings if not b.get("success", True) and not b.get("skipped")]
    if orders:
        has_delivery = any(o.get("order_type") == "delivery" for o in orders)
        has_deal = any(o.get("order_type", "deal") == "deal" for o in orders)
        if has_deal:
            parts.append("团购券 Mock 订单已创建（非真实支付）。")
        if has_delivery:
            parts.append("外卖/闪送 Mock 订单已创建（非真实支付/配送）。")
    if failed_bookings:
        failed_names = [b.get("poi_name", "") for b in failed_bookings]
        parts.append(f"注意：{', '.join(failed_names)}预约/订位未成功，可能需要手动处理。")

    parts.append("出发前看一下时间就行。")
    return "".join(parts)
