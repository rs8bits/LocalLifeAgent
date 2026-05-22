"""Planner - 标签对齐 → 场所搜索 → 方案组合"""

from typing import Any, Optional

from backend.agent.schemas import Intent, PlannerOutput
from backend.agent.intent_parser import parse_intent
from backend.agent.tag_resolver import resolve_domain_tags
from backend.agent.plan_composer import compose_plan_specs_with_llm
from backend.agent.scorer import score_plan
from backend.tools.registry import get_tool
from backend.mock_api.storage import read_json


async def plan_for_message(
    user_id: str,
    message: str,
) -> dict[str, Any]:
    """给定用户 ID 和自然语言消息，返回规划结果"""
    tool_logs: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    # 1. 读取用户记忆
    user_memory = _load_user_memory(user_id)

    # 2. 解析意图
    intent: Intent = await parse_intent(message, user_memory)
    intent_dict = intent.model_dump()

    # 3. 标签对齐
    tag_result = await resolve_domain_tags(
        message=message, intent=intent, intent_dict=intent_dict,
    )
    spec_by_domain = _domain_spec_map(tag_result)
    domains = list(spec_by_domain.keys())
    domain_required = tag_result.get("domain_required", {})

    # 4. 查询天气
    weather_result = await _run_tool(
        "get_weather", tool_logs,
        date=_resolve_mock_weather_date(intent.date), location="朝阳区",
    )

    indoor_pref = _indoor_preference(weather_result, intent)
    party_type = intent.party_type
    radius = intent.radius_km
    people = intent.people_count
    queue_limit = (intent.avoid_queue_minutes or 30) * 2

    # 5. 场所搜索 (按 domain)
    activities: list[dict] = []
    restaurants: list[dict] = []
    drinks: list[dict] = []
    delivery_items: list[dict] = []

    for domain_name in domains:
        if domain_name == "delivery":
            delivery_params = _build_delivery_search_params(spec_by_domain[domain_name], party_type)
            result = await _run_tool("search_delivery_items", tool_logs, **delivery_params)
        else:
            params = _build_place_search_params(
                domain_name=domain_name,
                spec=spec_by_domain[domain_name],
                party_type=party_type,
                radius=radius,
                people=people,
                queue_limit=queue_limit,
                child_age=intent.child_age if _has_child_context(intent) else None,
                indoor_pref=indoor_pref,
            )
            result = await _run_tool("search_places", tool_logs, **params)

        if result and result.status == "ok":
            data = result.data or []
            if domain_name == "play":
                activities = data
            elif domain_name == "eat":
                restaurants = data
            elif domain_name == "drink":
                drinks = data
            elif domain_name == "delivery":
                delivery_items = data
            if result.error:
                warnings.append(f"[{domain_name}] {result.error}")

    # 6. 组合方案：LLM 输出方案 JSON，本地规则作为兜底
    fallback_plans = _build_diverse_plans(intent, activities, restaurants, drinks, tool_logs)
    if not fallback_plans and delivery_items:
        fallback_plans = _build_delivery_only_plans(intent, delivery_items)
    _attach_delivery_to_plans(fallback_plans, delivery_items, intent)

    weather_data = weather_result.data[0] if weather_result and weather_result.status == "ok" and weather_result.data else None
    llm_specs, composer_warning = await compose_plan_specs_with_llm(
        message=message,
        intent=intent,
        user_memory=user_memory,
        tag_result=tag_result,
        weather=weather_data,
        candidates={
            "activities": activities,
            "restaurants": restaurants,
            "drinks": drinks,
            "delivery_items": delivery_items,
        },
    )
    if composer_warning:
        tool_logs.append({
            "tool": "llm_plan_composer",
            "status": "fallback",
            "message": composer_warning,
        })
    plans = [
        _make_plan_from_composer_spec(i, spec, intent, activities, restaurants, drinks, delivery_items)
        for i, spec in enumerate(llm_specs)
    ] if llm_specs else fallback_plans

    # 7. 错误/警告语义：有可用方案时，领域缺失进入风险提示；无方案才进入 errors。
    for domain_name in domains:
        is_required = domain_required.get(domain_name, False)
        count = {
            "play": len(activities),
            "eat": len(restaurants),
            "drink": len(drinks),
            "delivery": len(delivery_items),
        }.get(domain_name, 0)
        label_cn = {
            "play": "活动",
            "eat": "餐厅",
            "drink": "饮品",
            "delivery": "外卖/闪送商品",
        }.get(domain_name, domain_name)
        if count == 0:
            if plans:
                suffix = "用户明确要求，已作为风险提示" if is_required else "该领域非必须"
                warnings.append(f"未找到符合条件的{label_cn}（{suffix}）")
            elif is_required:
                errors.append(f"未找到符合条件的{label_cn}")

    if not plans and not errors:
        errors.append("未生成候选方案")

    # warnings 注入到方案 risk_tips
    if warnings and plans:
        for w in warnings:
            if w not in plans[0].get("risk_tips", []):
                plans[0].setdefault("risk_tips", []).append(w)

    # 8. 丰富方案 + 评分
    for plan in plans:
        await _enrich_plan(plan, tool_logs)
        _ensure_plan_actions(plan, intent)
    for plan in plans:
        score_plan(plan, intent)
    plans.sort(key=lambda p: p.get("score", 0.0), reverse=True)

    return PlannerOutput(
        intent=intent_dict,
        plans=plans[:4],
        tool_logs=tool_logs,
        errors=errors,
    ).model_dump()


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _load_user_memory(user_id: str) -> Optional[dict]:
    try:
        memories = read_json("user_memory.json")
        for m in memories:
            if m.get("user_id") == user_id:
                return m
    except Exception:
        pass
    return None


