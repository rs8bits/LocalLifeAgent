"""Planner - 基于 Intent 和 Tool 结果生成候选方案"""

from typing import Any, Optional

from backend.agent.schemas import Intent, PlannerOutput
from backend.agent.intent_parser import parse_intent
from backend.agent.scorer import score_plan
from backend.tools.registry import get_tool
from backend.mock_api.storage import read_json


async def plan_for_message(
    user_id: str,
    message: str,
) -> dict[str, Any]:
    """给定用户 ID 和自然语言消息，返回规划结果（方案列表 + 工具日志 + 错误）"""
    tool_logs: list[dict[str, Any]] = []
    errors: list[str] = []

    # 1. 读取用户记忆
    user_memory = _load_user_memory(user_id)

    # 2. 解析意图
    intent: Intent = await parse_intent(message, user_memory)
    intent_dict = intent.model_dump()

    # 3. 查询天气
    weather_result = await _run_tool(
        "get_weather",
        tool_logs,
        date=_resolve_mock_weather_date(intent.date),
        location="朝阳区",
    )

    # 4. 查询活动
    activities_result = await _run_tool(
        "search_activities",
        tool_logs,
        scene=intent.scene,
        radius_km=intent.radius_km,
        child_age=intent.child_age,
        indoor=_indoor_preference(weather_result, intent),
        tag=_first(intent.activity_preferences),
    )
    activities = activities_result.data if activities_result and activities_result.status == "ok" else []

    # 5. 查询餐厅
    restaurants_result = await _run_tool(
        "search_restaurants",
        tool_logs,
        scene=intent.scene,
        radius_km=intent.radius_km,
        party_size=intent.people_count,
        tag=_first(intent.food_preferences) if intent.food_preferences else None,
        available=True,
        max_queue_minutes=intent.avoid_queue_minutes * 2,  # 放宽一些
    )
    restaurants = restaurants_result.data if restaurants_result and restaurants_result.status == "ok" else []

    # 如果健康需求的餐厅不够，放宽条件再查
    if intent.needs_low_calorie and len(restaurants) < 2:
        fallback = await _run_tool(
            "search_restaurants",
            tool_logs,
            scene=intent.scene,
            radius_km=intent.radius_km,
            party_size=intent.people_count,
            available=True,
        )
        if fallback and fallback.status == "ok":
            restaurants = _dedupe_by_id(restaurants, fallback.data)

    # 6. 确保有足够数据
    if not activities:
        errors.append("未找到符合条件的活动")

    if not restaurants:
        errors.append("未找到符合条件的餐厅")

    # 7. 组合候选方案
    plans = _build_plans(intent, activities, restaurants, tool_logs)

    # 8. 为每个方案查询路线和团购券
    for plan in plans:
        await _enrich_plan(plan, tool_logs)

    # 9. 评分
    for plan in plans:
        score_plan(plan, intent)

    # 10. 按分数排序
    plans.sort(key=lambda p: p.get("score", 0), reverse=True)

    return PlannerOutput(
        intent=intent_dict,
        plans=plans[:3],
        tool_logs=tool_logs,
        errors=errors,
    ).model_dump()


def _load_user_memory(user_id: str) -> Optional[dict]:
    """加载用户记忆"""
    try:
        memories = read_json("user_memory.json")
        for m in memories:
            if m.get("user_id") == user_id:
                return m
    except Exception:
        pass
    return None


def _resolve_mock_weather_date(date_text: str) -> str:
    """将 today/tomorrow 映射到 Mock 天气数据里的具体日期"""
    if date_text not in {"today", "tomorrow"}:
        return date_text

    try:
        dates = sorted({item.get("date") for item in read_json("weather.json") if item.get("date")})
    except Exception:
        return date_text

    if not dates:
        return date_text
    if date_text == "today" or len(dates) == 1:
        return dates[0]
    return dates[1]


async def _run_tool(
    name: str, tool_logs: list[dict], **kwargs
) -> Any:
    """执行工具并记录日志"""
    tool = get_tool(name)
    if not tool:
        tool_logs.append({"tool": name, "status": "error", "message": f"工具 {name} 未注册"})
        return None
    # 过滤 None 参数
    filtered = {k: v for k, v in kwargs.items() if v is not None}
    result = await tool.run(**filtered)
    tool_logs.append({
        "tool": result.tool,
        "status": result.status,
        "message": result.message,
    })
    return result


def _indoor_preference(weather_result: Any, intent: Intent) -> Optional[bool]:
    """根据天气判断是否优先室内"""
    if not weather_result or weather_result.status != "ok":
        return None
    data = weather_result.data
    if not data:
        return None
    w = data[0]
    if not w.get("outdoor_suitable", True):
        return True  # 天气不好，优先室内
    return None


def _first(lst: list[str]) -> Optional[str]:
    return lst[0] if lst else None


def _dedupe_by_id(existing: list[dict], new_items: list[dict]) -> list[dict]:
    """按 id 去重合并"""
    seen = {item.get("id") for item in existing}
    return existing + [item for item in new_items if item.get("id") not in seen]


