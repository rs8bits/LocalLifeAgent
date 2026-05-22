"""规划节点 - 标签对齐 → 场所搜索 → 方案组合"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.tools.registry import get_tool
from backend.agent.schemas import Intent
from backend.agent.tag_resolver import resolve_domain_tags
from backend.agent.plan_composer import compose_plan_specs_with_llm
from backend.agent.planner import (
    _build_diverse_plans,
    _build_delivery_only_plans,
    _attach_delivery_to_plans,
    _make_plan_from_composer_spec,
    _ensure_plan_actions,
    _enrich_plan,
    _indoor_preference,
    _resolve_mock_weather_date,
    _dedupe_by_id,
    _domain_spec_map,
    _build_place_search_params,
    _build_delivery_search_params,
    _has_child_context,
    _format_tool_query,
    _relax_place_search_params,
    _should_relax_place_search,
)
from backend.agent.scorer import score_plan


async def planner_node(state: AgentState) -> AgentState:
    """新流程：标签对齐 → 天气 → 场所搜索 → 方案组合"""
    tool_logs: list[dict] = []
    warnings: list[str] = []

    intent_dict = state.get("intent", {})
    intent = Intent(**intent_dict)

    # 如果是重试，从 guardrail_feedback 中提取需要排除的 POI ID
    excluded_poi_ids: set[str] = set()
    guardrail_feedback = state.get("guardrail_feedback", {})
    if guardrail_feedback and guardrail_feedback.get("retryable_issues"):
        is_retry = state.get("planner_retry_count", 0) > 0
    else:
        is_retry = False

    await emit_event(state, {
        "event": "planner_start",
        "message": "正在重新规划..." if is_retry else "开始规划...",
        "data": {"retry": is_retry},
    })

    # ── 1. 标签对齐 ──
    await emit_event(state, {"event": "tag_catalog_start", "message": "正在查询标签目录...", "data": {}})
    await emit_event(state, {"event": "tag_catalog_done", "message": "标签目录已加载", "data": {}})
    await emit_event(state, {"event": "tag_resolve_start", "message": "正在对齐用户意图与业务标签...", "data": {}})
    tag_result = await resolve_domain_tags(
        message=state.get("user_message", ""),
        intent=intent,
        intent_dict=intent_dict,
    )
    await emit_event(state, {
        "event": "tag_resolve_done",
        "message": f"标签对齐完成: domains={tag_result['domains']}",
        "data": tag_result,
    })
    state["tag_resolve_result"] = tag_result

    spec_by_domain = _domain_spec_map(tag_result)
    domains = list(spec_by_domain.keys())
    domain_required = tag_result.get("domain_required", {})

    # ── 2. 天气 ──
    await emit_event(state, {"event": "tool_start", "message": "查询天气...", "data": {"tool": "get_weather"}})
    weather_result = await _run_tool("get_weather", tool_logs,
        date=_resolve_mock_weather_date(intent.date), location="朝阳区")
    await emit_event(state, {"event": "tool_done", "message": tool_logs[-1]["message"],
                   "data": {"tool": "get_weather", "status": "ok"}})
    if weather_result and weather_result.status == "ok" and weather_result.data:
        state["weather"] = weather_result.data[0]

    indoor_pref = _indoor_preference(weather_result, intent)
    party_type = intent.party_type
    radius = intent.radius_km
    people = intent.people_count
    queue_limit = (intent.avoid_queue_minutes or 30) * 2

    # ── 3. 场所搜索 (按 domain) ──
    activities: list[dict] = []
    restaurants: list[dict] = []
    drinks: list[dict] = []
    delivery_items: list[dict] = []

    for domain_name in domains:
        await emit_event(state, {
            "event": "place_search_start",
            "message": f"正在搜索场所 ({domain_name})...",
            "data": {"domain": domain_name},
        })

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
            if _should_relax_place_search(result, params):
                relaxed_params = _relax_place_search_params(params)
                relaxed = await _run_tool("search_places", tool_logs, **relaxed_params)
                if relaxed and relaxed.status == "ok" and relaxed.data:
                    warnings.append(f"[{domain_name}] 严格标签/类目无结果，已按 party_type 放宽检索")
                    result = relaxed

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

            # 记录 tag 放宽警告
            if result.error:
                warnings.append(f"[{domain_name}] {result.error}")

        await emit_event(state, {
            "event": "place_search_done",
            "message": tool_logs[-1]["message"],
            "data": {"domain": domain_name, "count": len(result.data) if result and result.data else 0},
        })

    # eat fallback: 低卡需求
    if intent.needs_low_calorie and len(restaurants) < 2 and "eat" in domains:
        fallback = await _run_tool("search_places", tool_logs,
            domain="eat", party_type=party_type, radius_km=radius,
            party_size=people, available=True,
        )
        if fallback and fallback.status == "ok":
            restaurants = _dedupe_by_id(restaurants, fallback.data)

    state["candidate_activities"] = activities
    state["candidate_restaurants"] = restaurants
    state["candidate_drinks"] = drinks
    state["candidate_delivery_items"] = delivery_items

    # ── 4. 方案组合 ──
    await emit_event(state, {
        "event": "composer_start",
        "message": "正在组合候选并生成可执行动作 JSON...",
        "data": {},
    })
    fallback_plans = _build_diverse_plans(intent, activities, restaurants, drinks, tool_logs)
    if not fallback_plans and delivery_items:
        fallback_plans = _build_delivery_only_plans(intent, delivery_items)
    _attach_delivery_to_plans(fallback_plans, delivery_items, intent)
    llm_specs, composer_warning = await compose_plan_specs_with_llm(
        message=state.get("user_message", ""),
        intent=intent,
        user_memory=state.get("user_profile", {}),
        tag_result=tag_result,
        weather=state.get("weather"),
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
    await emit_event(state, {
        "event": "composer_done",
        "message": "方案组合完成" if llm_specs else "已使用本地规则组合方案",
        "data": {"llm_used": bool(llm_specs), "plans_count": len(plans)},
    })

    # 将搜索不到的领域信息写入 risk_tips；只有完全无方案时才作为 errors。
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
                state.setdefault("errors", []).append(f"未找到符合条件的{label_cn}")

    if not plans and not state.get("errors"):
        state.setdefault("errors", []).append("未生成候选方案")

    # 将 warnings 注入到第一个方案的 risk_tips
    if warnings and plans:
        for w in warnings:
            if w not in plans[0].get("risk_tips", []):
                plans[0].setdefault("risk_tips", []).append(w)

    # ── 5. 丰富方案 + 评分 ──
    for plan in plans:
        await _enrich_plan(plan, tool_logs)
        _ensure_plan_actions(plan, intent)
    for plan in plans:
        score_plan(plan, intent)
    plans.sort(key=lambda p: p.get("score", 0.0), reverse=True)

    # 输出 plan_delta
    for i, plan in enumerate(plans[:4]):
        await emit_event(state, {
            "event": "plan_delta",
            "message": f"方案{i + 1}: {plan.get('title', '')}",
            "data": {"plan": plan},
        })

    state["plans"] = plans[:4]
    state["tool_logs"] = tool_logs

    return state


async def _run_tool(name: str, tool_logs: list[dict], **kwargs):
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
