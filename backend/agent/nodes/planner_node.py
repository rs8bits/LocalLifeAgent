"""规划节点 - 标签对齐 → 场所搜索 → 方案组合"""

from backend.agent.state import AgentState
from backend.tools.registry import get_tool
from backend.agent.schemas import Intent
from backend.agent.tag_resolver import resolve_domain_tags
from backend.agent.planner import (
    _build_diverse_plans,
    _enrich_plan,
    _indoor_preference,
    _resolve_mock_weather_date,
    _dedupe_by_id,
)
from backend.agent.scorer import score_plan


async def planner_node(state: AgentState) -> AgentState:
    """新流程：标签对齐 → 天气 → 场所搜索 → 方案组合"""
    events: list[dict] = state.get("stream_events", [])
    tool_logs: list[dict] = []
    warnings: list[str] = []

    intent_dict = state.get("intent", {})
    intent = Intent(**intent_dict)

    events.append({
        "event": "planner_start",
        "message": "开始规划...",
        "data": {},
    })

    # ── 1. 标签对齐 ──
    events.append({"event": "tag_catalog_start", "message": "正在查询标签目录...", "data": {}})
    events.append({"event": "tag_catalog_done", "message": "标签目录已加载", "data": {}})
    events.append({"event": "tag_resolve_start", "message": "正在对齐用户意图与业务标签...", "data": {}})
    tag_result = await resolve_domain_tags(
        message=state.get("user_message", ""),
        intent=intent,
        intent_dict=intent_dict,
    )
    events.append({
        "event": "tag_resolve_done",
        "message": f"标签对齐完成: domains={tag_result['domains']}",
        "data": tag_result,
    })
    state["tag_resolve_result"] = tag_result

    domains = tag_result["domains"]
    domain_required = tag_result.get("domain_required", {})
    domain_tags = tag_result.get("domain_tags", {})

    # ── 2. 天气 ──
    events.append({"event": "tool_start", "message": "查询天气...", "data": {"tool": "get_weather"}})
    weather_result = await _run_tool("get_weather", tool_logs,
        date=_resolve_mock_weather_date(intent.date), location="朝阳区")
    events.append({"event": "tool_done", "message": tool_logs[-1]["message"],
                   "data": {"tool": "get_weather", "status": "ok"}})
    if weather_result and weather_result.status == "ok" and weather_result.data:
        state["weather"] = weather_result.data[0]

    indoor_pref = _indoor_preference(weather_result, intent)
    scene = intent.scene
    radius = intent.radius_km
    people = intent.people_count
    queue_limit = (intent.avoid_queue_minutes or 30) * 2

    # ── 3. 场所搜索 (按 domain) ──
    activities: list[dict] = []
    restaurants: list[dict] = []
    drinks: list[dict] = []

    for domain_name in domains:
        events.append({
            "event": "place_search_start",
            "message": f"正在搜索场所 ({domain_name})...",
            "data": {"domain": domain_name},
        })

        # 构建搜索参数
        params = {
            "domain": domain_name,
            "scene": scene,
            "radius_km": radius,
        }
        tags = domain_tags.get(domain_name, [])

        if domain_name == "play":
            if tags:
                params["tags_any"] = tags
            if intent.scene == "family":
                params["child_age"] = intent.child_age
            if indoor_pref is not None:
                params["indoor"] = indoor_pref

        elif domain_name == "eat":
            if tags:
                params["tags_any"] = tags
            params["party_size"] = people
            params["available"] = True
            params["max_queue_minutes"] = queue_limit

        elif domain_name == "drink":
            sub_cats = tag_result.get("domain_sub_categories", {}).get("drink", [])
            if sub_cats:
                params["sub_category"] = sub_cats[0]
            if tags:
                params["tags_any"] = tags

        result = await _run_tool("search_places", tool_logs, **params)

        if result and result.status == "ok":
            data = result.data or []
            if domain_name == "play":
                activities = data
            elif domain_name == "eat":
                restaurants = data
            elif domain_name == "drink":
                drinks = data

            # 记录 tag 放宽警告
            if result.error:
                warnings.append(f"[{domain_name}] {result.error}")

        events.append({
            "event": "place_search_done",
            "message": tool_logs[-1]["message"],
            "data": {"domain": domain_name, "count": len(result.data) if result and result.data else 0},
        })

    # eat fallback: 低卡需求
    if intent.needs_low_calorie and len(restaurants) < 2 and "eat" in domains:
        fallback = await _run_tool("search_places", tool_logs,
            domain="eat", scene=scene, radius_km=radius,
            party_size=people, available=True,
        )
        if fallback and fallback.status == "ok":
            restaurants = _dedupe_by_id(restaurants, fallback.data)

    state["candidate_activities"] = activities
    state["candidate_restaurants"] = restaurants
    state["candidate_drinks"] = drinks

    # ── 4. 方案组合 ──
    plans = _build_diverse_plans(intent, activities, restaurants, drinks, tool_logs)

    # 将搜索不到的领域信息写入 risk_tips；只有完全无方案时才作为 errors。
    for domain_name in domains:
        is_required = domain_required.get(domain_name, False)
        count = {"play": len(activities), "eat": len(restaurants), "drink": len(drinks)}.get(domain_name, 0)
        label_cn = {"play": "活动", "eat": "餐厅", "drink": "饮品"}.get(domain_name, domain_name)
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
    for plan in plans:
        score_plan(plan, intent)

    # 输出 plan_delta
    for i, plan in enumerate(plans[:4]):
        events.append({
            "event": "plan_delta",
            "message": f"方案{i + 1}: {plan.get('title', '')}",
            "data": {"plan": plan},
        })

    state["plans"] = plans[:4]
    state["tool_logs"] = tool_logs
    state["stream_events"] = events

    return state


async def _run_tool(name: str, tool_logs: list[dict], **kwargs):
    tool = get_tool(name)
    if not tool:
        tool_logs.append({"tool": name, "status": "error", "message": f"工具 {name} 未注册"})
        return None
    filtered = {k: v for k, v in kwargs.items() if v is not None}
    result = await tool.run(**filtered)
    log = {"tool": result.tool, "status": result.status, "message": result.message}
    if result.error:
        log["detail"] = result.error
    tool_logs.append(log)
    return result
