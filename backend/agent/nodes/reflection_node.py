"""Reflection 节点 - 方案质量检查"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.agent.reflection import run_llm_reflection


async def reflection_node(state: AgentState) -> AgentState:
    """检查方案质量，生成问题和建议"""
    await emit_event(state, {"event": "reflection_start", "message": "正在检查方案质量...", "data": {}})

    intent = state.get("intent", {})
    plans = state.get("plans", [])
    weather = state.get("weather")
    tag_result = state.get("tag_resolve_result", {})
    required_domains = tag_result.get("domain_required", {})

    all_passed = True
    plan_results = []

    for plan in plans:
        issues: list[str] = []
        suggestions: list[str] = []
        retryable_issues: list[str] = []
        activities = _plan_activities(plan)
        activity = activities[0] if activities else {}
        restaurant = plan.get("restaurant") or {}
        restaurants = _plan_restaurants(plan)
        drink = plan.get("drink") or {}
        delivery_items = plan.get("delivery_items") or []

        # 1. 是否包含活动
        if required_domains.get("play") and not activity:
            issue = "方案缺少活动"
            issues.append(issue)
            retryable_issues.append(issue)
            suggestions.append("请确保至少包含一个活动")

        # 2. 是否包含餐厅
        if required_domains.get("eat") and not restaurant:
            issue = "方案缺少餐厅"
            issues.append(issue)
            retryable_issues.append(issue)
            suggestions.append("请确保至少包含一个餐厅")
        if required_domains.get("drink") and not drink:
            issue = "方案缺少饮品"
            issues.append(issue)
            retryable_issues.append(issue)
            suggestions.append("请确保包含用户明确要求的饮品/酒水")

        # 3. 时长检查
        act_dur = activity.get("recommended_duration_min", 0)
        rest_dur = restaurant.get("recommended_duration_min", 0)
        total_dur = act_dur + rest_dur
        if (activity or restaurant) and total_dur < 120:
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

        # 5. 亲子同行 → 儿童年龄
        if (intent.get("party_type") == "family_with_child" or intent.get("child_age")) and intent.get("child_age"):
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

        # 9. 路线：只有活动+餐厅组合才强制检查路线
        if activity and restaurant and not plan.get("route"):
            issues.append("未找到从活动到餐厅的路线")
            suggestions.append("建议选择同商圈的活动和餐厅")

        # 10. 不可执行环节
        if activity and not activity.get("bookable", True):
            issues.append(f"活动「{activity.get('name', '')}」不支持在线预约")
        if restaurant and not restaurant.get("available", True):
            issues.append(f"餐厅「{restaurant.get('name', '')}」当前无位")
        if required_domains.get("delivery") and not delivery_items:
            issue = "方案缺少外卖/闪送商品"
            issues.append(issue)
            retryable_issues.append(issue)
            suggestions.append("请补充可下单的配送商品")
        for item in delivery_items:
            if item.get("estimated_delivery_min", 0) > 90:
                issues.append(f"配送商品「{item.get('name', '')}」预计送达时间较长")

        for issue in _semantic_retryable_issues(plan, intent, required_domains):
            if issue not in issues:
                issues.append(issue)
            if issue not in retryable_issues:
                retryable_issues.append(issue)

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
            "retryable_issues": retryable_issues,
        })

    result = {
        "passed": all_passed,
        "plan_results": plan_results,
        "issues": [],
        "suggestions": [],
        "retryable_issues": [],
    }

    # 汇总所有问题
    for pr in plan_results:
        result["issues"].extend(pr["issues"])
        result["suggestions"].extend(pr["suggestions"])
        result["retryable_issues"].extend(pr.get("retryable_issues", []))

    llm_result, llm_error = await run_llm_reflection(state)
    if llm_result:
        _merge_llm_reflection(result, plan_results, plans, llm_result)
    elif llm_error:
        state.setdefault("tool_logs", []).append({
            "tool": "llm_reflection",
            "status": "fallback",
            "message": f"LLM Reflection 不可用，已使用规则反思: {llm_error}",
        })

    state["reflection_result"] = result

    await emit_event(state, {
        "event": "reflection_done",
        "message": f"质量检查完成: {'通过' if all_passed else '发现问题'} ({len(result['issues'])}个问题)",
        "data": result,
    })

    return state


def _semantic_retryable_issues(plan: dict, intent: dict, required_domains: dict) -> list[str]:
    issues: list[str] = []
    timeline = plan.get("timeline") or []
    timeline_refs = _timeline_refs(timeline)
    visible_refs = _visible_plan_refs(plan)

    if _requires_play(intent, required_domains):
        activities = _plan_activities(plan)
        if not activities:
            issues.append("用户明确要求活动，但方案主体缺少活动")
        elif not any(activity.get("id") in timeline_refs for activity in activities if activity.get("id")):
            issues.append("用户明确要求活动，但时间线未展示活动")

    if _requires_drink(intent, required_domains):
        drink = plan.get("drink") or {}
        if not drink:
            issues.append("用户明确要求饮品/酒水，但方案主体缺少饮品")
        elif drink.get("id") not in timeline_refs:
            issues.append("用户明确要求饮品/酒水，但时间线未展示饮品")

    if _requires_eat(intent, required_domains):
        restaurants = _plan_restaurants(plan)
        if not restaurants:
            issues.append("用户明确要求用餐，但方案主体缺少餐厅")
        elif not any(restaurant.get("id") in timeline_refs for restaurant in restaurants if restaurant.get("id")):
            issues.append("用户明确要求用餐，但时间线未展示餐厅")

    if required_domains.get("delivery"):
        delivery_items = plan.get("delivery_items") or []
        if not delivery_items:
            issues.append("用户明确要求配送，但方案主体缺少配送商品")
        elif not any(item.get("id") in timeline_refs for item in delivery_items if item.get("id")):
            issues.append("用户明确要求配送，但时间线未展示配送商品")

    hidden_action_refs = [
        ref_id for ref_id in _action_refs(plan)
        if ref_id and ref_id not in visible_refs
    ]
    if hidden_action_refs:
        issues.append(f"actions 引用了方案主体未展示的 POI: {', '.join(sorted(set(hidden_action_refs)))}")

    for ref_id in visible_refs:
        if ref_id.startswith(("act_", "drink_", "delivery_")) and ref_id not in timeline_refs:
            issues.append(f"方案主体包含 {ref_id}，但时间线未展示")

    if _requires_drink(intent, required_domains) and "dinner" in set(intent.get("meal_slots") or []):
        drink_time = _first_time(timeline, "drink")
        dinner = _last_timeline_item(timeline, "restaurant")
        if drink_time and dinner and _time_to_minutes_safe(drink_time) <= _timeline_item_end_min(dinner):
            issues.append("用户要求晚饭后饮品/酒水，但时间线中饮品没有排在晚饭后")

    return _unique(issues)


def _requires_play(intent: dict, required_domains: dict) -> bool:
    return bool(required_domains.get("play") or intent.get("activity_preferences"))


def _requires_eat(intent: dict, required_domains: dict) -> bool:
    return bool(required_domains.get("eat") or intent.get("meal_slots"))


def _requires_drink(intent: dict, required_domains: dict) -> bool:
    return bool(required_domains.get("drink") or intent.get("drink_preferences"))


def _plan_activities(plan: dict) -> list[dict]:
    activities = []
    primary = plan.get("activity")
    if primary:
        activities.append(primary)
    activities.extend(plan.get("extra_activities") or [])
    return _unique_items(activities)


def _plan_restaurants(plan: dict) -> list[dict]:
    entries = plan.get("meal_restaurants") or []
    restaurants = [
        entry.get("restaurant") for entry in entries
        if isinstance(entry, dict) and entry.get("restaurant")
    ]
    if restaurants:
        return _unique_items(restaurants)
    restaurant = plan.get("restaurant")
    return [restaurant] if restaurant else []


def _unique_items(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for item in items:
        item_id = item.get("id")
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        result.append(item)
    return result


def _timeline_refs(timeline: list[dict]) -> set[str]:
    return {
        item.get("poi_id") or item.get("ref_id")
        for item in timeline
        if item.get("poi_id") or item.get("ref_id")
    }


def _visible_plan_refs(plan: dict) -> set[str]:
    refs = set()
    for item in [*_plan_activities(plan), *_plan_restaurants(plan), plan.get("drink") or {}]:
        if item.get("id"):
            refs.add(item["id"])
    for item in plan.get("delivery_items") or []:
        if item.get("id"):
            refs.add(item["id"])
    for deal in plan.get("deals") or []:
        if deal.get("id"):
            refs.add(deal["id"])
    return refs


def _action_refs(plan: dict) -> list[str]:
    refs = []
    for action in plan.get("actions") or []:
        ref_id = action.get("ref_id")
        if ref_id:
            refs.append(ref_id)
    return refs


def _first_time(timeline: list[dict], slot_type: str) -> str | None:
    item = next((entry for entry in timeline if entry.get("type") == slot_type), None)
    return item.get("time") if item else None


def _last_timeline_item(timeline: list[dict], slot_type: str) -> dict | None:
    items = [entry for entry in timeline if entry.get("type") == slot_type and entry.get("time")]
    return max(items, key=lambda entry: entry.get("time")) if items else None


def _time_to_minutes_safe(value: str | None) -> int:
    if not value or ":" not in value:
        return -1
    try:
        hour, minute = value.split(":", 1)
        return int(hour) * 60 + int(minute)
    except ValueError:
        return -1


def _timeline_item_end_min(item: dict) -> int:
    return _time_to_minutes_safe(item.get("time")) + int(item.get("duration_min") or 0)


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _merge_llm_reflection(
    result: dict,
    plan_results: list[dict],
    plans: list[dict],
    llm_result: dict,
) -> None:
    plan_result_by_id = {item.get("plan_id"): item for item in plan_results}
    plan_by_id = {item.get("plan_id"): item for item in plans}
    for llm_plan in llm_result.get("plan_results", []):
        plan_id = llm_plan.get("plan_id")
        target = plan_result_by_id.get(plan_id)
        if not target:
            continue
        for issue in llm_plan.get("issues", []):
            if issue not in target["issues"]:
                target["issues"].append(issue)
            if _looks_retryable_semantic_issue(issue) and issue not in target.setdefault("retryable_issues", []):
                target["retryable_issues"].append(issue)
            plan = plan_by_id.get(plan_id)
            if plan is not None and issue not in plan.get("risk_tips", []):
                plan.setdefault("risk_tips", []).append(issue)
        for suggestion in llm_plan.get("suggestions", []):
            if suggestion not in target["suggestions"]:
                target["suggestions"].append(suggestion)
        target["passed"] = target["passed"] and llm_plan.get("passed", True)

    for issue in llm_result.get("issues", []):
        if issue not in result["issues"]:
            result["issues"].append(issue)
        if _looks_retryable_semantic_issue(issue) and issue not in result.setdefault("retryable_issues", []):
            result["retryable_issues"].append(issue)
    for suggestion in llm_result.get("suggestions", []):
        if suggestion not in result["suggestions"]:
            result["suggestions"].append(suggestion)
    result["passed"] = all(item["passed"] for item in plan_results) and not result["issues"]
    result["llm_reflection"] = llm_result
    result["retryable_issues"] = _unique([
        *result.get("retryable_issues", []),
        *[
            issue
            for item in plan_results
            for issue in item.get("retryable_issues", [])
        ],
    ])


def _looks_retryable_semantic_issue(issue: str) -> bool:
    keywords = [
        "明确要求", "缺少", "未展示", "未列出", "未覆盖",
        "timeline", "时间线", "actions", "饭后", "顺序错误",
    ]
    return any(keyword in issue for keyword in keywords)
