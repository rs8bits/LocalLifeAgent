"""Planner - 标签对齐 → 场所搜索 → 方案组合"""

from datetime import datetime
from typing import Any, Optional

from backend.agent.schemas import Intent, PlannerOutput
from backend.agent.intent_parser import parse_intent
from backend.agent.tag_resolver import resolve_domain_tags
from backend.agent.plan_composer import compose_plan_specs_with_llm
from backend.agent.scorer import score_plan
from backend.agent.time_utils import infer_time_window_from_clock
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
                intent=intent,
            )
            result = await _run_place_search_with_relaxation(_run_tool, tool_logs, domain_name, params)

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
    _apply_multi_meal_constraints_to_plans(fallback_plans, intent, restaurants)
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
    _apply_multi_meal_constraints_to_plans(plans, intent, restaurants)
    _attach_delivery_to_plans(plans, delivery_items, intent)

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


async def _run_place_search_with_relaxation(
    runner,
    tool_logs: list[dict],
    domain_name: str,
    params: dict[str, Any],
) -> Any:
    """搜索无结果时逐步放宽软过滤，避免组合行程被过窄标签打空。"""
    result = await runner("search_places", tool_logs, **params)
    if _has_tool_data(result):
        return result

    attempts = _relaxed_place_search_params(domain_name, params)
    for relaxed_params, reason in attempts:
        retry = await runner("search_places", tool_logs, **relaxed_params)
        if _has_tool_data(retry):
            retry.error = _join_warnings(retry.error, reason)
            _annotate_latest_tool_log(tool_logs, reason)
            return retry
    return result


def _has_tool_data(result: Any) -> bool:
    return bool(result and result.status == "ok" and result.data)


def _annotate_latest_tool_log(tool_logs: list[dict], reason: str) -> None:
    if not tool_logs:
        return
    latest = tool_logs[-1]
    latest["detail"] = _join_warnings(latest.get("detail"), reason)
    latest["message"] = f"{latest.get('message', '')} | relaxed={reason}"


def _relaxed_place_search_params(
    domain_name: str,
    params: dict[str, Any],
) -> list[tuple[dict[str, Any], str]]:
    attempts: list[tuple[dict[str, Any], str]] = []
    seen: set[tuple] = set()
    base_normalized = _clean_search_params(params)

    def add(candidate: dict[str, Any], reason: str) -> None:
        normalized = _clean_search_params(candidate)
        signature = tuple(sorted((k, _hashable_value(v)) for k, v in normalized.items()))
        if signature not in seen and normalized != base_normalized:
            seen.add(signature)
            attempts.append((normalized, reason))

    def with_radius_variants(base: dict[str, Any], reason: str) -> None:
        for radius in _expanded_radius_values(base.get("radius_km")):
            candidate = dict(base)
            candidate["radius_km"] = radius
            add(candidate, f"{reason}，扩大搜索半径至{radius:g}km")

    # 先保留 tags_any，优先放宽更容易误伤召回的软条件。
    with_radius_variants(params, "首次搜索无结果")

    if domain_name == "play" and params.get("indoor") is not None:
        without_indoor = dict(params)
        without_indoor.pop("indoor", None)
        add(without_indoor, "首次搜索无结果，已放宽室内外条件")
        with_radius_variants(without_indoor, "首次搜索无结果，已放宽室内外条件")

    if domain_name == "eat" and params.get("max_queue_minutes") is not None:
        without_queue = dict(params)
        without_queue.pop("max_queue_minutes", None)
        add(without_queue, "首次搜索无结果，已放宽排队时长条件")
        with_radius_variants(without_queue, "首次搜索无结果，已放宽排队时长条件")

    # 部分泛化行程的 mock 数据没有细分 party_types，画像应晚于半径/天气偏好再放宽。
    if params.get("party_type"):
        without_party = dict(params)
        without_party.pop("party_type", None)
        add(without_party, "首次搜索无结果，已放宽同行人画像条件")
        with_radius_variants(without_party, "首次搜索无结果，已放宽同行人画像条件")

        if domain_name == "play" and without_party.get("indoor") is not None:
            without_party_indoor = dict(without_party)
            without_party_indoor.pop("indoor", None)
            add(without_party_indoor, "首次搜索无结果，已放宽同行人画像与室内外条件")
            with_radius_variants(without_party_indoor, "首次搜索无结果，已放宽同行人画像与室内外条件")

        if domain_name == "eat" and without_party.get("max_queue_minutes") is not None:
            without_party_queue = dict(without_party)
            without_party_queue.pop("max_queue_minutes", None)
            add(without_party_queue, "首次搜索无结果，已放宽同行人画像与排队条件")
            with_radius_variants(without_party_queue, "首次搜索无结果，已放宽同行人画像与排队条件")

    # tags_any 是召回线索，最后才整体移除，避免一开始就丢掉意图标签。
    soft_keys = {"tag", "tags_any", "tags_all", "category", "categories_any", "sub_category"}
    without_tags = {k: v for k, v in params.items() if k not in soft_keys}
    add(without_tags, "首次搜索无结果，已放宽标签/类目条件")
    with_radius_variants(without_tags, "首次搜索无结果，已放宽标签/类目条件")

    if domain_name == "play" and without_tags.get("indoor") is not None:
        without_tags_indoor = dict(without_tags)
        without_tags_indoor.pop("indoor", None)
        add(without_tags_indoor, "首次搜索无结果，已放宽标签/类目与室内外条件")
        with_radius_variants(without_tags_indoor, "首次搜索无结果，已放宽标签/类目与室内外条件")

    if without_tags.get("party_type"):
        without_tags_party = dict(without_tags)
        without_tags_party.pop("party_type", None)
        add(without_tags_party, "首次搜索无结果，已放宽标签/类目与同行人画像条件")
        with_radius_variants(without_tags_party, "首次搜索无结果，已放宽标签/类目与同行人画像条件")
    return attempts


def _hashable_value(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, dict):
        return tuple(sorted(value.items()))
    return value


def _clean_search_params(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None and v != []}


def _expanded_radius_values(current: Any) -> list[float]:
    if current is None:
        return []
    try:
        current_float = float(current)
    except (TypeError, ValueError):
        return []
    return [radius for radius in (5.0, 10.0, 15.0, 20.0) if radius > current_float]


def _join_warnings(*warnings: str | None) -> str | None:
    values = [w for w in warnings if w]
    if not values:
        return None
    return "; ".join(values)


