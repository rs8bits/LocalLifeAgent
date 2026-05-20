"""转发消息生成器 - 纯规则，不调用 LLM"""


def generate_share_message(plan: dict, intent: dict, bookings: list[dict], orders: list[dict]) -> str:
    """根据方案和执行结果生成可转发消息"""
    scene = intent.get("scene", "general")
    activity = plan.get("activity") or {}
    restaurant = plan.get("restaurant") or {}
    timeline = plan.get("timeline", [])

    parts = []

    if scene == "family":
        act_name = activity.get("name", "某活动")
        rest_name = restaurant.get("name", "某餐厅")
        act_time = ""
        rest_time = ""
        for t in timeline:
            if t.get("type") == "activity":
                act_time = t.get("time", "")
            elif t.get("type") == "restaurant":
                rest_time = t.get("time", "")

        parts.append("下午安排好了：")
        if act_time:
            parts.append(f"{act_time} 去{act_name}，")
        else:
            parts.append(f"先去{act_name}，")
        if rest_time:
            parts.append(f"之后去{rest_name}吃饭。")
        else:
            parts.append(f"之后去{rest_name}吃饭。")

        if activity.get("child_friendly"):
            parts.append("孩子能玩，")
        if restaurant.get("low_calorie_options"):
            parts.append("餐厅也比较清淡健康。")
        else:
            parts.append("整体离家不远。")

    elif scene == "friends":
        act_name = activity.get("name", "某活动")
        rest_name = restaurant.get("name", "某餐厅")
        parts.append(f"下午行程定了：先去{act_name}玩，再去{rest_name}吃饭。")
        tags = set((activity.get("tags") or []) + (restaurant.get("tags") or []))
        if "拍照" in tags:
            parts.append("路线顺，适合聊天拍照，")
        else:
            parts.append("路线顺，适合聚会，")

    else:
        act_name = activity.get("name", "")
        rest_name = restaurant.get("name", "")
        if act_name and rest_name:
            parts.append(f"安排了：{act_name} + {rest_name}。")
        elif act_name:
            parts.append(f"安排了：{act_name}。")
        elif rest_name:
            parts.append(f"安排了：{rest_name}。")

    # 预约结果
    success_bookings = [b for b in bookings if b.get("success") or b.get("skipped")]
    failed_bookings = [b for b in bookings if not b.get("success", True) and not b.get("skipped")]

    if orders:
        parts.append(f"团购券 Mock 订单已创建（非真实支付）。")
    if failed_bookings:
        failed_names = [b.get("poi_name", "") for b in failed_bookings]
        parts.append(f"注意：{', '.join(failed_names)}预约/订位未成功，可能需要手动处理。")

    parts.append("出发前看一下时间就行。")
    return "".join(parts)