def _resolve_mock_weather_date(date_text: str) -> str:
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


async def _run_tool(name: str, tool_logs: list[dict], **kwargs) -> Any:
    tool = get_tool(name)
    if not tool:
        tool_logs.append({"tool": name, "status": "error", "message": f"工具 {name} 未注册"})
        return None
    filtered = {k: v for k, v in kwargs.items() if v is not None}
    result = await tool.run(**filtered)
    query_suffix = _format_tool_query(filtered)
    log_message = f"{result.message} | {query_suffix}" if query_suffix else result.message
    log = {"tool": result.tool, "status": result.status, "message": log_message}
    if result.error:
        log["detail"] = result.error
    tool_logs.append(log)
    return result


def _format_tool_query(params: dict[str, Any]) -> str:
    keys = ["domain", "party_type", "category", "categories_any", "sub_category", "tags_any", "tags_all"]
    parts = []
    for key in keys:
        value = params.get(key)
        if value:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def _indoor_preference(weather_result: Any, intent: Intent) -> Optional[bool]:
    if not weather_result or weather_result.status != "ok":
        return None
    data = weather_result.data
    if not data:
        return None
    w = data[0]
    if not w.get("outdoor_suitable", True):
        return True
    return None


def _domain_spec_map(tag_result: dict) -> dict[str, dict]:
    specs = tag_result.get("domain_specs") or []
    if specs:
        return {
            spec["domain"]: spec
            for spec in specs
            if spec.get("domain") in ("play", "eat", "drink", "delivery")
        }
    result = {}
    for domain_name in tag_result.get("domains", []):
        result[domain_name] = {
            "domain": domain_name,
            "required": tag_result.get("domain_required", {}).get(domain_name, False),
            "categories": tag_result.get("domain_categories", {}).get(domain_name, []),
            "tags": tag_result.get("domain_tags", {}).get(domain_name, []),
            "sub_categories": tag_result.get("domain_sub_categories", {}).get(domain_name, []),
        }
    return result


def _apply_domain_spec_filters(params: dict[str, Any], spec: dict) -> None:
    categories = spec.get("categories") or []
    tags = spec.get("tags") or []
    sub_categories = spec.get("sub_categories") or []
    tag_signals = [*categories, *tags, *sub_categories]
    if tag_signals:
        params["tags_any"] = _unique_values(tag_signals)


