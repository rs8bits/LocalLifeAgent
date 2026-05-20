"""规划节点 - 通过 Tool 查询数据并组合方案"""

import asyncio

from backend.agent.state import AgentState
from backend.tools.registry import get_tool
from backend.agent.schemas import Intent
from backend.agent.planner import (
    _build_plans,
    _enrich_plan,
    _indoor_preference,
    _resolve_mock_weather_date,
    _dedupe_by_id,
    _first,
)
from backend.agent.scorer import score_plan


async def planner_node(state: AgentState) -> AgentState:
    """查询工具并组合候选方案"""
    events: list[dict] = state.get("stream_events", [])
    tool_logs: list[dict] = []

    intent_dict = state.get("intent", {})
    intent = Intent(**intent_dict)

    events.append({
        "event": "planner_start",
        "message": "开始规划...",
        "data": {},
    })

    # 1. 天气
    events.append({"event": "tool_start", "message": "查询天气...", "data": {"tool": "get_weather"}})
    weather_result = await _run_tool("get_weather", tool_logs,
        date=_resolve_mock_weather_date(intent.date), location="朝阳区")
    events.append({"event": "tool_done", "message": tool_logs[-1]["message"],
                   "data": {"tool": "get_weather", "status": "ok"}})
    if weather_result and weather_result.status == "ok" and weather_result.data:
        state["weather"] = weather_result.data[0]

    # 2. 活动
    events.append({"event": "tool_start", "message": "查询活动...", "data": {"tool": "search_activities"}})
    activities_result = await _run_tool("search_activities", tool_logs,
        scene=intent.scene, radius_km=intent.radius_km,
        child_age=intent.child_age,
        indoor=_indoor_preference(weather_result, intent),
        tag=_first(intent.activity_preferences))
    state["candidate_activities"] = activities_result.data if activities_result and activities_result.status == "ok" else []
    events.append({"event": "tool_done", "message": tool_logs[-1]["message"],
                   "data": {"tool": "search_activities", "status": "ok"}})

    # 3. 餐厅
    events.append({"event": "tool_start", "message": "查询餐厅...", "data": {"tool": "search_restaurants"}})
    restaurants_result = await _run_tool("search_restaurants", tool_logs,
        scene=intent.scene, radius_km=intent.radius_km,
        party_size=intent.people_count,
        tag=_first(intent.food_preferences) if intent.food_preferences else None,
        available=True, max_queue_minutes=intent.avoid_queue_minutes * 2)
    state["candidate_restaurants"] = restaurants_result.data if restaurants_result and restaurants_result.status == "ok" else []
    events.append({"event": "tool_done", "message": tool_logs[-1]["message"],
                   "data": {"tool": "search_restaurants", "status": "ok"}})

    # 健康需求 fallback
    if intent.needs_low_calorie and len(state["candidate_restaurants"]) < 2:
        fallback = await _run_tool("search_restaurants", tool_logs,
            scene=intent.scene, radius_km=intent.radius_km,
            party_size=intent.people_count, available=True)
        if fallback and fallback.status == "ok":
            state["candidate_restaurants"] = _dedupe_by_id(
                state["candidate_restaurants"], fallback.data)

    # 组合方案
    plans = _build_plans(
        intent, state["candidate_activities"],
        state["candidate_restaurants"], tool_logs)

    # 丰富方案
    for plan in plans:
        await _enrich_plan(plan, tool_logs)

    # 评分排序
    for plan in plans:
        score_plan(plan, intent)
    plans.sort(key=lambda p: p.get("score", 0), reverse=True)

    # 输出 plan_delta
    for i, plan in enumerate(plans[:3]):
        events.append({
            "event": "plan_delta",
            "message": f"方案{i + 1}: {plan.get('title', '')}",
            "data": {"plan": plan},
        })

    state["plans"] = plans[:3]
    state["tool_logs"] = tool_logs
    state["stream_events"] = events

    if not state["candidate_activities"]:
        state.setdefault("errors", []).append("未找到符合条件的活动")
    if not state["candidate_restaurants"]:
        state.setdefault("errors", []).append("未找到符合条件的餐厅")

    return state


async def _run_tool(name: str, tool_logs: list[dict], **kwargs):
    tool = get_tool(name)
    if not tool:
        tool_logs.append({"tool": name, "status": "error", "message": f"工具 {name} 未注册"})
        return None
    filtered = {k: v for k, v in kwargs.items() if v is not None}
    result = await tool.run(**filtered)
    tool_logs.append({"tool": result.tool, "status": result.status, "message": result.message})
    return result
