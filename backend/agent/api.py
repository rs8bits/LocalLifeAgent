"""Agent API 路由（含流式 SSE）"""

import json
import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.schemas.agent_api import (
    AgentPlanRequest,
    AgentPlanResponse,
    AgentConfirmRequest,
    AgentConfirmResponse,
)
from backend.agent.planner import plan_for_message
from backend.agent.session_store import create_session, get_session, update_session
from backend.agent.executor import execute_plan
from backend.agent.message_generator import generate_share_message

# Graph 导入
from backend.agent.graph import run_planning_graph, run_execution_graph
from backend.agent.stream import plan_stream_events, confirm_stream_events

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ═══════════════════════════════════════════════════════════════
# 非流式 API（保持兼容）
# ═══════════════════════════════════════════════════════════════

@router.post("/plan", response_model=AgentPlanResponse)
async def agent_plan(req: AgentPlanRequest):
    """规划接口：使用 Graph 流程生成方案（兼容原响应格式）"""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    # 使用 LangGraph 流程
    graph_result = await run_planning_graph(
        user_id=req.user_id,
        message=req.message,
    )

    # 转换为兼容格式
    errors = list(graph_result.get("errors", []))
    guardrail_result = graph_result.get("guardrail_result", {})
    plans = graph_result.get("plans", [])
    if guardrail_result.get("blocked"):
        errors.extend(guardrail_result.get("issues", []))
        plans = []

    planner_output = {
        "intent": graph_result.get("intent", {}),
        "plans": plans,
        "tool_logs": graph_result.get("tool_logs", []),
        "errors": errors,
    }

    session = create_session(
        user_id=req.user_id,
        message=req.message,
        planner_output=planner_output,
    )

    # 将 graph 的 reflection/guardrails 结果写入 session
    update_session(session["session_id"], {
        "reflection_result": graph_result.get("reflection_result", {}),
        "guardrail_result": graph_result.get("guardrail_result", {}),
    })

    return AgentPlanResponse(
        session_id=session["session_id"],
        user_id=req.user_id,
        message=req.message,
        intent=planner_output.get("intent", {}),
        plans=planner_output.get("plans", []),
        tool_logs=planner_output.get("tool_logs", []),
        errors=planner_output.get("errors", []),
    )


@router.post("/confirm", response_model=AgentConfirmResponse)
async def agent_confirm(req: AgentConfirmRequest):
    """确认接口：执行预约、订位、下单（兼容原响应格式）"""
    session = get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session 不存在: {req.session_id}")

    if session.get("status") in ("success", "confirmed", "partial_success", "failed"):
        return AgentConfirmResponse(
            status=session["status"],
            session_id=req.session_id,
            plan_id=session.get("selected_plan_id", ""),
            selected_plan=None,
            execution_result=session.get("execution_result") or {},
            bookings=session.get("execution_result", {}).get("bookings", []),
            orders=session.get("execution_result", {}).get("orders", []),
            share_message=session.get("share_message"),
            errors=session.get("execution_result", {}).get("errors", []),
        )

    plans = session.get("plans", [])
    selected_plan = None
    for p in plans:
        if p.get("plan_id") == req.plan_id:
            selected_plan = p
            break

    if selected_plan is None:
        raise HTTPException(status_code=404, detail=f"Plan 不存在: {req.plan_id}")

    # 使用 Graph 执行流程
    graph_state = {
        "session_id": req.session_id,
        "user_id": session.get("user_id", "user_001"),
        "user_message": session.get("message", ""),
        "intent": session.get("intent", {}),
        "user_profile": {},
        "candidate_activities": [],
        "candidate_restaurants": [],
        "plans": plans,
        "selected_plan_id": req.plan_id,
        "tool_logs": session.get("tool_logs", []),
        "reflection_result": {},
        "guardrail_result": {},
        "execution_result": None,
        "share_message": None,
        "errors": [],
        "stream_events": [],
        "phase": "execution",
    }
    exec_state = await run_execution_graph(graph_state, req.plan_id)
    result = exec_state.get("execution_result", {})
    share_msg = exec_state.get("share_message", "")

    update_session(req.session_id, {
        "status": result.get("status", "failed"),
        "selected_plan_id": req.plan_id,
        "execution_result": result,
        "share_message": share_msg,
    })

    return AgentConfirmResponse(
        status=result.get("status", "failed"),
        session_id=req.session_id,
        plan_id=req.plan_id,
        selected_plan=selected_plan,
        execution_result=result,
        bookings=result.get("bookings", []),
        orders=result.get("orders", []),
        share_message=share_msg,
        errors=result.get("errors", []),
    )


