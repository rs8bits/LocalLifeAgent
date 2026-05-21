"""LangGraph 编排 - 多 Agent 节点工作流"""

import asyncio
import contextlib
import json
from typing import AsyncIterator

from langgraph.graph import StateGraph, END

from backend.agent.state import AgentState
from backend.agent.nodes.intent_node import intent_node
from backend.agent.nodes.memory_node import memory_node
from backend.agent.nodes.planner_node import planner_node
from backend.agent.nodes.reflection_node import reflection_node
from backend.agent.nodes.guardrails_node import guardrails_node
from backend.agent.nodes.executor_node import executor_node
from backend.agent.nodes.message_node import message_node


def build_planning_graph() -> StateGraph:
    """构建规划阶段 Graph"""
    graph = StateGraph(AgentState)

    graph.add_node("memory", memory_node)
    graph.add_node("intent", intent_node)
    graph.add_node("planner", planner_node)
    graph.add_node("reflection", reflection_node)
    graph.add_node("guardrails", guardrails_node)

    graph.set_entry_point("memory")
    graph.add_edge("memory", "intent")
    graph.add_edge("intent", "planner")
    graph.add_edge("planner", "reflection")
    graph.add_edge("reflection", "guardrails")
    graph.add_edge("guardrails", END)

    return graph.compile()


def build_execution_graph() -> StateGraph:
    """构建确认执行阶段 Graph"""
    graph = StateGraph(AgentState)

    graph.add_node("executor", executor_node)
    graph.add_node("guardrails", guardrails_node)
    graph.add_node("message", message_node)

    graph.set_entry_point("executor")
    graph.add_edge("executor", "guardrails")
    graph.add_edge("guardrails", "message")
    graph.add_edge("message", END)

    return graph.compile()


# 导出编译后的 graph 实例
planning_graph = build_planning_graph()
execution_graph = build_execution_graph()


async def run_planning_graph(
    user_id: str, message: str, user_profile: dict | None = None
) -> dict:
    """运行规划 Graph，返回最终状态"""
    initial_state: AgentState = {
        "session_id": None,
        "user_id": user_id,
        "user_message": message,
        "intent": {},
        "user_profile": user_profile or {},
        "candidate_activities": [],
        "candidate_restaurants": [],
        "candidate_drinks": [],
        "candidate_delivery_items": [],
        "candidate_routes": [],
        "candidate_deals": [],
        "weather": None,
        "plans": [],
        "selected_plan_id": None,
        "tool_logs": [],
        "reflection_result": {},
        "guardrail_result": {},
        "execution_result": None,
        "share_message": None,
        "errors": [],
        "stream_events": [],
        "phase": "planning",
    }
    result = await planning_graph.ainvoke(initial_state)
    return result


