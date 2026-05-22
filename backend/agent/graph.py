"""LangGraph 编排 - 多 Agent 节点工作流"""

import asyncio
import contextlib
import json
from typing import AsyncIterator

from langgraph.graph import StateGraph, END

from backend.agent.state import AgentState, DEFAULT_MAX_RETRIES
from backend.agent.nodes.intent_node import intent_node
from backend.agent.nodes.memory_node import memory_node
from backend.agent.nodes.planner_node import planner_node
from backend.agent.nodes.reflection_node import reflection_node
from backend.agent.nodes.guardrails_node import guardrails_node
from backend.agent.nodes.executor_node import executor_node
from backend.agent.nodes.message_llm_node import message_llm_node
from backend.agent.nodes.input_safety_node import input_safety_node
from backend.agent.nodes.rewrite_node import rewrite_node


# ── Routers ───────────────────────────────────────────────────────────

def input_safety_router(state: AgentState) -> str:
    result = state.get("input_safety_result", {})
    if result.get("blocked"):
        return "blocked"
    return "passed"


def plan_guardrails_router(state: AgentState) -> str:
    result = state.get("guardrail_result", {})
    if result.get("passed"):
        return "passed"
    if result.get("retryable") and result.get("can_retry"):
        return "retry"
    return "blocked"


def message_guardrails_router(state: AgentState) -> str:
    result = state.get("guardrail_result", {})
    if result.get("passed"):
        return "passed"
    if result.get("retryable") and result.get("can_retry"):
        return "retry"
    return "blocked"


# ── Build Graph ───────────────────────────────────────────────────────

def _make_base_state(
    user_id: str = "",
    message: str = "",
    user_profile: dict | None = None,
) -> AgentState:
    return {
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
        "tag_resolve_result": {},
        "tool_logs": [],
        "reflection_result": {},
        "guardrail_result": {},
        "execution_result": None,
        "share_message": None,
        "errors": [],
        "stream_events": [],
        "phase": "planning",
        "input_safety_result": {},
        "rewrite_result": {},
        "guardrail_feedback": {},
        "planner_retry_count": 0,
        "message_retry_count": 0,
        "max_retries": DEFAULT_MAX_RETRIES,
    }