def _format_tool_query(params: dict[str, Any]) -> str:
    keys = [
        "domain", "party_type", "radius_km", "indoor", "available", "max_queue_minutes",
        "category", "categories_any", "sub_category", "tags_any", "tags_all",
    ]
    parts = []
    for key in keys:
        value = params.get(key)
        if value is not None and value != "" and value != []:
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


def _apply_domain_spec_filters(params: dict[str, Any], spec: dict, intent: Intent | None = None) -> None:
    categories = spec.get("categories") or []
    tags = spec.get("tags") or []
    sub_categories = spec.get("sub_categories") or []
    domain_name = spec.get("domain", "")
    tag_signals = [*categories, *tags, *sub_categories]
    if intent is not None:
        tag_signals.extend(_intent_recall_tags(domain_name, intent))
    if tag_signals:
        params["tags_any"] = _unique_values(tag_signals)


_COMMON_INTENT_TAG_ALIASES = {
    "爸妈": ["长辈友好", "少走路", "安静"],
    "父母": ["长辈友好", "少走路", "安静"],
    "爸爸": ["长辈友好", "少走路", "安静"],
    "妈妈": ["长辈友好", "少走路", "安静"],
    "老人": ["长辈友好", "少走路", "安静"],
    "长辈": ["长辈友好", "少走路", "安静"],
    "sightseeing": ["历史文化", "散步", "展览"],
    "观光": ["历史文化", "散步", "展览"],
}

_DOMAIN_INTENT_TAG_ALIASES = {
    "play": {
        "游玩": ["散步", "展览", "公园", "商场", "历史文化"],
        "逛逛": ["散步", "公园", "商场", "历史文化"],
        "逛街": ["商场", "购物"],
        "购物": ["商场", "购物"],
        "来我的城市": ["散步", "历史文化", "展览"],
        "带他们逛": ["散步", "历史文化", "展览"],
    },
    "eat": {
        "清淡": ["清淡", "健康", "中餐"],
        "健康": ["健康", "健康轻食", "低卡"],
        "低卡": ["低卡", "轻食", "健康轻食"],
        "聚餐": ["聚会", "中餐"],
    },
    "drink": {
        "喝茶": ["茶饮", "安静"],
        "茶": ["茶饮", "安静"],
        "休息": ["安静", "茶饮"],
    },
}


def _intent_recall_tags(domain_name: str, intent: Intent) -> list[str]:
    signals: list[str] = []
    raw_values = list(intent.tags)
    if domain_name == "play":
        raw_values.extend(intent.activity_preferences)
    elif domain_name == "eat":
        raw_values.extend(intent.food_preferences)
    elif domain_name == "drink":
        raw_values.extend(intent.drink_preferences)

    if intent.party_type == "family_elder":
        raw_values.extend(["长辈友好", "少走路", "安静"])
    if intent.needs_less_walking:
        raw_values.extend(["少走路", "长辈友好"])
    if intent.needs_quiet:
        raw_values.append("安静")
    if intent.needs_photo_spot:
        raw_values.append("拍照")
    if domain_name == "eat" and intent.needs_low_calorie:
        raw_values.extend(["清淡", "健康", "低卡", "轻食"])

    for value in raw_values:
        if not value:
            continue
        signals.append(value)
        signals.extend(_COMMON_INTENT_TAG_ALIASES.get(value, []))
        signals.extend(_DOMAIN_INTENT_TAG_ALIASES.get(domain_name, {}).get(value, []))
    return signals


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
    intent: Intent | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "domain": domain_name,
        "radius_km": radius,
    }
    if party_type != "general":
        params["party_type"] = party_type
    _apply_domain_spec_filters(params, spec, intent)
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
        activities.sort(key=_friends_act_key(intent), reverse=True)
        restaurants.sort(key=_friends_rest_key(intent), reverse=True)

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
        s += _memory_match_score(a, intent) * 0.6
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
        s += _memory_match_score(r, intent) * 0.8
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
        s += _memory_match_score(a, intent) * 0.6
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
        s += _memory_match_score(r, intent) * 0.8
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
        s += _memory_match_score(a, intent) * 0.5
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
        s += _memory_match_score(r, intent) * 0.7
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


def _friends_act_key(intent: Intent):
    def key(a: dict) -> float:
        s = a.get("_match_score", 0) * 2.0
        s += _memory_match_score(a, intent) * 0.6
        tags = a.get("tags", [])
        if any(t in tags for t in ["社交", "聚会", "桌游", "拍照", "唱歌", "密室", "电竞", "音乐"]):
            s += 3.0
        s += a.get("rating", 0) * 0.2
        s -= a.get("distance_km", 0) * 0.1
        return s
    return key


def _friends_rest_key(intent: Intent):
    def key(r: dict) -> float:
        s = r.get("_match_score", 0) * 2.0
        s += _memory_match_score(r, intent) * 0.7
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
        s += _memory_match_score(d, intent) * 0.4
        prefs = intent.drink_preferences or []
        if "bar" in prefs and d.get("sub_category") == "bar":
            s += 5.0
        elif "coffee_tea" in prefs and d.get("sub_category") in ("coffee", "tea", "milk_tea"):
            s += 5.0
        s -= d.get("distance_km", 0) * 0.1
        s += d.get("rating", 0) * 0.1
        return s
    return key


def _memory_match_score(item: dict, intent: Intent) -> int:
    """长期偏好只影响排序，不参与硬过滤。"""
    if not item or not intent.memory_tags:
        return 0
    searchable = {
        str(value)
        for value in [
            item.get("name"),
            item.get("category"),
            item.get("sub_category"),
            item.get("cuisine"),
            *(item.get("tags") or []),
        ]
        if value
    }
    aliases = {
        "减脂": {"健康", "轻食", "低卡", "减脂", "健康轻食", "沙拉"},
        "健康": {"健康", "轻食", "低卡", "健康轻食", "沙拉"},
        "美食": {"聚会", "特色", "高品质"},
    }
    score = 0
    for tag in intent.memory_tags:
        candidates = {tag, *aliases.get(tag, set())}
        if searchable.intersection(candidates):
            score += 1
    return score


# ═══════════════════════════════════════════════════════════════
# 时间感知方案构建
# ═══════════════════════════════════════════════════════════════