async def run_planning_graph_stream(
    user_id: str, message: str, user_profile: dict | None = None
) -> AsyncIterator[str]:
    """运行规划 Graph 并以 SSE 格式实时流式输出每个节点的事件。

    与 run_planning_graph 不同，本函数通过 event_queue 在事件产生时
    立即产出 SSE，而不是等整个 Graph 完成后再回放。
    """
    initial_state: AgentState = {
        "session_id": None,
        "user_id": user_id,
        "user_message": message,
        "intent": {},
        "user_profile": user_profile or {},
        "candidate_activities": [],
        "candidate_restaurants": [],
        "candidate_drinks": [],
        "candidate_delivery_items": [],
        "candidate_routes": [],
        "candidate_deals": [],
        "weather": None,
        "plans": [],
        "selected_plan_id": None,
        "tool_logs": [],
        "reflection_result": {},
        "guardrail_result": {},
        "execution_result": None,
        "share_message": None,
        "errors": [],
        "stream_events": [],
        "phase": "planning",
    }

    event_queue: asyncio.Queue[dict] = asyncio.Queue()
    initial_state["event_queue"] = event_queue

    task = asyncio.create_task(planning_graph.ainvoke(initial_state))
    try:
        while True:
            if task.done() and event_queue.empty():
                break
            try:
                evt = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            event_type = evt.get("event", "message")
            yield f"event: {event_type}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"

        accumulated = await task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # Graph 完成后，生成 plan_done（含 session 写入）
    from backend.agent.session_store import create_session, update_session

    errors = list(accumulated.get("errors", []))
    guardrail_result = accumulated.get("guardrail_result", {})
    plans = accumulated.get("plans", [])
    if guardrail_result.get("blocked"):
        errors.extend(guardrail_result.get("issues", []))
        plans = []

    planner_output = {
        "intent": accumulated.get("intent", {}),
        "plans": plans,
        "tool_logs": accumulated.get("tool_logs", []),
        "errors": errors,
    }

    session = create_session(
        user_id=user_id,
        message=message,
        planner_output=planner_output,
    )

    update_session(session["session_id"], {
        "reflection_result": accumulated.get("reflection_result", {}),
        "guardrail_result": accumulated.get("guardrail_result", {}),
    })

    plan_done = {
        "event": "plan_done",
        "message": "规划完成",
        "data": {
            "session_id": session["session_id"],
            "plans_count": len(plans),
            "result": {
                "session_id": session["session_id"],
                "user_id": user_id,
                "message": message,
                "intent": accumulated.get("intent", {}),
                "plans": plans,
                "tool_logs": accumulated.get("tool_logs", []),
                "errors": errors,
                "reflection_result": accumulated.get("reflection_result", {}),
                "guardrail_result": accumulated.get("guardrail_result", {}),
            },
        },
    }
    yield f"event: plan_done\ndata: {json.dumps(plan_done, ensure_ascii=False)}\n\n"


async def run_execution_graph(
    state: dict, plan_id: str
) -> dict:
    """运行确认执行 Graph"""
    state["selected_plan_id"] = plan_id
    state["phase"] = "execution"
    state["stream_events"] = state.get("stream_events", [])
    result = await execution_graph.ainvoke(state)
    return result


async def run_execution_graph_stream(
    state: dict, plan_id: str
) -> AsyncIterator[str]:
    """运行确认执行 Graph，并在预约/下单事件产生时立即输出 SSE。"""
    state["selected_plan_id"] = plan_id
    state["phase"] = "execution"
    state["stream_events"] = state.get("stream_events", [])
    event_queue: asyncio.Queue[dict] = asyncio.Queue()
    state["event_queue"] = event_queue

    task = asyncio.create_task(execution_graph.ainvoke(state))
    try:
        while True:
            if task.done() and event_queue.empty():
                break
            try:
                evt = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            event_type = evt.get("event", "message")
            yield f"event: {event_type}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"

        exec_state = await task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    result = exec_state.get("execution_result", {}) or {}
    share_msg = exec_state.get("share_message", "")

    from backend.agent.session_store import update_session

    update_session(state.get("session_id", ""), {
        "status": result.get("status", "failed"),
        "selected_plan_id": plan_id,
        "execution_result": result,
        "share_message": share_msg,
    })

    confirm_done = {
        "event": "confirm_done",
        "message": "执行完成",
        "data": {
            "share_message": share_msg,
            "execution_result": result,
            "result": {
                "status": result.get("status", "failed"),
                "session_id": state.get("session_id", ""),
                "plan_id": plan_id,
                "selected_plan": _selected_plan(exec_state, plan_id),
                "execution_result": result,
                "bookings": result.get("bookings", []),
                "orders": result.get("orders", []),
                "share_message": share_msg,
                "errors": result.get("errors", []),
            },
        },
    }
    yield f"event: confirm_done\ndata: {json.dumps(confirm_done, ensure_ascii=False)}\n\n"


def _selected_plan(state: dict, plan_id: str) -> dict | None:
    for plan in state.get("plans", []):
        if plan.get("plan_id") == plan_id:
            return plan
    return None