def _build_plans(
    intent: Intent,
    activities: list[dict],
    restaurants: list[dict],
    tool_logs: list[dict],
) -> list[dict]:
    """组合活动和餐厅生成候选方案"""
    plans: list[dict] = []

    if intent.scene == "family":
        plans = _build_family_plans(intent, activities, restaurants)
    else:
        plans = _build_friends_plans(intent, activities, restaurants)

    # 如果没有餐厅，生成仅活动方案
    if not plans and activities:
        for i, act in enumerate(activities[:2]):
            plans.append(_make_plan(i, intent.scene, act, None))

    return plans


def _build_family_plans(
    intent: Intent, activities: list[dict], restaurants: list[dict]
) -> list[dict]:
    """家庭场景方案生成"""
    plans: list[dict] = []

    # 优先级排序：亲子友好 + 儿童年龄适配
    def family_act_key(a: dict) -> float:
        score = 0.0
        if a.get("child_friendly"):
            score += 2.0
        if intent.child_age and a.get("suitable_age_min", 0) <= intent.child_age <= a.get("suitable_age_max", 99):
            score += 1.0
        score -= a.get("distance_km", 0) * 0.1
        score -= a.get("queue_minutes", 0) * 0.01
        return score

    def family_rest_key(r: dict) -> float:
        score = 0.0
        if r.get("child_friendly"):
            score += 2.0
        if intent.needs_low_calorie:
            if r.get("low_calorie_options"):
                score += 2.0
            tags = r.get("tags", [])
            if any(t in tags for t in ["健康", "轻食", "低卡", "减脂"]):
                score += 1.0
        score -= r.get("distance_km", 0) * 0.1
        score -= r.get("queue_minutes", 0) * 0.01
        return score

    sorted_acts = sorted(activities, key=family_act_key, reverse=True)
    sorted_rests = sorted(restaurants, key=family_rest_key, reverse=True)

    # 方案 1：最佳亲子 + 最佳健康餐厅
    if sorted_acts and sorted_rests:
        plans.append(_make_plan(0, intent.scene, sorted_acts[0], sorted_rests[0]))

    # 方案 2：次佳组合（如果数据够）
    if len(sorted_acts) >= 2 and len(sorted_rests) >= 2:
        plans.append(_make_plan(1, intent.scene, sorted_acts[1], sorted_rests[1]))
    elif len(sorted_acts) >= 2 and sorted_rests:
        plans.append(_make_plan(1, intent.scene, sorted_acts[1], sorted_rests[0]))
    elif sorted_acts and len(sorted_rests) >= 2:
        plans.append(_make_plan(1, intent.scene, sorted_acts[0], sorted_rests[1]))

    # 方案 3：如果数据更多
    if len(sorted_acts) >= 3 and len(sorted_rests) >= 3:
        plans.append(_make_plan(2, intent.scene, sorted_acts[2], sorted_rests[2]))

    return plans


def _build_friends_plans(
    intent: Intent, activities: list[dict], restaurants: list[dict]
) -> list[dict]:
    """朋友场景方案生成"""
    plans: list[dict] = []

    def friends_act_key(a: dict) -> float:
        score = 0.0
        tags = a.get("tags", [])
        if any(t in tags for t in ["社交", "聚会", "桌游", "拍照", "约会"]):
            score += 2.0
        score += a.get("rating", 0) * 0.1
        score -= a.get("distance_km", 0) * 0.1
        return score

    def friends_rest_key(r: dict) -> float:
        score = 0.0
        tags = r.get("tags", [])
        if any(t in tags for t in ["约会", "拍照", "聚会", "社交", "高品质"]):
            score += 2.0
        score += r.get("rating", 0) * 0.2
        score -= r.get("distance_km", 0) * 0.1
        score -= r.get("queue_minutes", 0) * 0.005
        return score

    sorted_acts = sorted(activities, key=friends_act_key, reverse=True)
    sorted_rests = sorted(restaurants, key=friends_rest_key, reverse=True)

    if sorted_acts and sorted_rests:
        plans.append(_make_plan(0, intent.scene, sorted_acts[0], sorted_rests[0]))
    if len(sorted_acts) >= 2 and len(sorted_rests) >= 2:
        plans.append(_make_plan(1, intent.scene, sorted_acts[1], sorted_rests[1]))
    elif len(sorted_acts) >= 2 and sorted_rests:
        plans.append(_make_plan(1, intent.scene, sorted_acts[1], sorted_rests[0]))
    if len(sorted_acts) >= 3 and len(sorted_rests) >= 3:
        plans.append(_make_plan(2, intent.scene, sorted_acts[2], sorted_rests[2]))

    return plans