def build_planning_graph() -> StateGraph:
    """构建规划阶段 Graph

    input_safety -> memory -> rewrite -> intent -> planner -> reflection -> guardrails
       |            (blocked -> END)                                   /    |      \
       |                                              passed -> END   retry -> planner  blocked -> END
    """
    graph = StateGraph(AgentState)

    graph.add_node("input_safety", input_safety_node)
    graph.add_node("memory", memory_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("intent", intent_node)
    graph.add_node("planner", planner_node)
    graph.add_node("reflection", reflection_node)
    graph.add_node("guardrails", guardrails_node)

    graph.set_entry_point("input_safety")
    graph.add_conditional_edges(
        "input_safety",
        input_safety_router,
        {"blocked": END, "passed": "memory"},
    )
    graph.add_edge("memory", "rewrite")
    graph.add_edge("rewrite", "intent")
    graph.add_edge("intent", "planner")
    graph.add_edge("planner", "reflection")
    graph.add_edge("reflection", "guardrails")
    graph.add_conditional_edges(
        "guardrails",
        plan_guardrails_router,
        {"passed": END, "retry": "planner", "blocked": END},
    )

    return graph.compile()


def build_execution_graph() -> StateGraph:
    """构建确认执行阶段 Graph

    executor -> message_llm -> guardrails
                   ^            /   |    \
                   |  retry  <─'   END  END
    """
    graph = StateGraph(AgentState)

    graph.add_node("executor", executor_node)
    graph.add_node("message_llm", message_llm_node)
    graph.add_node("guardrails", guardrails_node)

    graph.set_entry_point("executor")
    graph.add_edge("executor", "message_llm")
    graph.add_edge("message_llm", "guardrails")
    graph.add_conditional_edges(
        "guardrails",
        message_guardrails_router,
        {"passed": END, "retry": "message_llm", "blocked": END},
    )

    return graph.compile()


# 导出编译后的 graph 实例
planning_graph = build_planning_graph()
execution_graph = build_execution_graph()


async def run_planning_graph(
    user_id: str, message: str, user_profile: dict | None = None
) -> dict:
    """运行规划 Graph，返回最终状态"""
    initial_state = _make_base_state(user_id=user_id, message=message, user_profile=user_profile)
    result = await planning_graph.ainvoke(initial_state)
    return result


async def run_planning_graph_stream(
    user_id: str, message: str, user_profile: dict | None = None
) -> AsyncIterator[str]:
    """运行规划 Graph 并以 SSE 格式实时流式输出每个节点的事件。"""
    initial_state = _make_base_state(user_id=user_id, message=message, user_profile=user_profile)

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

    # Graph 完成后，生成 plan_done
    from backend.agent.session_store import create_session, update_session

    errors = list(accumulated.get("errors", []))
    guardrail_result = accumulated.get("guardrail_result", {})
    input_safety_result = accumulated.get("input_safety_result", {})
    plans = accumulated.get("plans", [])
    guardrail_failed = bool(guardrail_result) and not guardrail_result.get("passed", True)

    if guardrail_failed or input_safety_result.get("blocked"):
        if guardrail_failed:
            for issue in guardrail_result.get("issues", []):
                if issue not in errors:
                    errors.append(issue)
        if input_safety_result.get("blocked"):
            safe_message = input_safety_result.get("safe_message", "输入被拦截")
            if safe_message not in errors:
                errors.append(safe_message)
        plans = []

    planner_output = {
        "intent": accumulated.get("intent", {}),
        "plans": plans,
        "tool_logs": accumulated.get("tool_logs", []),
        "errors": errors,
    }

    # 只有 guardrails 通过后才创建 session
    guardrail_passed = not guardrail_failed and not input_safety_result.get("blocked")
    session_id = ""
    if guardrail_passed:
        session = create_session(
            user_id=user_id,
            message=message,
            planner_output=planner_output,
        )
        session_id = session["session_id"]
        update_session(session_id, {
            "reflection_result": accumulated.get("reflection_result", {}),
            "guardrail_result": accumulated.get("guardrail_result", {}),
            "input_safety_result": accumulated.get("input_safety_result", {}),
            "rewrite_result": accumulated.get("rewrite_result", {}),
        })

    plan_done = {
        "event": "plan_done",
        "message": "规划完成" if guardrail_passed else "规划被阻止",
        "data": {
            "session_id": session_id,
            "plans_count": len(plans),
            "result": {
                "session_id": session_id,
                "user_id": user_id,
                "message": message,
                "intent": accumulated.get("intent", {}),
                "plans": plans,
                "tool_logs": accumulated.get("tool_logs", []),
                "errors": errors,
                "input_safety_result": accumulated.get("input_safety_result", {}),
                "rewrite_result": accumulated.get("rewrite_result", {}),
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
    # Ensure new state fields exist
    state.setdefault("message_retry_count", 0)
    state.setdefault("max_retries", DEFAULT_MAX_RETRIES)
    state.setdefault("guardrail_feedback", {})
    result = await execution_graph.ainvoke(state)
    return result


async def run_execution_graph_stream(
    state: dict, plan_id: str
) -> AsyncIterator[str]:
    """运行确认执行 Graph，并在事件产生时立即输出 SSE。"""
    state["selected_plan_id"] = plan_id
    state["phase"] = "execution"
    state["stream_events"] = state.get("stream_events", [])
    state.setdefault("message_retry_count", 0)
    state.setdefault("max_retries", DEFAULT_MAX_RETRIES)
    state.setdefault("guardrail_feedback", {})
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
    guardrail_result = exec_state.get("guardrail_result", {})
    guardrail_passed = guardrail_result.get("passed", True)
    response_errors = list(result.get("errors", []))
    if not guardrail_passed:
        for issue in guardrail_result.get("issues", []):
            if issue not in response_errors:
                response_errors.append(issue)
        share_msg = None

    from backend.agent.session_store import update_session

    # 只有 MessageGuardrails 通过后才更新 session
    if guardrail_passed:
        update_session(state.get("session_id", ""), {
            "status": result.get("status", "failed"),
            "selected_plan_id": plan_id,
            "execution_result": result,
            "share_message": share_msg,
            "message_guardrail_result": guardrail_result,
        })

    confirm_done = {
        "event": "confirm_done",
        "message": "执行完成",
        "data": {
            "share_message": share_msg,
            "execution_result": result,
            "message_guardrail_result": guardrail_result,
            "result": {
                "status": result.get("status", "failed"),
                "session_id": state.get("session_id", ""),
                "plan_id": plan_id,
                "selected_plan": _selected_plan(exec_state, plan_id),
                "execution_result": result,
                "bookings": result.get("bookings", []),
                "orders": result.get("orders", []),
                "share_message": share_msg,
                "errors": response_errors,
                "message_guardrail_result": guardrail_result,
            },
        },
    }
    yield f"event: confirm_done\ndata: {json.dumps(confirm_done, ensure_ascii=False)}\n\n"


def _selected_plan(state: dict, plan_id: str) -> dict | None:
    for plan in state.get("plans", []):
        if plan.get("plan_id") == plan_id:
            return plan
    return None