def _unique_values(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _build_place_search_params(
    *,
    domain_name: str,
    spec: dict,
    party_type: str,
    radius: float,
    people: int | None,
    queue_limit: int,
    child_age: int | None,
    indoor_pref: bool | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "domain": domain_name,
        "radius_km": radius,
    }
    if party_type != "general":
        params["party_type"] = party_type
    _apply_domain_spec_filters(params, spec)
    if domain_name == "play":
        params["child_age"] = child_age
        params["indoor"] = indoor_pref
    elif domain_name == "eat":
        params["party_size"] = people
        params["available"] = True
        params["max_queue_minutes"] = queue_limit
    return params


def _build_delivery_search_params(spec: dict, party_type: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if party_type != "general":
        params["party_type"] = party_type
    _apply_domain_spec_filters(params, spec)
    return params


# ═══════════════════════════════════════════════════════════════
# 动态方案组合
# ═══════════════════════════════════════════════════════════════

def _build_diverse_plans(
    intent: Intent,
    activities: list[dict],
    restaurants: list[dict],
    drinks: list[dict],
    tool_logs: list[dict],
) -> list[dict]:
    """生成多个不同风格的方案（不同 POI 组合，不评分排序）"""
    plans: list[dict] = []

    # 过滤：确保活动适宜
    if _has_child_context(intent):
        activities = [a for a in activities if a.get("child_friendly")]
        restaurants = [r for r in restaurants if r.get("child_friendly")]

    # 晚餐场景排除咖啡甜品为主的正餐不适合餐厅
    if intent.time_window == "evening":
        restaurants = [r for r in restaurants if r.get("meal_suitable") is not False]

    # 排序：场景适配优先
    if _has_child_context(intent):
        activities.sort(key=_family_act_key(intent), reverse=True)
        restaurants.sort(key=_family_rest_key(intent), reverse=True)
    elif intent.party_type in {"family_elder", "family"}:
        activities.sort(key=_family_group_act_key(intent), reverse=True)
        restaurants.sort(key=_family_group_rest_key(intent), reverse=True)
    elif intent.party_type in {"couple", "business", "solo"}:
        activities.sort(key=_general_act_key(intent), reverse=True)
        restaurants.sort(key=_general_rest_key(intent), reverse=True)
    else:
        activities.sort(key=_friends_act_key(), reverse=True)
        restaurants.sort(key=_friends_rest_key(), reverse=True)

    # 饮品排序：匹配用户偏好
    drinks_sorted = sorted(drinks, key=_drink_key(intent), reverse=True)

    top_acts = activities[:4]
    top_rests = restaurants[:4]
    top_drink = drinks_sorted[0] if drinks_sorted else None
    alt_drink = drinks_sorted[1] if len(drinks_sorted) >= 2 else None

    if not top_acts and not top_rests and not top_drink:
        return plans

    # 方案1：最佳活动 + 最佳餐厅 + 最佳饮品
    plans.append(_make_plan_with_timeline(0, intent, top_acts[0] if top_acts else None,
        top_rests[0] if top_rests else None, top_drink))

    # 方案2：同一活动 + 不同餐厅
    if len(top_rests) >= 2:
        plans.append(_make_plan_with_timeline(1, intent, top_acts[0] if top_acts else None,
            top_rests[1], alt_drink or top_drink))

    # 方案3：不同活动 + 最佳餐厅
    if len(top_acts) >= 2:
        plans.append(_make_plan_with_timeline(2, intent, top_acts[1],
            top_rests[0] if top_rests else None, alt_drink or top_drink))

    # 方案4：不同活动 + 不同餐厅（如果数据够）
    if len(top_acts) >= 2 and len(top_rests) >= 2:
        plans.append(_make_plan_with_timeline(3, intent, top_acts[1],
            top_rests[1], alt_drink or top_drink))

    # 去重（相同 POI 组合只保留一个）
    seen_combos = set()
    unique_plans = []
    for p in plans:
        act_id = (p.get("activity") or {}).get("id", "")
        rest_id = (p.get("restaurant") or {}).get("id", "")
        drink_id = (p.get("drink") or {}).get("id", "")
        combo = (act_id, rest_id, drink_id)
        if combo not in seen_combos:
            seen_combos.add(combo)
            unique_plans.append(p)

    return unique_plans


def _has_child_context(intent: Intent) -> bool:
    return intent.party_type == "family_with_child" or intent.child_age is not None or any(
        c.get("role") == "child" for c in intent.companions
    )


def _family_act_key(intent: Intent):
    def key(a: dict) -> float:
        s = a.get("_match_score", 0) * 2.0
        if a.get("child_friendly"): s += 3.0
        if intent.child_age and a.get("suitable_age_min", 0) <= intent.child_age <= a.get("suitable_age_max", 99):
            s += 2.0
        s -= a.get("distance_km", 0) * 0.1
        s -= a.get("queue_minutes", 0) * 0.01
        return s
    return key


def _family_rest_key(intent: Intent):
    def key(r: dict) -> float:
        s = r.get("_match_score", 0) * 2.0
        if r.get("child_friendly"): s += 3.0
        if intent.needs_low_calorie:
            if r.get("low_calorie_options"): s += 3.0
            if any(t in r.get("tags", []) for t in ["健康", "轻食", "低卡", "减脂"]):
                s += 1.0
        s -= r.get("distance_km", 0) * 0.1
        s -= r.get("queue_minutes", 0) * 0.01
        return s
    return key


def _family_group_act_key(intent: Intent):
    def key(a: dict) -> float:
        s = a.get("_match_score", 0) * 2.0
        tags = a.get("tags", [])
        if any(t in tags for t in ["户外", "公园", "展览", "艺术", "轻松"]):
            s += 1.5
        if intent.needs_less_walking:
            s -= a.get("distance_km", 0) * 0.25
            s -= a.get("queue_minutes", 0) * 0.03
        else:
            s -= a.get("distance_km", 0) * 0.1
            s -= a.get("queue_minutes", 0) * 0.01
        s += a.get("rating", 0) * 0.2
        return s
    return key


def _family_group_rest_key(intent: Intent):
    def key(r: dict) -> float:
        s = r.get("_match_score", 0) * 2.0
        tags = r.get("tags", [])
        if any(t in tags for t in ["健康", "轻食", "低卡", "高品质", "聚会"]):
            s += 2.0
        if r.get("available"):
            s += 1.0
        if intent.needs_less_walking:
            s -= r.get("distance_km", 0) * 0.25
            s -= r.get("queue_minutes", 0) * 0.04
        else:
            s -= r.get("distance_km", 0) * 0.1
            s -= r.get("queue_minutes", 0) * 0.01
        return s
    return key


def _general_act_key(intent: Intent):
    def key(a: dict) -> float:
        s = a.get("_match_score", 0) * 2.0
        tags = a.get("tags", [])
        if intent.party_type == "couple" and any(t in tags for t in ["拍照", "艺术", "音乐", "约会"]):
            s += 3.0
        if intent.party_type == "business" and any(t in tags for t in ["高品质", "展览", "艺术"]):
            s += 2.0
        if intent.party_type == "solo" and any(t in tags for t in ["咖啡", "公园", "艺术", "观影"]):
            s += 1.5
        s += a.get("rating", 0) * 0.2
        s -= a.get("distance_km", 0) * 0.1
        s -= a.get("queue_minutes", 0) * 0.01
        return s
    return key


def _general_rest_key(intent: Intent):
    def key(r: dict) -> float:
        s = r.get("_match_score", 0) * 2.0
        tags = r.get("tags", [])
        if intent.party_type == "couple" and any(t in tags for t in ["约会", "拍照", "高品质", "出片"]):
            s += 3.0
        if intent.party_type == "business" and any(t in tags for t in ["高品质", "聚会", "品质"]):
            s += 3.0
        if intent.party_type == "solo" and any(t in tags for t in ["健康", "轻食", "小吃"]):
            s += 1.5
        if r.get("available"):
            s += 0.8
        s += r.get("rating", 0) * 0.2
        s -= r.get("distance_km", 0) * 0.1
        s -= r.get("queue_minutes", 0) * 0.01
        return s
    return key


def _friends_act_key():
    def key(a: dict) -> float:
        s = a.get("_match_score", 0) * 2.0
        tags = a.get("tags", [])
        if any(t in tags for t in ["社交", "聚会", "桌游", "拍照", "唱歌", "密室", "电竞", "音乐"]):
            s += 3.0
        s += a.get("rating", 0) * 0.2
        s -= a.get("distance_km", 0) * 0.1
        return s
    return key


def _friends_rest_key():
    def key(r: dict) -> float:
        s = r.get("_match_score", 0) * 2.0
        tags = r.get("tags", [])
        if any(t in tags for t in ["约会", "拍照", "聚会", "社交", "高品质", "网红"]):
            s += 3.0
        s += r.get("rating", 0) * 0.2
        s -= r.get("distance_km", 0) * 0.1
        s -= r.get("queue_minutes", 0) * 0.005
        return s
    return key


def _drink_key(intent: Intent):
    def key(d: dict) -> float:
        s = d.get("_match_score", 0) * 2.0
        prefs = intent.drink_preferences or []
        if "bar" in prefs and d.get("sub_category") == "bar":
            s += 5.0
        elif "coffee_tea" in prefs and d.get("sub_category") in ("coffee", "tea", "milk_tea"):
            s += 5.0
        s -= d.get("distance_km", 0) * 0.1
        s += d.get("rating", 0) * 0.1
        return s
    return key


# ═══════════════════════════════════════════════════════════════
# 时间感知方案构建
# ═══════════════════════════════════════════════════════════════

def _resolve_time_constraints(intent: Intent) -> tuple[str, int]:
    """根据意图确定开始时间和可用分钟数"""
    window_starts = {
        "morning": "09:00",
        "afternoon": "13:00",
        "evening": "17:00",
        "unknown": "14:00",
    }
    start = window_starts.get(intent.time_window, "14:00")
    default_hours = {
        "morning": 3, "afternoon": 6, "evening": 4, "unknown": 4,
    }
    hours = intent.duration_hours or default_hours.get(intent.time_window, 4)
    return start, hours * 60


def _time_to_minutes(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _minutes_to_time(m: int) -> str:
    h = (m // 60) % 24
    mm = m % 60
    return f"{h:02d}:{mm:02d}"


def _parse_business_hours(bh: str | None) -> tuple[int, int] | None:
    """解析营业时间，如 '17:00-02:00' -> (open_min, close_min)。跨午夜 close 会 +24h。"""
    if not bh:
        return None
    try:
        parts = bh.split("-")
        if len(parts) != 2:
            return None
        open_t = _time_to_minutes(parts[0].strip())
        close_t = _time_to_minutes(parts[1].strip())
        if close_t <= open_t:
            close_t += 24 * 60
        return (open_t, close_t)
    except (ValueError, AttributeError):
        return None


def _is_within_business_hours(time_min: int, bh: tuple[int, int] | None) -> bool:
    if bh is None:
        return True
    open_min, close_min = bh
    day_start = (time_min // (24 * 60)) * 24 * 60
    t = time_min - day_start
    o = open_min
    c = close_min
    return o <= t <= c


def _align_to_slot(preferred_min: int, available_slots: list[str]) -> int | None:
    """找到不早于 preferred_min 的最近可用时段"""
    if not available_slots:
        return None
    day_start = (preferred_min // (24 * 60)) * 24 * 60
    pref_ofs = preferred_min - day_start
    for s in sorted(available_slots):
        slot_min = _time_to_minutes(s)
        if slot_min >= pref_ofs:
            return day_start + slot_min
    return None


_MIN_DURATION = {"activity": 45, "restaurant": 45, "drink": 10, "delivery": 5}


def _resolve_poi_start_time(timeline: list[dict], slot_type: str) -> str | None:
    """从时间线中提取指定类型 POI 的开始时间"""
    for t in timeline:
        if t.get("type") == slot_type:
            return t.get("time")
    return None


def _estimate_transit(poi_a: dict | None, poi_b: dict | None) -> int:
    if not poi_a or not poi_b:
        return 15
    if poi_a.get("area") == poi_b.get("area"):
        return 5
    return 20


def _schedule_slots(
    start_time: str,
    budget_min: int,
    activity: dict | None,
    drink: dict | None,
    restaurant: dict | None,
    time_window: str,
) -> list[dict]:
    """动态调度 POI 到时间线，尊重营业时间和可预约时段"""
    timeline = []
    current_min = _time_to_minutes(start_time)

    if time_window == "evening":
        slots = [
            ("restaurant", restaurant),
            ("drink", drink),
            ("activity", activity),
        ]
    else:
        slots = [
            ("activity", activity),
            ("drink", drink),
            ("restaurant", restaurant),
        ]

    for i, (slot_type, poi) in enumerate(slots):
        if poi is None:
            continue

        bh = _parse_business_hours(poi.get("business_hours"))
        rec_dur = poi.get("recommended_duration_min", _default_duration(slot_type))
        min_dur = _MIN_DURATION.get(slot_type, 10)
        dur = rec_dur

        # 检查营业时间
        if bh and not _is_within_business_hours(current_min, bh):
            open_min = bh[0]
            day_start = (current_min // (24 * 60)) * 24 * 60
            next_open = day_start + open_min
            if next_open < current_min:
                next_open += 24 * 60
            if next_open - (current_min // (24 * 60) * 24 * 60 + _time_to_minutes(start_time)) <= budget_min:
                current_min = next_open

        # 可预约 POI：对齐 available_slots
        slots_avail = poi.get("available_slots", [])
        if poi.get("bookable") and slots_avail:
            aligned = _align_to_slot(current_min, slots_avail)
            if aligned is not None and aligned >= current_min:
                current_min = aligned

        # 再次检查营业时间（对齐后）
        if bh and not _is_within_business_hours(current_min, bh):
            continue  # skip if still outside

        # 预算检查：确保剩余时间够最低时长
        elapsed = current_min - _time_to_minutes(start_time)
        remaining = budget_min - elapsed
        if remaining < min_dur:
            continue

        dur = min(dur, max(remaining, min_dur))

        timeline.append({
            "time": _minutes_to_time(current_min),
            "type": slot_type,
            "title": poi.get("name", ""),
            "poi_id": poi.get("id", ""),
            "duration_min": dur,
        })
        current_min += dur

        # 中转
        next_poi = None
        for j in range(i + 1, len(slots)):
            if slots[j][1] is not None:
                next_poi = slots[j][1]
                break

        if next_poi:
            transit = _estimate_transit(poi, next_poi)
            timeline.append({
                "time": _minutes_to_time(current_min),
                "type": "transit",
                "title": f"前往 {next_poi.get('name', '')}",
                "poi_id": "",
                "duration_min": transit,
            })
            current_min += transit

    return timeline


def _default_duration(slot_type: str) -> int:
    return {"activity": 120, "restaurant": 75, "drink": 25, "delivery": 5}.get(slot_type, 60)


def _make_plan_with_timeline(
    index: int,
    intent: Intent,
    activity: dict | None,
    restaurant: dict | None,
    drink: dict | None,
) -> dict:
    """构建含动态时间线的单个方案"""
    plan_id = f"plan_{index + 1:03d}"
    scene = intent.scene

    # 标题
    parts = []
    if activity:
        parts.append(activity["name"])
    if drink:
        parts.append(drink["name"])
    if restaurant:
        parts.append(restaurant["name"])
    prefix = _party_title_prefix(intent)
    title = f"{prefix}{index + 1}：{' + '.join(parts)}" if parts else f"{prefix}{index + 1}"

    # 时间线
    start_time, budget_min = _resolve_time_constraints(intent)
    timeline = _schedule_slots(start_time, budget_min, activity, drink, restaurant, intent.time_window)

    # 预算
    act_price = activity.get("avg_price", 0) if activity else 0
    rest_price = restaurant.get("avg_price", 0) if restaurant else 0
    drink_price = drink.get("avg_price", 0) if drink else 0
    per_person = act_price + rest_price + drink_price
    people = intent.people_count or _default_people_count(intent)
    total = per_person * people

    # 排队
    queue = 0
    if activity: queue += activity.get("queue_minutes", 0)
    if restaurant: queue += restaurant.get("queue_minutes", 0)
    if drink: queue += drink.get("queue_minutes", 0)

    # 预约状态
    booking_status = "available"
    risk_tips: list[str] = []
    if activity:
        if not activity.get("bookable"):
            booking_status = "partial"
            risk_tips.append(f"活动「{activity['name']}」不支持在线预约")
        if activity.get("risk"):
            risk_tips.append(activity["risk"])
        if activity.get("queue_minutes", 0) > 30:
            risk_tips.append(f"活动排队约{activity['queue_minutes']}分钟")
    if restaurant:
        if not restaurant.get("available"):
            booking_status = "unavailable"
            risk_tips.append(f"餐厅「{restaurant['name']}」当前无位")
        if restaurant.get("risk"):
            risk_tips.append(restaurant["risk"])
    if drink:
        if drink.get("risk"):
            risk_tips.append(drink["risk"])
        if drink.get("sub_category") == "bar" and intent.time_window in ("morning", "afternoon"):
            risk_tips.append(f"酒吧「{drink['name']}」下午可能尚未营业")
        drink_bh = _parse_business_hours(drink.get("business_hours"))
        if drink_bh:
            drink_start = _resolve_poi_start_time(timeline, "drink")
            if drink_start and not _is_within_business_hours(_time_to_minutes(drink_start), drink_bh):
                risk_tips.append(f"饮品「{drink['name']}」在 {drink_start} 不营业")
        if drink.get("available_slots") and not drink.get("bookable"):
            risk_tips.append(f"饮品「{drink['name']}」不支持预约")

    # 检查活动营业时间
    if activity:
        act_bh = _parse_business_hours(activity.get("business_hours"))
        if act_bh:
            act_start = _resolve_poi_start_time(timeline, "activity")
            if act_start and not _is_within_business_hours(_time_to_minutes(act_start), act_bh):
                risk_tips.append(f"活动「{activity['name']}」在 {act_start} 不营业")

    # 检查餐厅时长
    if restaurant:
        rest_item = next((t for t in timeline if t.get("type") == "restaurant"), None)
        if rest_item and rest_item.get("duration_min", 0) < 45:
            risk_tips.append(f"餐厅「{restaurant['name']}」用餐时间不足45分钟")

    # 推荐理由
    recommend_reasons: list[str] = []
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
    if drink:
        if drink.get("rating", 0) >= 4.5:
            recommend_reasons.append(f"饮品评分{drink['rating']}")

    return {
        "plan_id": plan_id,
        "title": title,
        "scene": scene,
        "party_type": intent.party_type,
        "timeline": timeline,
        "activity": activity,
        "restaurant": restaurant,
        "drink": drink,
        "delivery_items": [],
        "actions": [],
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


def _attach_delivery_to_plans(
    plans: list[dict],
    delivery_items: list[dict],
    intent: Intent,
) -> None:
    """本地兜底：把最合适的外卖/闪送商品挂到方案上。"""
    if not plans or not delivery_items:
        return
    sorted_items = sorted(delivery_items, key=_delivery_key(intent), reverse=True)
    for idx, plan in enumerate(plans):
        if plan.get("delivery_items"):
            continue
        item, target = _select_delivery_for_plan(sorted_items, plan)
        if not item:
            continue
        item = dict(item)
        item["_delivery_target_ref_id"] = target.get("id")
        item["_delivery_target_name"] = target.get("name")
        item["_delivery_target_area"] = target.get("area")
        plan["delivery_items"] = [item]
        delivery_time = _delivery_time_for_plan(plan, item)
        plan.setdefault("timeline", []).append({
            "time": delivery_time,
            "type": "delivery",
            "title": f"{item.get('name', '')}送达{target.get('name', '目的地')}",
            "poi_id": item.get("id", ""),
            "duration_min": 5,
        })
        plan["timeline"] = _sort_timeline(plan["timeline"])
        plan.setdefault("recommend_reasons", []).append("可叠加外卖/闪送服务")
        if target and target != (plan.get("restaurant") or {}):
            plan.setdefault("risk_tips", []).append("配送商品不支持送到餐厅，已改为送达活动地点")
        if item.get("risk"):
            plan.setdefault("risk_tips", []).append(item["risk"])
        _recalculate_budget(plan, intent)


def _select_delivery_for_plan(delivery_items: list[dict], plan: dict) -> tuple[dict | None, dict]:
    targets = [
        plan.get("restaurant") or {},
        plan.get("activity") or {},
        plan.get("drink") or {},
    ]
    for target in [t for t in targets if t]:
        item = next((candidate for candidate in delivery_items if _delivery_supports_target(candidate, target)), None)
        if item:
            return item, target
    return None, {}


def _delivery_supports_target(item: dict, target: dict) -> bool:
    target_area = target.get("area")
    if not target_area:
        return True
    available_areas = item.get("available_areas") or []
    return target_area in available_areas


def _build_delivery_only_plans(intent: Intent, delivery_items: list[dict]) -> list[dict]:
    """用户只要求外卖/闪送时生成可执行的配送方案。"""
    plans = []
    for idx, item in enumerate(sorted(delivery_items, key=_delivery_key(intent), reverse=True)[:3]):
        delivery_time = "15:30" if intent.time_window != "evening" else "18:00"
        plan = {
            "plan_id": f"plan_{idx + 1:03d}",
            "title": f"配送方案{idx + 1}：{item.get('name', '')}",
            "scene": intent.scene,
            "party_type": intent.party_type,
            "timeline": [{
                "time": delivery_time,
                "type": "delivery",
                "title": f"{item.get('name', '')}送达指定地点",
                "poi_id": item.get("id", ""),
                "duration_min": 5,
            }],
            "activity": None,
            "restaurant": None,
            "drink": None,
            "delivery_items": [item],
            "actions": [],
            "route": None,
            "deals": [],
            "budget": {},
            "queue_minutes": 0,
            "booking_status": "available",
            "risk_tips": [item["risk"]] if item.get("risk") else [],
            "recommend_reasons": ["可直接创建外卖/闪送 Mock 订单"],
            "score": 0.0,
            "score_reasons": [],
        }
        _recalculate_budget(plan, intent)
        plans.append(plan)
    return plans


def _delivery_key(intent: Intent):
    def key(item: dict) -> float:
        tags = item.get("tags", [])
        score = item.get("_match_score", 0) * 3.0
        for pref in intent.delivery_preferences or []:
            if pref in tags or pref == item.get("sub_category"):
                score += 4.0
        if _has_child_context(intent) and "亲子" in tags:
            score += 2.0
        if intent.needs_low_calorie and any(t in tags for t in ["健康", "低卡", "轻食"]):
            score += 3.0
        score -= item.get("estimated_delivery_min", 60) * 0.02
        return score
    return key


def _party_title_prefix(intent: Intent) -> str:
    return {
        "family_with_child": "亲子方案",
        "family_elder": "长辈家庭方案",
        "family": "家庭方案",
        "friends": "朋友方案",
        "couple": "约会方案",
        "business": "商务方案",
        "solo": "个人方案",
    }.get(intent.party_type, "出行方案")


def _default_people_count(intent: Intent) -> int:
    return {
        "family_with_child": 3,
        "family_elder": 3,
        "family": 3,
        "friends": 4,
        "couple": 2,
        "business": 2,
        "solo": 1,
    }.get(intent.party_type, 2)


def _delivery_time_for_plan(plan: dict, item: dict) -> str:
    restaurant_time = _timeline_time_for(plan, "restaurant")
    if restaurant_time:
        return restaurant_time
    activity_time = _timeline_time_for(plan, "activity")
    if activity_time:
        return _minutes_to_time(_time_to_minutes(activity_time) + 60)
    return "15:30"


def _make_plan_from_composer_spec(
    index: int,
    spec: dict,
    intent: Intent,
    activities: list[dict],
    restaurants: list[dict],
    drinks: list[dict],
    delivery_items: list[dict],
) -> dict:
    """将 LLM 输出的引用 JSON 转换为前端/执行器使用的完整 Plan。"""
    refs = spec.get("selected_refs", {})
    activity = _find_by_id(activities, refs.get("activity_id"))
    restaurant = _find_by_id(restaurants, refs.get("restaurant_id"))
    drink = _find_by_id(drinks, refs.get("drink_id"))
    deliveries = [
        item for item_id in refs.get("delivery_item_ids", [])
        if (item := _find_by_id(delivery_items, item_id))
    ]

    base = _make_plan_with_timeline(index, intent, activity, restaurant, drink)
    if spec.get("title"):
        base["title"] = str(spec["title"])
    timeline = _timeline_from_spec(spec.get("timeline", []), activity, restaurant, drink, deliveries)
    if timeline:
        base["timeline"] = timeline
    base["delivery_items"] = deliveries
    base["actions"] = _normalize_actions_from_spec(spec.get("actions", []))
    for reason in spec.get("recommend_reasons") or []:
        if reason not in base["recommend_reasons"]:
            base["recommend_reasons"].append(str(reason))
    for risk in spec.get("risk_tips") or []:
        if risk not in base["risk_tips"]:
            base["risk_tips"].append(str(risk))
    _recalculate_budget(base, intent)
    return base


def _timeline_from_spec(
    raw_timeline: list[dict],
    activity: dict | None,
    restaurant: dict | None,
    drink: dict | None,
    delivery_items: list[dict],
) -> list[dict]:
    item_map = {}
    for item in [activity, restaurant, drink, *delivery_items]:
        if item:
            item_map[item.get("id")] = item

    timeline = []
    for raw in raw_timeline:
        ref_id = raw.get("ref_id") or raw.get("poi_id") or ""
        poi = item_map.get(ref_id, {})
        title = raw.get("title") or poi.get("name", "")
        step_type = _normalize_timeline_type(raw.get("type") or _type_from_id(ref_id))
        timeline.append({
            "time": raw.get("time") or "",
            "type": step_type,
            "title": title,
            "poi_id": ref_id,
            "duration_min": int(raw.get("duration_min") or _default_duration(step_type)),
        })
    return _sort_timeline(timeline)


def _normalize_actions_from_spec(raw_actions: list[dict]) -> list[dict]:
    actions = []
    for idx, action in enumerate(raw_actions):
        if not isinstance(action, dict):
            continue
        actions.append({
            "action_id": action.get("action_id") or f"action_{idx + 1}",
            "type": action.get("type", ""),
            "ref_id": action.get("ref_id", ""),
            "scheduled_time": action.get("scheduled_time") or "",
            "quantity": int(action.get("quantity") or 1),
            "target_ref_id": action.get("target_ref_id"),
        })
    return actions


def _ensure_plan_actions(plan: dict, intent: Intent) -> None:
    """为前端确认页和执行器补齐可执行动作 JSON。"""
    existing = plan.get("actions") or []
    seen = {(a.get("type"), a.get("ref_id")) for a in existing}
    actions = list(existing)

    activity = plan.get("activity")
    if activity and activity.get("bookable") and ("book_activity", activity.get("id")) not in seen:
        actions.append({
            "action_id": f"book_{activity.get('id')}",
            "type": "book_activity",
            "ref_id": activity.get("id"),
            "scheduled_time": _timeline_time_for(plan, "activity") or "14:00",
            "quantity": intent.people_count or 1,
            "target_ref_id": None,
        })

    restaurant = plan.get("restaurant")
    if restaurant and restaurant.get("bookable") and restaurant.get("available") and ("book_restaurant", restaurant.get("id")) not in seen:
        actions.append({
            "action_id": f"book_{restaurant.get('id')}",
            "type": "book_restaurant",
            "ref_id": restaurant.get("id"),
            "scheduled_time": _timeline_time_for(plan, "restaurant") or "17:30",
            "quantity": intent.people_count or 1,
            "target_ref_id": None,
        })

    drink = plan.get("drink")
    if drink and drink.get("bookable") and ("book_drink", drink.get("id")) not in seen:
        actions.append({
            "action_id": f"book_{drink.get('id')}",
            "type": "book_drink",
            "ref_id": drink.get("id"),
            "scheduled_time": _timeline_time_for(plan, "drink") or "16:00",
            "quantity": intent.people_count or 1,
            "target_ref_id": None,
        })

    for item in plan.get("delivery_items") or []:
        if ("order_delivery", item.get("id")) in seen:
            continue
        target = plan.get("restaurant") or plan.get("activity") or plan.get("drink") or {}
        target_ref_id = item.get("_delivery_target_ref_id") or target.get("id")
        actions.append({
            "action_id": f"order_{item.get('id')}",
            "type": "order_delivery",
            "ref_id": item.get("id"),
            "scheduled_time": _timeline_time_for(plan, "delivery") or _delivery_time_for_plan(plan, item),
            "quantity": 1,
            "target_ref_id": target_ref_id,
        })

    for deal in plan.get("deals") or []:
        if ("order_deal", deal.get("id")) in seen:
            continue
        actions.append({
            "action_id": f"deal_{deal.get('id')}",
            "type": "order_deal",
            "ref_id": deal.get("id"),
            "scheduled_time": "",
            "quantity": 1,
            "target_ref_id": deal.get("poi_id"),
        })

    plan["actions"] = actions


def _find_by_id(items: list[dict], item_id: str | None) -> dict | None:
    if not item_id:
        return None
    return next((item for item in items if item.get("id") == item_id), None)


def _type_from_id(ref_id: str) -> str:
    if ref_id.startswith("act_"):
        return "activity"
    if ref_id.startswith("rest_"):
        return "restaurant"
    if ref_id.startswith("drink_"):
        return "drink"
    if ref_id.startswith("delivery_"):
        return "delivery"
    return "transit"


def _normalize_timeline_type(value: str) -> str:
    return {
        "play": "activity",
        "activity": "activity",
        "eat": "restaurant",
        "restaurant": "restaurant",
        "drink": "drink",
        "delivery": "delivery",
        "flash": "delivery",
        "takeout": "delivery",
        "transit": "transit",
    }.get(value, "activity")


def _timeline_time_for(plan: dict, slot_type: str) -> str | None:
    for item in plan.get("timeline") or []:
        if item.get("type") == slot_type:
            return item.get("time")
    return None


def _sort_timeline(timeline: list[dict]) -> list[dict]:
    return sorted(timeline, key=lambda item: item.get("time") or "99:99")


def _recalculate_budget(plan: dict, intent: Intent) -> None:
    people = intent.people_count or _default_people_count(intent)
    per_person = 0
    for key in ["activity", "restaurant", "drink"]:
        if plan.get(key):
            per_person += plan[key].get("avg_price", 0)
    delivery_total = 0
    for item in plan.get("delivery_items") or []:
        delivery_total += item.get("avg_price", 0) + item.get("delivery_fee", 0)
    plan["budget"] = {
        "total": per_person * people + delivery_total,
        "per_person": per_person + (delivery_total // max(people, 1) if delivery_total else 0),
        "currency": "CNY",
    }


# ═══════════════════════════════════════════════════════════════
# 方案丰富
# ═══════════════════════════════════════════════════════════════

async def _enrich_plan(plan: dict, tool_logs: list[dict]) -> None:
    activity = plan.get("activity")
    restaurant = plan.get("restaurant")
    drink = plan.get("drink")

    # 路线
    if activity and restaurant:
        route_result = await _run_tool(
            "estimate_route", tool_logs,
            origin=activity.get("area", ""), destination=restaurant.get("area", ""),
        )
        if route_result and route_result.status == "ok" and route_result.data:
            plan["route"] = route_result.data[0]

    # 团购券
    deals = []
    for poi in [activity, restaurant, drink]:
        if poi:
            deal_result = await _run_tool("get_deals", tool_logs, poi_id=poi.get("id", ""))
            if deal_result and deal_result.status == "ok" and deal_result.data:
                deals.extend(deal_result.data)
    plan["deals"] = deals
