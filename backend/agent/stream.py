"""SSE 流式输出工具"""

import json
from typing import AsyncIterator


async def sse_event(event: str, message: str = "", data: dict | None = None) -> str:
    """构建单条 SSE 数据"""
    payload = {"event": event, "message": message, "data": data or {}}
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def plan_stream_events(state: dict) -> AsyncIterator[str]:
    """将 Graph 运行结果的 stream_events 转为 SSE 文本流"""
    events = state.get("stream_events", [])
    for evt in events:
        event_type = evt.get("event", "message")
        message = evt.get("message", "")
        data = evt.get("data", {})
        yield f"event: {event_type}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
    # 最后发送 plan_done
    plan_done = {
        "event": "plan_done",
        "message": "规划完成",
        "data": {
            "session_id": state.get("session_id", ""),
            "plans_count": len(state.get("plans", [])),
            "result": {
                "session_id": state.get("session_id", ""),
                "user_id": state.get("user_id", "user_001"),
                "message": state.get("user_message", ""),
                "intent": state.get("intent", {}),
                "plans": state.get("plans", []),
                "tool_logs": state.get("tool_logs", []),
                "errors": state.get("errors", []),
                "reflection_result": state.get("reflection_result", {}),
                "guardrail_result": state.get("guardrail_result", {}),
            },
        },
    }
    yield f"event: plan_done\ndata: {json.dumps(plan_done, ensure_ascii=False)}\n\n"


async def confirm_stream_events(state: dict) -> AsyncIterator[str]:
    """将确认执行的 stream_events 转为 SSE 文本流"""
    events = state.get("stream_events", [])
    # 只发送 execution 阶段的 events
    in_exec = False
    for evt in events:
        etype = evt.get("event", "")
        if etype in ("confirm_start", "booking_start", "order_start"):
            in_exec = True
        if in_exec:
            yield f"event: {etype}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"

    # confirm_done
    confirm_done = {
        "event": "confirm_done",
        "message": "执行完成",
        "data": {
            "share_message": state.get("share_message"),
            "execution_result": state.get("execution_result"),
            "result": {
                "status": (state.get("execution_result") or {}).get("status", "failed"),
                "session_id": state.get("session_id", ""),
                "plan_id": state.get("selected_plan_id", ""),
                "selected_plan": _selected_plan(state),
                "execution_result": state.get("execution_result") or {},
                "bookings": (state.get("execution_result") or {}).get("bookings", []),
                "orders": (state.get("execution_result") or {}).get("orders", []),
                "share_message": state.get("share_message"),
                "errors": (state.get("execution_result") or {}).get("errors", []),
            },
        },
    }
    yield f"event: confirm_done\ndata: {json.dumps(confirm_done, ensure_ascii=False)}\n\n"


def _selected_plan(state: dict) -> dict | None:
    plan_id = state.get("selected_plan_id")
    for plan in state.get("plans", []):
        if plan.get("plan_id") == plan_id:
            return plan
    return None
