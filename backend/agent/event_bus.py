"""Agent 节点事件工具"""

from typing import Any


async def emit_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    """记录事件，并在流式模式下立即推送到队列。"""
    events = state.setdefault("stream_events", [])
    events.append(event)
    queue = state.get("event_queue")
    if queue is not None:
        await queue.put(event)