@router.get("/session/{session_id}")
async def agent_get_session(session_id: str):
    """查询 session 详情"""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session 不存在: {session_id}")
    return session


# ═══════════════════════════════════════════════════════════════
# 流式 SSE API
# ═══════════════════════════════════════════════════════════════

@router.post("/plan/stream")
async def agent_plan_stream(req: AgentPlanRequest):
    """流式规划接口 (SSE)"""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    async def event_stream():
        try:
            # 发送 confirm_start 作为初始事件
            yield f"event: intent_start\ndata: {json.dumps({'event': 'intent_start', 'message': '开始规划...', 'data': {}}, ensure_ascii=False)}\n\n"

            graph_result = await run_planning_graph(
                user_id=req.user_id,
                message=req.message,
            )

            errors = list(graph_result.get("errors", []))
            guardrail_result = graph_result.get("guardrail_result", {})
            plans = graph_result.get("plans", [])
            if guardrail_result.get("blocked"):
                errors.extend(guardrail_result.get("issues", []))
                plans = []

            planner_output = {
                "intent": graph_result.get("intent", {}),
                "plans": plans,
                "tool_logs": graph_result.get("tool_logs", []),
                "errors": errors,
            }

            session = create_session(
                user_id=req.user_id,
                message=req.message,
                planner_output=planner_output,
            )

            # 更新 session_id 到结果
            graph_result["session_id"] = session["session_id"]
            graph_result["plans"] = plans
            graph_result["errors"] = errors

            update_session(session["session_id"], {
                "reflection_result": graph_result.get("reflection_result", {}),
                "guardrail_result": graph_result.get("guardrail_result", {}),
            })

            # 流式输出事件
            async for chunk in plan_stream_events(graph_result):
                yield chunk

        except Exception as e:
            err = {"event": "error", "message": str(e), "data": {}}
            yield f"event: error\ndata: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/confirm/stream")
async def agent_confirm_stream(req: AgentConfirmRequest):
    """流式确认接口 (SSE)"""
    session = get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session 不存在: {req.session_id}")

    if session.get("status") in ("success", "confirmed", "partial_success", "failed"):
        # 已确认过，直接返回
        async def done_stream():
            done = {
                "event": "confirm_done",
                "message": "已确认（复用之前结果）",
                "data": {
                    "share_message": session.get("share_message"),
                    "execution_result": session.get("execution_result"),
                },
            }
            yield f"event: confirm_done\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"
        return StreamingResponse(
            done_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    plans = session.get("plans", [])
    selected_plan = None
    for p in plans:
        if p.get("plan_id") == req.plan_id:
            selected_plan = p
            break

    if selected_plan is None:
        raise HTTPException(status_code=404, detail=f"Plan 不存在: {req.plan_id}")

    async def event_stream():
        try:
            yield f"event: confirm_start\ndata: {json.dumps({'event': 'confirm_start', 'message': '开始执行...', 'data': {}}, ensure_ascii=False)}\n\n"

            graph_state = {
                "session_id": req.session_id,
                "user_id": session.get("user_id", "user_001"),
                "user_message": session.get("message", ""),
                "intent": session.get("intent", {}),
                "user_profile": {},
                "candidate_activities": [],
                "candidate_restaurants": [],
                "plans": plans,
                "selected_plan_id": req.plan_id,
                "tool_logs": session.get("tool_logs", []),
                "reflection_result": {},
                "guardrail_result": {},
                "execution_result": None,
                "share_message": None,
                "errors": [],
                "stream_events": [],
                "phase": "execution",
            }
            exec_state = await run_execution_graph(graph_state, req.plan_id)
            result = exec_state.get("execution_result", {})
            share_msg = exec_state.get("share_message", "")

            update_session(req.session_id, {
                "status": result.get("status", "failed"),
                "selected_plan_id": req.plan_id,
                "execution_result": result,
                "share_message": share_msg,
            })

            async for chunk in confirm_stream_events(exec_state):
                yield chunk

        except Exception as e:
            err = {"event": "error", "message": str(e), "data": {}}
            yield f"event: error\ndata: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