def _make_plan(
    index: int,
    scene: str,
    activity: dict | None,
    restaurant: dict | None,
) -> dict:
    """构建单个方案的字典"""
    plan_id = f"plan_{index + 1:03d}"
    act_name = activity["name"] if activity else "无"
    rest_name = restaurant["name"] if restaurant else "无"

    if scene == "family":
        title = f"亲子方案{index + 1}：{act_name} + {rest_name}"
    else:
        title = f"聚会方案{index + 1}：{act_name} + {rest_name}"

    timeline = _build_timeline(activity, restaurant)

    # 预算
    act_price = activity.get("avg_price", 0) if activity else 0
    rest_price = restaurant.get("avg_price", 0) if restaurant else 0
    per_person = act_price + rest_price
    total = per_person * 3 if scene == "family" else per_person * 4

    # 排队
    queue = (activity.get("queue_minutes", 0) if activity else 0) + (
        restaurant.get("queue_minutes", 0) if restaurant else 0
    )

    # 预约状态
    booking_status = "available"
    risk_tips = []
    if activity:
        if not activity.get("bookable"):
            booking_status = "partial"
            risk_tips.append(f"活动「{act_name}」不支持在线预约")
        if activity.get("risk"):
            risk_tips.append(activity["risk"])
        if activity.get("queue_minutes", 0) > 30:
            risk_tips.append(f"活动排队约{activity['queue_minutes']}分钟")
    if restaurant:
        if not restaurant.get("available"):
            booking_status = "unavailable"
            risk_tips.append(f"餐厅「{rest_name}」当前无位")
        if restaurant.get("risk"):
            risk_tips.append(restaurant["risk"])
        if restaurant.get("queue_minutes", 0) > 30:
            risk_tips.append(f"餐厅排队约{restaurant['queue_minutes']}分钟")

    # 推荐理由
    recommend_reasons = []
    if activity:
        if activity.get("child_friendly"):
            recommend_reasons.append("亲子友好")
        if activity.get("indoor"):
            recommend_reasons.append("室内活动")
        if activity.get("rating", 0) >= 4.5:
            recommend_reasons.append(f"评分{activity['rating']}")
    if restaurant:
        if restaurant.get("low_calorie_options"):
            recommend_reasons.append("提供低卡选项")
        if restaurant.get("child_friendly"):
            recommend_reasons.append("儿童友好餐厅")

    return {
        "plan_id": plan_id,
        "title": title,
        "scene": scene,
        "timeline": timeline,
        "activity": activity,
        "restaurant": restaurant,
        "route": None,
        "deals": [],
        "budget": {
            "total": total,
            "per_person": per_person,
            "currency": "CNY",
        },
        "queue_minutes": queue,
        "booking_status": booking_status,
        "risk_tips": risk_tips,
        "recommend_reasons": recommend_reasons,
        "score": 0.0,
        "score_reasons": [],
    }


def _build_timeline(
    activity: dict | None, restaurant: dict | None
) -> list[dict]:
    """构建时间线"""
    timeline = []
    if activity:
        act_dur = activity.get("recommended_duration_min", 120)
        timeline.append({
            "time": "14:00",
            "type": "activity",
            "title": activity.get("name", ""),
            "poi_id": activity.get("id", ""),
            "duration_min": act_dur,
        })
        if restaurant:
            start_h = 14 + act_dur // 60
            start_m = act_dur % 60
            # 简化：加 30 分钟路程
            start_m += 30
            if start_m >= 60:
                start_h += 1
                start_m -= 60
            time_str = f"{start_h:02d}:{start_m:02d}"
            timeline.append({
                "time": time_str,
                "type": "restaurant",
                "title": restaurant.get("name", ""),
                "poi_id": restaurant.get("id", ""),
                "duration_min": restaurant.get("recommended_duration_min", 75),
            })
    elif restaurant:
        timeline.append({
            "time": "17:30",
            "type": "restaurant",
            "title": restaurant.get("name", ""),
            "poi_id": restaurant.get("id", ""),
            "duration_min": restaurant.get("recommended_duration_min", 75),
        })
    return timeline


async def _enrich_plan(plan: dict, tool_logs: list[dict]) -> None:
    """为方案补充路线和团购券信息"""
    activity = plan.get("activity")
    restaurant = plan.get("restaurant")

    # 路线
    if activity and restaurant:
        act_area = activity.get("area", "")
        rest_area = restaurant.get("area", "")
        route_result = await _run_tool(
            "estimate_route", tool_logs,
            origin=act_area, destination=rest_area,
        )
        if route_result and route_result.status == "ok" and route_result.data:
            plan["route"] = route_result.data[0] if route_result.data else None

    # 团购券
    deals = []
    if activity:
        deal_result = await _run_tool(
            "get_deals", tool_logs, poi_id=activity.get("id", "")
        )
        if deal_result and deal_result.status == "ok" and deal_result.data:
            deals.extend(deal_result.data)
    if restaurant:
        deal_result = await _run_tool(
            "get_deals", tool_logs, poi_id=restaurant.get("id", "")
        )
        if deal_result and deal_result.status == "ok" and deal_result.data:
            deals.extend(deal_result.data)
    plan["deals"] = deals
