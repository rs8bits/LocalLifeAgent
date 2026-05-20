"""LangGraph 编排 - 多 Agent 节点工作流"""

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


async def run_execution_graph(
    state: dict, plan_id: str
) -> dict:
    """运行确认执行 Graph"""
    state["selected_plan_id"] = plan_id
    state["phase"] = "execution"
    state["stream_events"] = state.get("stream_events", [])
    result = await execution_graph.ainvoke(state)
    return result
