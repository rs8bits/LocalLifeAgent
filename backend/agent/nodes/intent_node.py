"""意图解析节点"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.agent.intent_parser import parse_intent
from backend.agent.revision import apply_revision_intent_patch


async def intent_node(state: AgentState) -> AgentState:
    """解析意图，产生流式事件"""
    await emit_event(state, {"event": "intent_start", "message": "正在解析意图...", "data": {}})

    try:
        user_profile = state.get("user_profile") or {}
        user_memory = (
            user_profile
            if "preferences" in user_profile
            else {"preferences": user_profile}
        )
        # 意图里的同行人/否定约束以用户原话为准，避免 rewrite 将长期记忆误当成当次同行人。
        effective_message = state["user_message"]
        intent = await parse_intent(
            message=effective_message,
            user_memory=user_memory,
        )
        apply_revision_intent_patch(intent, state.get("revision_patch"))
        state["intent"] = intent.model_dump()
        tag_text = f", tags={intent.tags}" if intent.tags else ""
        await emit_event(state, {
            "event": "intent_done",
            "message": f"意图解析完成: party_type={intent.party_type}{tag_text}",
            "data": {"intent": state["intent"]},
        })
    except Exception as e:
        state.setdefault("errors", []).append(f"意图解析失败: {e}")
        # 规则兜底已在 parse_intent 内部完成
        from backend.agent.intent_parser import _rule_parse
        intent = _rule_parse(state["user_message"])
        state["intent"] = intent.model_dump()
        await emit_event(state, {
            "event": "intent_done",
            "message": "意图解析完成（规则兜底）",
            "data": {"intent": state["intent"]},
        })

    return state
