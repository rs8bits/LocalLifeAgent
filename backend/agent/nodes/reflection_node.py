"""Reflection 节点 - 方案质量检查"""

from backend.agent.state import AgentState


async def reflection_node(state: AgentState) -> AgentState:
    """检查方案质量，生成问题和建议"""
    events: list[dict] = state.get("stream_events", [])
    events.append({"event": "reflection_start", "message": "正在检查方案质量...", "data": {}})

    intent = state.get("intent", {})
    plans = state.get("plans", [])
    weather = state.get("weather")

    all_passed = True
    plan_results = []

    for plan in plans:
        issues: list[str] = []
        suggestions: list[str] = []
        activity = plan.get("activity") or {}
        restaurant = plan.get("restaurant") or {}

        # 1. 是否包含活动
        if not activity:
            issues.append("方案缺少活动")
            suggestions.append("请确保至少包含一个活动")

        # 2. 是否包含餐厅
        if not restaurant:
            issues.append("方案缺少餐厅")
            suggestions.append("请确保至少包含一个餐厅")

        # 3. 时长检查
        act_dur = activity.get("recommended_duration_min", 0)
        rest_dur = restaurant.get("recommended_duration_min", 0)
        total_dur = act_dur + rest_dur
        if total_dur < 120:
            issues.append(f"总时长{total_dur}分钟偏短")
            suggestions.append("建议增加活动或延长停留时间")
        elif total_dur > 480:
            issues.append(f"总时长{total_dur}分钟偏长")
            suggestions.append("建议缩短活动时间或减少项目")

        # 4. 距离检查
        radius = intent.get("radius_km", 5)
        act_dist = activity.get("distance_km", 0)
        rest_dist = restaurant.get("distance_km", 0)
        if act_dist > radius * 1.5:
            issues.append(f"活动距离{act_dist}km超出用户偏好{radius}km")
            suggestions.append("建议选择更近的活动")
        if rest_dist > radius * 1.5:
            issues.append(f"餐厅距离{rest_dist}km超出用户偏好{radius}km")
            suggestions.append("建议选择更近的餐厅")

        # 5. 家庭场景 → 儿童年龄
        if intent.get("scene") == "family" and intent.get("child_age"):
            child_age = intent["child_age"]
            age_min = activity.get("suitable_age_min", 0)
            age_max = activity.get("suitable_age_max", 99)
            if not (age_min <= child_age <= age_max):
                issues.append(f"活动不适合{child_age}岁儿童（适合{age_min}-{age_max}岁）")
                suggestions.append("建议更换为适合儿童的活动")

        # 6. 减脂/低卡
        if intent.get("needs_low_calorie"):
            if restaurant and not restaurant.get("low_calorie_options"):
                tags = restaurant.get("tags", [])
                if not any(t in tags for t in ["健康", "轻食", "低卡", "减脂"]):
                    issues.append("餐厅可能不满足减脂/低卡需求")
                    suggestions.append("建议选择标注健康/轻食的餐厅")

        # 7. 排队
        act_queue = activity.get("queue_minutes", 0)
        rest_queue = restaurant.get("queue_minutes", 0)
        avoid = intent.get("avoid_queue_minutes", 30)
        if act_queue > avoid * 2:
            issues.append(f"活动排队{act_queue}分钟过长（容忍上限{avoid}分钟）")
            suggestions.append("建议错峰或选择排队较短的活动")
        if rest_queue > avoid * 2:
            issues.append(f"餐厅排队{rest_queue}分钟过长（容忍上限{avoid}分钟）")
            suggestions.append("建议提前取号或选择排队较短的餐厅")

        # 8. 雨天 → 室内
        if weather and not weather.get("outdoor_suitable", True):
            if activity and not activity.get("indoor", True):
                issues.append("天气不佳，活动在户外")
                suggestions.append("建议改为室内活动")

        # 9. 路线
        if not plan.get("route"):
            issues.append("未找到从活动到餐厅的路线")
            suggestions.append("建议选择同商圈的活动和餐厅")

        # 10. 不可执行环节
        if activity and not activity.get("bookable", True):
            issues.append(f"活动「{activity.get('name', '')}」不支持在线预约")
        if restaurant and not restaurant.get("available", True):
            issues.append(f"餐厅「{restaurant.get('name', '')}」当前无位")

        passed = len(issues) == 0
        if not passed:
            all_passed = False
            # 将 issues 转为风险提示
            for issue in issues:
                if issue not in plan.get("risk_tips", []):
                    plan.setdefault("risk_tips", []).append(issue)

        plan_results.append({
            "plan_id": plan.get("plan_id", ""),
            "passed": passed,
            "issues": issues,
            "suggestions": suggestions,
        })

    result = {
        "passed": all_passed,
        "plan_results": plan_results,
        "issues": [],
        "suggestions": [],
    }

    # 汇总所有问题
    for pr in plan_results:
        result["issues"].extend(pr["issues"])
        result["suggestions"].extend(pr["suggestions"])

    state["reflection_result"] = result

    events.append({
        "event": "reflection_done",
        "message": f"质量检查完成: {'通过' if all_passed else '发现问题'} ({len(result['issues'])}个问题)",
        "data": result,
    })

    state["stream_events"] = events
    return state