def _resolve_time_constraints(intent: Intent) -> tuple[str, int, str]:
    """根据意图确定开始时间、可用分钟数和实际排期时间段。"""
    window_starts = {
        "morning": "09:00",
        "lunch": "11:30",
        "afternoon": "13:30",
        "dinner": "17:30",
        "evening": "18:30",
        "night": "20:30",
        "unknown": "14:00",
    }
    multi_meal_slots = set(_required_meal_slots(intent))
    if {"lunch", "dinner"}.issubset(multi_meal_slots):
        start = intent.start_time or "11:30"
        start = _adjust_today_start_time(intent, start)
        hours = intent.duration_hours or 9
        return start, hours * 60, infer_time_window_from_clock(start)

    start = intent.start_time or window_starts.get(intent.time_window, "14:00")
    start = _adjust_today_start_time(intent, start)
    effective_window = infer_time_window_from_clock(start)
    default_hours = {
        "morning": 3,
        "lunch": 2,
        "afternoon": 6,
        "dinner": 3,
        "evening": 4,
        "night": 3,
        "unknown": 4,
    }
    hours = intent.duration_hours or default_hours.get(intent.time_window, 4)
    return start, hours * 60, effective_window


def _adjust_today_start_time(intent: Intent, start: str) -> str:
    """今天的非精确时间不排到已经过去的整点。"""
    if intent.date != "today" or intent.start_time:
        return start
    try:
        now = datetime.now()
        now_min = now.hour * 60 + now.minute
        start_min = _time_to_minutes(start)
    except Exception:
        return start
    if now_min <= start_min:
        return start
    if now_min >= 23 * 60:
        return start
    adjusted = ((now_min + 29) // 30) * 30
    return _minutes_to_time(adjusted)


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
_MEAL_SLOT_LABELS = {"lunch": "午餐", "dinner": "晚餐"}
_MEAL_SLOT_DEFAULT_TIMES = {"lunch": "11:30", "dinner": "17:30"}
_MEAL_SLOT_WINDOWS = {
    "lunch": (10 * 60 + 30, 15 * 60),
    "dinner": (17 * 60, 21 * 60),
}
_MEAL_SLOT_IDEAL_WINDOWS = {
    "lunch": (11 * 60, 13 * 60 + 30),
    "dinner": (17 * 60, 20 * 60),
}


def _required_meal_slots(intent: Intent) -> list[str]:
    slots = [slot for slot in ["lunch", "dinner"] if slot in set(intent.meal_slots or [])]
    if slots:
        return slots
    if intent.time_window in {"lunch", "dinner"}:
        return [intent.time_window]
    return []


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
    start_min = _time_to_minutes(start_time)
    last_poi: dict | None = None

    if time_window in {"lunch", "dinner", "evening"}:
        slots = [
            ("restaurant", restaurant),
            ("drink", drink),
            ("activity", activity),
        ]
    elif time_window == "night":
        slots = [
            ("drink", drink),
            ("activity", activity),
            ("restaurant", restaurant),
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
        transit = _estimate_transit(last_poi, poi) if last_poi else 0
        candidate_min = current_min + transit

        # 检查营业时间
        if bh and not _is_within_business_hours(candidate_min, bh):
            open_min = bh[0]
            day_start = (candidate_min // (24 * 60)) * 24 * 60
            next_open = day_start + open_min
            if next_open < candidate_min:
                next_open += 24 * 60
            if next_open - start_min <= budget_min:
                candidate_min = next_open

        # 可预约 POI：对齐 available_slots
        slots_avail = poi.get("available_slots", [])
        if poi.get("bookable") and slots_avail:
            aligned = _align_to_slot(candidate_min, slots_avail)
            if aligned is not None and aligned >= candidate_min:
                candidate_min = aligned

        # 再次检查营业时间（对齐后）
        if bh and not _is_within_business_hours(candidate_min, bh):
            continue  # skip if still outside

        # 预算检查：确保剩余时间够最低时长
        elapsed = candidate_min - start_min
        remaining = budget_min - elapsed
        if remaining < min_dur:
            continue

        if (
            slot_type == "restaurant"
            and time_window == "afternoon"
            and budget_min >= 4 * 60
            and candidate_min < _time_to_minutes("17:30")
        ):
            dinner_min = _time_to_minutes("17:30")
            if budget_min - (dinner_min - start_min) >= min_dur:
                candidate_min = dinner_min
                remaining = budget_min - (candidate_min - start_min)

        dur = min(dur, max(remaining, min_dur))

        if transit:
            timeline.append({
                "time": _minutes_to_time(current_min),
                "type": "transit",
                "title": f"前往 {poi.get('name', '')}",
                "poi_id": "",
                "duration_min": transit,
            })

        current_min = candidate_min
        timeline.append({
            "time": _minutes_to_time(current_min),
            "type": slot_type,
            "title": poi.get("name", ""),
            "poi_id": poi.get("id", ""),
            "duration_min": dur,
        })
        current_min += dur
        last_poi = poi

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

    # 时间线
    start_time, budget_min, effective_window = _resolve_time_constraints(intent)
    timeline = _schedule_slots(start_time, budget_min, activity, drink, restaurant, effective_window)
    if (
        restaurant
        and drink
        and not intent.drink_preferences
        and not any(item.get("type") == "restaurant" for item in timeline)
    ):
        drink = None
        timeline = _schedule_slots(start_time, budget_min, activity, drink, restaurant, effective_window)

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
        if drink.get("sub_category") == "bar" and intent.time_window in ("morning", "lunch", "afternoon"):
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
        "meal_restaurants": [],
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
    for item in delivery_items:
        targets = _delivery_targets_for_item(item, plan)
        target = next((candidate for candidate in targets if _delivery_supports_target(item, candidate)), None)
        if target:
            return item, target
    return None, {}


def _delivery_targets_for_item(item: dict, plan: dict) -> list[dict]:
    restaurants = _plan_restaurants(plan)
    activity = plan.get("activity") or {}
    drink = plan.get("drink") or {}
    tags = set(item.get("tags") or [])
    if item.get("sub_category") == "drink" or tags.intersection({"奶茶", "果茶", "低糖"}):
        return [target for target in [activity, *restaurants, drink] if target]
    return [target for target in [*restaurants, activity, drink] if target]


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
        delivery_time = "18:00" if intent.time_window in {"dinner", "evening", "night"} else "15:30"
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
            "meal_restaurants": [],
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


def _inject_revision_locked_candidates(
    activities: list[dict],
    restaurants: list[dict],
    drinks: list[dict],
    delivery_items: list[dict],
    revision_patch: dict[str, Any] | None,
) -> None:
    """把上一轮被锁定的 POI 放回候选集，避免本轮搜索条件把它过滤掉。"""
    if not revision_patch:
        return
    target_lists = {
        "activity": activities,
        "restaurant": restaurants,
        "drink": drinks,
        "delivery": delivery_items,
    }
    for slot_info in (revision_patch.get("locked_slots") or {}).values():
        if not isinstance(slot_info, dict):
            continue
        domain = slot_info.get("domain")
        item = slot_info.get("item") or {}
        target = target_lists.get(domain)
        if target is None or not item.get("id"):
            continue
        locked_item = dict(item)
        locked_item["_revision_locked"] = True
        locked_item["_match_score"] = int(locked_item.get("_match_score") or 0) + 20
        _prepend_unique_item(target, locked_item)


def _prepend_unique_item(items: list[dict], item: dict) -> None:
    item_id = item.get("id")
    if not item_id:
        return
    items[:] = [candidate for candidate in items if candidate.get("id") != item_id]
    items.insert(0, item)


def _apply_revision_constraints_to_plans(
    plans: list[dict],
    intent: Intent,
    revision_patch: dict[str, Any] | None,
) -> None:
    """把 revision patch 的锁定/删除槽位强制应用到候选方案。"""
    if not revision_patch or not plans:
        return
    locked_slots = revision_patch.get("locked_slots") or {}
    remove_slots = set(revision_patch.get("remove_slots") or [])
    for plan in plans:
        changed = False
        if "activity" in remove_slots:
            changed = _remove_plan_slot(plan, "activity") or changed
        elif locked_slots.get("activity"):
            changed = _apply_locked_single_slot(plan, "activity", locked_slots["activity"], intent) or changed

        if "drink" in remove_slots:
            changed = _remove_plan_slot(plan, "drink") or changed
        elif locked_slots.get("drink"):
            changed = _apply_locked_single_slot(plan, "drink", locked_slots["drink"], intent) or changed

        meal_changed = _apply_locked_meal_slots(plan, intent, locked_slots, remove_slots)
        changed = changed or meal_changed
        if changed:
            plan["actions"] = []
            _recalculate_budget(plan, intent)


def _apply_locked_single_slot(
    plan: dict,
    slot: str,
    slot_info: dict[str, Any],
    intent: Intent,
) -> bool:
    item = slot_info.get("item") or {}
    if not item.get("id"):
        return False
    previous_id = (plan.get(slot) or {}).get("id")
    had_timeline_item = _timeline_has_item(plan, slot, item.get("id"))
    plan[slot] = item
    _ensure_timeline_item(
        plan,
        slot,
        item,
        slot_info.get("time") or _timeline_time_for(plan, slot) or _default_locked_time(slot, intent),
    )
    reason = f"已保留上一轮{_slot_label(slot)}"
    if reason not in plan.setdefault("recommend_reasons", []):
        plan["recommend_reasons"].append(reason)
    return previous_id != item.get("id") or not had_timeline_item


def _apply_locked_meal_slots(
    plan: dict,
    intent: Intent,
    locked_slots: dict[str, Any],
    remove_slots: set[str],
) -> bool:
    meal_locks = {
        slot.split(":", 1)[1]: info
        for slot, info in locked_slots.items()
        if slot.startswith("meal:") and slot not in remove_slots
    }
    if not meal_locks:
        return False

    assignments = _current_meal_assignments(plan)
    original_ids = {
        meal: (restaurant or {}).get("id")
        for meal, restaurant in assignments.items()
    }
    for meal, info in meal_locks.items():
        restaurant = info.get("item") or {}
        if restaurant.get("id"):
            assignments[meal] = restaurant

    for slot in remove_slots:
        if slot.startswith("meal:"):
            assignments.pop(slot.split(":", 1)[1], None)

    if not assignments:
        return False

    required_slots = _required_meal_slots(intent)
    for meal in assignments:
        if meal not in required_slots:
            intent.meal_slots = _ordered_meal_slots([*(intent.meal_slots or []), meal])
    _write_meal_assignments(plan, intent, assignments)
    for meal in meal_locks:
        reason = f"已保留上一轮{_MEAL_SLOT_LABELS.get(meal, meal)}"
        if reason not in plan.setdefault("recommend_reasons", []):
            plan["recommend_reasons"].append(reason)
    return original_ids != {
        meal: restaurant.get("id")
        for meal, restaurant in assignments.items()
    }


def _current_meal_assignments(plan: dict) -> dict[str, dict]:
    assignments: dict[str, dict] = {}
    for entry in plan.get("meal_restaurants") or []:
        if not isinstance(entry, dict):
            continue
        meal = entry.get("meal")
        restaurant = entry.get("restaurant")
        if meal in {"lunch", "dinner"} and restaurant:
            assignments[meal] = restaurant
    restaurant = plan.get("restaurant")
    if restaurant and not assignments:
        slot = _meal_slot_for_time(_timeline_time_for(plan, "restaurant")) or "dinner"
        assignments[slot] = restaurant
    return assignments


def _remove_plan_slot(plan: dict, slot: str) -> bool:
    changed = bool(plan.get(slot))
    plan[slot] = None
    plan["timeline"] = [
        item for item in (plan.get("timeline") or [])
        if item.get("type") != slot
    ]
    return changed


def _ensure_timeline_item(plan: dict, slot: str, item: dict, time_value: str) -> None:
    timeline = [
        entry for entry in (plan.get("timeline") or [])
        if not (entry.get("type") == slot and entry.get("poi_id") == item.get("id"))
    ]
    timeline.append({
        "time": time_value,
        "type": slot,
        "title": item.get("name", ""),
        "poi_id": item.get("id", ""),
        "duration_min": item.get("recommended_duration_min", _default_duration(slot)),
    })
    plan["timeline"] = _sort_timeline(timeline)


def _timeline_has_item(plan: dict, slot: str, poi_id: str | None) -> bool:
    return any(
        item.get("type") == slot and item.get("poi_id") == poi_id
        for item in plan.get("timeline") or []
    )


def _default_locked_time(slot: str, intent: Intent) -> str:
    if slot == "activity":
        return "14:00" if intent.time_window not in {"morning"} else "10:00"
    if slot == "drink":
        return "20:00" if "bar" in intent.drink_preferences else "16:00"
    return "14:00"


def _slot_label(slot: str) -> str:
    return {"activity": "活动", "drink": "饮品"}.get(slot, slot)


def _ordered_meal_slots(values: list[str]) -> list[str]:
    return [slot for slot in ["lunch", "dinner"] if slot in set(values)]


def _apply_multi_meal_constraints_to_plans(
    plans: list[dict],
    intent: Intent,
    restaurants: list[dict],
) -> None:
    """用户明确要午餐+晚餐时，把两顿饭拆成独立槽位并尽量使用不同餐厅/菜系。"""
    meal_slots = _required_meal_slots(intent)
    if len(meal_slots) < 2 or not plans:
        return
    candidates = [r for r in restaurants if r and r.get("meal_suitable") is not False]
    if not candidates:
        return

    for index, plan in enumerate(plans):
        assignments = _select_meal_assignments(plan, intent, candidates, meal_slots, index)
        if not assignments:
            continue
        _write_meal_assignments(plan, intent, assignments)


def _select_meal_assignments(
    plan: dict,
    intent: Intent,
    candidates: list[dict],
    meal_slots: list[str],
    plan_index: int,
) -> dict[str, dict]:
    id_map = {r.get("id"): r for r in candidates if r.get("id")}
    existing_by_slot = _existing_meal_restaurants_by_slot(plan, id_map, meal_slots)
    assignments: dict[str, dict] = {}
    used_ids: set[str] = set()
    used_categories: set[str] = set()

    for slot in meal_slots:
        restaurant = existing_by_slot.get(slot)
        if not restaurant or restaurant.get("id") in used_ids:
            restaurant = _pick_restaurant_for_meal(
                candidates=candidates,
                intent=intent,
                slot=slot,
                used_ids=used_ids,
                used_categories=used_categories,
                offset=plan_index,
            )
        if restaurant:
            assignments[slot] = restaurant
            if restaurant.get("id"):
                used_ids.add(restaurant["id"])
            if restaurant.get("category"):
                used_categories.add(restaurant["category"])

    return assignments


def _existing_meal_restaurants_by_slot(
    plan: dict,
    id_map: dict[str, dict],
    meal_slots: list[str],
) -> dict[str, dict]:
    existing: dict[str, dict] = {}
    restaurant_items = [
        item for item in _sort_timeline(plan.get("timeline") or [])
        if item.get("type") == "restaurant"
    ]
    for order, item in enumerate(restaurant_items):
        ref_id = item.get("poi_id") or item.get("ref_id")
        restaurant = id_map.get(ref_id)
        if not restaurant:
            continue
        slot = _meal_slot_for_time(item.get("time")) or (
            meal_slots[order] if order < len(meal_slots) else None
        )
        if slot in meal_slots and slot not in existing:
            existing[slot] = restaurant

    legacy_restaurant = plan.get("restaurant") or {}
    legacy_id = legacy_restaurant.get("id")
    if meal_slots and meal_slots[0] not in existing and legacy_id in id_map:
        existing[meal_slots[0]] = id_map[legacy_id]
    return existing


def _pick_restaurant_for_meal(
    *,
    candidates: list[dict],
    intent: Intent,
    slot: str,
    used_ids: set[str],
    used_categories: set[str],
    offset: int,
) -> dict | None:
    available = [r for r in candidates if r.get("id") not in used_ids]
    if not available:
        available = candidates
    ranked = sorted(
        available,
        key=lambda r: _meal_restaurant_key(r, intent, slot, used_categories),
        reverse=True,
    )
    if not ranked:
        return None
    return ranked[offset % len(ranked)]


def _meal_restaurant_key(
    restaurant: dict,
    intent: Intent,
    slot: str,
    used_categories: set[str],
) -> float:
    score = float(restaurant.get("_match_score") or 0) * 3.0
    score += _memory_match_score(restaurant, intent) * 0.9
    if restaurant.get("available"):
        score += 2.0
    if restaurant.get("bookable"):
        score += 1.0
    score += float(restaurant.get("rating") or 0) * 0.25
    score += _meal_slot_fit_score(restaurant, slot)
    category = restaurant.get("category")
    if category and category not in used_categories:
        score += 3.0
    elif category:
        score -= 4.0
    if intent.budget_per_person and restaurant.get("avg_price", 0) <= intent.budget_per_person:
        score += 0.8
    score -= float(restaurant.get("distance_km") or 0) * 0.08
    score -= float(restaurant.get("queue_minutes") or 0) * 0.015
    return score


def _meal_slot_fit_score(restaurant: dict, slot: str) -> float:
    slots = restaurant.get("available_slots") or []
    window = _MEAL_SLOT_WINDOWS.get(slot)
    if window and slots:
        for value in slots:
            try:
                minute = _time_to_minutes(value)
            except ValueError:
                continue
            if window[0] <= minute <= window[1]:
                return 2.0
    preferred = _MEAL_SLOT_DEFAULT_TIMES.get(slot)
    if preferred:
        bh = _parse_business_hours(restaurant.get("business_hours"))
        if bh and _is_within_business_hours(_time_to_minutes(preferred), bh):
            return 1.0
    return 0.0


def _write_meal_assignments(
    plan: dict,
    intent: Intent,
    assignments: dict[str, dict],
) -> None:
    existing_times = _existing_meal_times(plan)
    meal_entries: list[dict] = []
    for slot in _required_meal_slots(intent):
        restaurant = assignments.get(slot)
        if not restaurant:
            continue
        time = _meal_time_for_restaurant(slot, restaurant, existing_times.get(slot))
        meal_entries.append({
            "meal": slot,
            "label": _MEAL_SLOT_LABELS.get(slot, slot),
            "time": time,
            "restaurant": restaurant,
        })
    if not meal_entries:
        return

    plan["meal_restaurants"] = meal_entries
    plan["restaurant"] = meal_entries[0]["restaurant"]
    plan["timeline"] = _timeline_with_meal_entries(plan, meal_entries)
    plan["actions"] = [
        action for action in (plan.get("actions") or [])
        if action.get("type") != "book_restaurant"
    ]
    _refresh_multi_meal_title(plan, intent, meal_entries)
    _refresh_multi_meal_reasons_and_risks(plan, meal_entries)
    _refresh_plan_queue_and_status(plan)
    _recalculate_budget(plan, intent)


def _existing_meal_times(plan: dict) -> dict[str, str]:
    times: dict[str, str] = {}
    restaurant_items = [
        item for item in _sort_timeline(plan.get("timeline") or [])
        if item.get("type") == "restaurant"
    ]
    fallback_slots = ["lunch", "dinner"]
    for order, item in enumerate(restaurant_items):
        slot = _meal_slot_for_time(item.get("time"))
        if not slot and order < len(fallback_slots):
            slot = fallback_slots[order]
        if slot and slot not in times:
            times[slot] = item.get("time") or _MEAL_SLOT_DEFAULT_TIMES.get(slot, "")
    return times


def _meal_slot_for_time(time_value: str | None) -> str | None:
    if not time_value:
        return None
    try:
        minute = _time_to_minutes(time_value)
    except ValueError:
        return None
    if _MEAL_SLOT_WINDOWS["lunch"][0] <= minute <= _MEAL_SLOT_WINDOWS["lunch"][1]:
        return "lunch"
    if _MEAL_SLOT_WINDOWS["dinner"][0] <= minute <= _MEAL_SLOT_WINDOWS["dinner"][1]:
        return "dinner"
    return None


def _meal_time_for_restaurant(
    slot: str,
    restaurant: dict,
    existing_time: str | None,
) -> str:
    ideal_window = _MEAL_SLOT_IDEAL_WINDOWS.get(slot)
    if existing_time and ideal_window and _time_between(existing_time, ideal_window[0], ideal_window[1]):
        return existing_time
    preferred = _MEAL_SLOT_DEFAULT_TIMES.get(slot, "12:00")
    window = ideal_window or _MEAL_SLOT_WINDOWS.get(slot)
    valid_slots = []
    for value in restaurant.get("available_slots") or []:
        try:
            minute = _time_to_minutes(value)
        except ValueError:
            continue
        if not window or window[0] <= minute <= window[1]:
            valid_slots.append(value)
    if valid_slots:
        after_preferred = [value for value in valid_slots if value >= preferred]
        return min(after_preferred) if after_preferred else min(valid_slots)
    return preferred


def _timeline_with_meal_entries(plan: dict, meal_entries: list[dict]) -> list[dict]:
    original_timeline = plan.get("timeline") or []
    timeline = [
        item for item in original_timeline
        if item.get("type") == "delivery"
    ]
    for entry in meal_entries:
        restaurant = entry["restaurant"]
        timeline.append({
            "time": entry["time"],
            "type": "restaurant",
            "title": f"{entry['label']}：{restaurant.get('name', '')}",
            "poi_id": restaurant.get("id", ""),
            "duration_min": restaurant.get("recommended_duration_min", 90),
        })
    activity = plan.get("activity")
    if activity:
        original_activity = _first_timeline_item(original_timeline, "activity")
        activity_time, activity_duration = _activity_slot_between_meals(activity, meal_entries, original_activity)
        timeline.append({
            "time": activity_time,
            "type": "activity",
            "title": activity.get("name", ""),
            "poi_id": activity.get("id", ""),
            "duration_min": activity_duration,
        })
    drink = plan.get("drink")
    if drink:
        original_drink = _first_timeline_item(original_timeline, "drink")
        drink_time, drink_duration = _drink_slot_after_dinner(drink, meal_entries, original_drink)
        timeline.append({
            "time": drink_time,
            "type": "drink",
            "title": drink.get("name", ""),
            "poi_id": drink.get("id", ""),
            "duration_min": drink_duration,
        })
    return _insert_transits(_sort_timeline(timeline), _timeline_poi_map(plan, meal_entries))


def _first_timeline_item(timeline: list[dict], slot_type: str) -> dict | None:
    return next((item for item in timeline if item.get("type") == slot_type), None)


def _activity_slot_between_meals(
    activity: dict,
    meal_entries: list[dict],
    original_item: dict | None,
) -> tuple[str, int]:
    lunch = next((entry for entry in meal_entries if entry.get("meal") == "lunch"), None)
    dinner = next((entry for entry in meal_entries if entry.get("meal") == "dinner"), None)
    rec_duration = int(activity.get("recommended_duration_min") or _default_duration("activity"))
    if not lunch or not dinner:
        return (original_item or {}).get("time") or "14:00", rec_duration

    lunch_restaurant = lunch["restaurant"]
    dinner_restaurant = dinner["restaurant"]
    lunch_end = _time_to_minutes(lunch["time"]) + int(lunch_restaurant.get("recommended_duration_min", 75))
    dinner_start = _time_to_minutes(dinner["time"])
    earliest = _round_up_to_half_hour(lunch_end + _estimate_transit(lunch_restaurant, activity))
    latest_start = max(earliest, dinner_start - _estimate_transit(activity, dinner_restaurant) - rec_duration)
    original_time = (original_item or {}).get("time")
    if original_time and _time_between(original_time, earliest, dinner_start):
        start_min = _time_to_minutes(original_time)
    else:
        start_min = _choose_slot_between(activity.get("available_slots") or [], earliest, latest_start) or earliest
    latest_end = max(start_min + 60, dinner_start - _estimate_transit(activity, dinner_restaurant))
    duration = min(rec_duration, max(60, latest_end - start_min))
    return _minutes_to_time(start_min), duration


def _drink_slot_after_dinner(
    drink: dict,
    meal_entries: list[dict],
    original_item: dict | None,
) -> tuple[str, int]:
    dinner = next((entry for entry in meal_entries if entry.get("meal") == "dinner"), None)
    rec_duration = int(drink.get("recommended_duration_min") or _default_duration("drink"))
    if not dinner:
        return (original_item or {}).get("time") or "20:00", rec_duration

    dinner_restaurant = dinner["restaurant"]
    dinner_end = _time_to_minutes(dinner["time"]) + int(dinner_restaurant.get("recommended_duration_min", 75))
    earliest = _round_up_to_half_hour(dinner_end + _estimate_transit(dinner_restaurant, drink))
    original_time = (original_item or {}).get("time")
    if original_time:
        try:
            original_min = _time_to_minutes(original_time)
        except ValueError:
            original_min = 0
        if original_min >= earliest:
            return original_time, rec_duration
    start_min = _choose_slot_between(drink.get("available_slots") or [], earliest, 23 * 60) or earliest
    return _minutes_to_time(start_min), rec_duration


def _choose_slot_between(available_slots: list[str], earliest: int, latest: int) -> int | None:
    candidates = []
    day_start = (earliest // (24 * 60)) * 24 * 60
    for slot in available_slots:
        try:
            minute = day_start + _time_to_minutes(slot)
        except ValueError:
            continue
        if earliest <= minute <= latest:
            candidates.append(minute)
    return min(candidates) if candidates else None


def _time_between(time_value: str, start_min: int, end_min: int) -> bool:
    try:
        minute = _time_to_minutes(time_value)
    except ValueError:
        return False
    return start_min <= minute <= end_min


def _round_up_to_half_hour(minute: int) -> int:
    return ((minute + 29) // 30) * 30


def _timeline_poi_map(plan: dict, meal_entries: list[dict]) -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for key in ["activity", "drink"]:
        item = plan.get(key)
        if item and item.get("id"):
            mapping[item["id"]] = item
    for entry in meal_entries:
        restaurant = entry.get("restaurant") or {}
        if restaurant.get("id"):
            mapping[restaurant["id"]] = restaurant
    for item in plan.get("delivery_items") or []:
        if item.get("id"):
            mapping[item["id"]] = item
    return mapping


def _insert_transits(timeline: list[dict], poi_map: dict[str, dict]) -> list[dict]:
    if not timeline:
        return []
    result: list[dict] = []
    travel_items = [item for item in timeline if item.get("type") != "delivery"]
    travel_ids = {id(item) for item in travel_items}
    for index, item in enumerate(timeline):
        result.append(item)
        if id(item) not in travel_ids:
            continue
        next_item = next(
            (candidate for candidate in timeline[index + 1:] if candidate.get("type") != "delivery"),
            None,
        )
        if not next_item:
            continue
        current_poi = poi_map.get(item.get("poi_id"))
        next_poi = poi_map.get(next_item.get("poi_id"))
        if not current_poi or not next_poi:
            continue
        try:
            end_time = _minutes_to_time(_time_to_minutes(item.get("time")) + int(item.get("duration_min") or 0))
        except (TypeError, ValueError):
            continue
        result.append({
            "time": end_time,
            "type": "transit",
            "title": f"前往 {next_item.get('title', '')}",
            "poi_id": "",
            "duration_min": _estimate_transit(current_poi, next_poi),
        })
    return result


def _refresh_multi_meal_title(plan: dict, intent: Intent, meal_entries: list[dict]) -> None:
    parts: list[str] = []
    activity = plan.get("activity")
    drink = plan.get("drink")
    if activity:
        parts.append(str(activity.get("name", "")))
    for entry in meal_entries:
        restaurant = entry["restaurant"]
        meal_label = entry.get("label", "")
        category = restaurant.get("category") or restaurant.get("name", "")
        parts.append(f"{meal_label}{category}")
    if drink:
        parts.append(str(drink.get("name", "")))
    prefix = _party_title_prefix(intent).replace("方案", "")
    plan["title"] = f"{prefix}方案：{' + '.join([p for p in parts if p])}"


def _refresh_multi_meal_reasons_and_risks(plan: dict, meal_entries: list[dict]) -> None:
    ids = [entry["restaurant"].get("id") for entry in meal_entries if entry.get("restaurant")]
    categories = [entry["restaurant"].get("category") for entry in meal_entries if entry.get("restaurant")]
    reasons = plan.setdefault("recommend_reasons", [])
    risks = plan.setdefault("risk_tips", [])
    if len(set(ids)) == len(ids) and len(ids) >= 2:
        reason = "午餐和晚餐已安排不同餐厅"
        if reason not in reasons:
            reasons.append(reason)
    else:
        risk = "可用餐厅不足，午餐和晚餐可能重复同一家"
        if risk not in risks:
            risks.append(risk)
    if len(set(categories)) >= 2:
        reason = "两顿饭菜系不同，避免体验重复"
        if reason not in reasons:
            reasons.append(reason)
    for entry in meal_entries:
        restaurant = entry["restaurant"]
        label = entry.get("label", "餐厅")
        if restaurant.get("risk") and restaurant["risk"] not in risks:
            risks.append(restaurant["risk"])
        if restaurant.get("queue_minutes", 0) > 30:
            tip = f"{label}「{restaurant.get('name', '')}」排队约{restaurant['queue_minutes']}分钟"
            if tip not in risks:
                risks.append(tip)
        slots = restaurant.get("available_slots") or []
        if restaurant.get("bookable") and slots and entry.get("time") not in slots:
            next_slot = _next_available_slot_text(entry.get("time"), slots)
            tip = f"{label}「{restaurant.get('name', '')}」{entry.get('time')}暂无预约位"
            if next_slot:
                tip += f"，最近可约 {next_slot}"
            if tip not in risks:
                risks.append(tip)


def _next_available_slot_text(preferred_time: str | None, slots: list[str]) -> str | None:
    if not preferred_time or not slots:
        return None
    after = [slot for slot in slots if slot >= preferred_time]
    return min(after) if after else slots[0]


def _refresh_plan_queue_and_status(plan: dict) -> None:
    queue = 0
    for key in ["activity", "drink"]:
        if plan.get(key):
            queue += int(plan[key].get("queue_minutes") or 0)
    restaurants = _plan_restaurants(plan)
    queue += sum(int(r.get("queue_minutes") or 0) for r in restaurants)
    plan["queue_minutes"] = queue

    if any(not r.get("available", True) for r in restaurants):
        plan["booking_status"] = "unavailable"
    elif any(not r.get("bookable", True) for r in restaurants):
        plan["booking_status"] = "partial"


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


def _delivery_time_for_plan(plan: dict, item: dict) -> str:
    target_id = item.get("_delivery_target_ref_id")
    if target_id:
        target_time = next(
            (
                entry.get("time")
                for entry in plan.get("timeline") or []
                if entry.get("poi_id") == target_id
            ),
            None,
        )
        if target_time:
            if item.get("sub_category") == "drink" or "奶茶" in set(item.get("tags") or []):
                return _minutes_to_time(_time_to_minutes(target_time) + 45)
            return target_time
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
    meal_ref_ids = refs.get("meal_restaurant_ids") or {}
    meal_restaurants = [
        item for meal in ["lunch", "dinner"]
        if (item := _find_by_id(restaurants, meal_ref_ids.get(meal)))
    ]
    activity = _find_by_id(activities, refs.get("activity_id"))
    restaurant = _find_by_id(restaurants, refs.get("restaurant_id")) or (meal_restaurants[0] if meal_restaurants else None)
    drink = _find_by_id(drinks, refs.get("drink_id"))
    deliveries = [
        item for item_id in refs.get("delivery_item_ids", [])
        if (item := _find_by_id(delivery_items, item_id))
    ]

    base = _make_plan_with_timeline(index, intent, activity, restaurant, drink)
    if spec.get("title"):
        base["title"] = str(spec["title"])
    timeline = _timeline_from_spec(spec.get("timeline", []), activity, restaurants, drink, deliveries)
    if timeline:
        base["timeline"] = timeline
    if meal_restaurants:
        base["meal_restaurants"] = [
            {
                "meal": meal,
                "label": _MEAL_SLOT_LABELS.get(meal, meal),
                "time": "",
                "restaurant": restaurant_item,
            }
            for meal in ["lunch", "dinner"]
            if (restaurant_item := _find_by_id(restaurants, meal_ref_ids.get(meal)))
        ]
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
    restaurants: list[dict],
    drink: dict | None,
    delivery_items: list[dict],
) -> list[dict]:
    item_map = {}
    for item in [activity, drink, *restaurants, *delivery_items]:
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
    seen = {(a.get("type"), a.get("ref_id"), a.get("scheduled_time")) for a in existing}
    actions = list(existing)

    activity = plan.get("activity")
    activity_time = _timeline_time_for(plan, "activity") or "14:00"
    if activity and activity.get("bookable") and ("book_activity", activity.get("id"), activity_time) not in seen:
        actions.append({
            "action_id": f"book_{activity.get('id')}",
            "type": "book_activity",
            "ref_id": activity.get("id"),
            "scheduled_time": activity_time,
            "quantity": intent.people_count or 1,
            "target_ref_id": None,
        })
        seen.add(("book_activity", activity.get("id"), activity_time))

    meal_entries = plan.get("meal_restaurants") or []
    if meal_entries:
        for entry in meal_entries:
            restaurant = entry.get("restaurant") or {}
            scheduled_time = entry.get("time") or _timeline_time_for_restaurant_id(plan, restaurant.get("id")) or "17:30"
            signature = ("book_restaurant", restaurant.get("id"), scheduled_time)
            if (
                restaurant
                and restaurant.get("bookable")
                and restaurant.get("available")
                and signature not in seen
            ):
                actions.append({
                    "action_id": f"book_{entry.get('meal', 'meal')}_{restaurant.get('id')}",
                    "type": "book_restaurant",
                    "ref_id": restaurant.get("id"),
                    "scheduled_time": scheduled_time,
                    "quantity": intent.people_count or 1,
                    "target_ref_id": None,
                })
                seen.add(signature)
    else:
        restaurant = plan.get("restaurant")
        scheduled_time = _timeline_time_for(plan, "restaurant") or "17:30"
        if restaurant and restaurant.get("bookable") and restaurant.get("available") and ("book_restaurant", restaurant.get("id"), scheduled_time) not in seen:
            actions.append({
                "action_id": f"book_{restaurant.get('id')}",
                "type": "book_restaurant",
                "ref_id": restaurant.get("id"),
                "scheduled_time": scheduled_time,
                "quantity": intent.people_count or 1,
                "target_ref_id": None,
            })

    drink = plan.get("drink")
    drink_time = _timeline_time_for(plan, "drink") or "16:00"
    if drink and drink.get("bookable") and ("book_drink", drink.get("id"), drink_time) not in seen:
        actions.append({
            "action_id": f"book_{drink.get('id')}",
            "type": "book_drink",
            "ref_id": drink.get("id"),
            "scheduled_time": drink_time,
            "quantity": intent.people_count or 1,
            "target_ref_id": None,
        })
        seen.add(("book_drink", drink.get("id"), drink_time))

    for item in plan.get("delivery_items") or []:
        delivery_time = _timeline_time_for(plan, "delivery") or _delivery_time_for_plan(plan, item)
        if ("order_delivery", item.get("id"), delivery_time) in seen:
            continue
        target = (_plan_restaurants(plan) or [None])[0] or plan.get("activity") or plan.get("drink") or {}
        target_ref_id = item.get("_delivery_target_ref_id") or target.get("id")
        actions.append({
            "action_id": f"order_{item.get('id')}",
            "type": "order_delivery",
            "ref_id": item.get("id"),
            "scheduled_time": delivery_time,
            "quantity": 1,
            "target_ref_id": target_ref_id,
        })
        seen.add(("order_delivery", item.get("id"), delivery_time))

    for deal in plan.get("deals") or []:
        if ("order_deal", deal.get("id"), "") in seen:
            continue
        actions.append({
            "action_id": f"deal_{deal.get('id')}",
            "type": "order_deal",
            "ref_id": deal.get("id"),
            "scheduled_time": "",
            "quantity": 1,
            "target_ref_id": deal.get("poi_id"),
        })
        seen.add(("order_deal", deal.get("id"), ""))

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


def _timeline_time_for_restaurant_id(plan: dict, restaurant_id: str | None) -> str | None:
    if not restaurant_id:
        return None
    for item in plan.get("timeline") or []:
        if item.get("type") == "restaurant" and item.get("poi_id") == restaurant_id:
            return item.get("time")
    return None


def _sort_timeline(timeline: list[dict]) -> list[dict]:
    return sorted(timeline, key=lambda item: item.get("time") or "99:99")


def _recalculate_budget(plan: dict, intent: Intent) -> None:
    people = intent.people_count or _default_people_count(intent)
    per_person = 0
    for key in ["activity", "drink"]:
        if plan.get(key):
            per_person += plan[key].get("avg_price", 0)
    meal_restaurants = _plan_restaurants(plan)
    if meal_restaurants:
        per_person += sum(restaurant.get("avg_price", 0) for restaurant in meal_restaurants)
    elif plan.get("restaurant"):
        per_person += plan["restaurant"].get("avg_price", 0)
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
    restaurants = _plan_restaurants(plan)
    restaurant = restaurants[0] if restaurants else None
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
    seen_poi_ids: set[str] = set()
    for poi in [activity, *restaurants, drink]:
        if poi:
            if poi.get("id") in seen_poi_ids:
                continue
            seen_poi_ids.add(poi.get("id"))
            deal_result = await _run_tool("get_deals", tool_logs, poi_id=poi.get("id", ""))
            if deal_result and deal_result.status == "ok" and deal_result.data:
                deals.extend(deal_result.data)
    plan["deals"] = deals
