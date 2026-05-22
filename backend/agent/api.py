"""Agent API 路由（含流式 SSE）"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.schemas.agent_api import (
    AgentPlanRequest,
    AgentPlanResponse,
    AgentConfirmRequest,
    AgentConfirmResponse,
)
from backend.agent.session_store import create_session, get_session, update_session

# Graph 导入
from backend.agent.graph import (
    run_planning_graph,
    run_planning_graph_stream,
    run_execution_graph,
    run_execution_graph_stream,
)

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
    input_safety_result = graph_result.get("input_safety_result", {})
    plans = graph_result.get("plans", [])
    guardrail_failed = bool(guardrail_result) and not guardrail_result.get("passed", True)

    if guardrail_failed:
        for issue in guardrail_result.get("issues", []):
            if issue not in errors:
                errors.append(issue)
    if input_safety_result.get("blocked"):
        safe_message = input_safety_result.get("safe_message", "输入被拦截")
        if safe_message not in errors:
            errors.append(safe_message)
    if guardrail_failed or input_safety_result.get("blocked"):
        plans = []

    planner_output = {
        "intent": graph_result.get("intent", {}),
        "plans": plans,
        "tool_logs": graph_result.get("tool_logs", []),
        "errors": errors,
    }

    session_id = ""
    if not guardrail_failed and not input_safety_result.get("blocked"):
        session = create_session(
            user_id=req.user_id,
            message=req.message,
            planner_output=planner_output,
        )

        # 将 graph 的 reflection/guardrails/新字段结果写入 session
        session_id = session["session_id"]
        update_session(session_id, {
            "reflection_result": graph_result.get("reflection_result", {}),
            "guardrail_result": graph_result.get("guardrail_result", {}),
            "input_safety_result": graph_result.get("input_safety_result", {}),
            "rewrite_result": graph_result.get("rewrite_result", {}),
        })

    return AgentPlanResponse(
        session_id=session_id,
        user_id=req.user_id,
        message=req.message,
        intent=planner_output.get("intent", {}),
        plans=planner_output.get("plans", []),
        tool_logs=planner_output.get("tool_logs", []),
        errors=planner_output.get("errors", []),
        input_safety_result=graph_result.get("input_safety_result", {}),
        rewrite_result=graph_result.get("rewrite_result", {}),
        reflection_result=graph_result.get("reflection_result", {}),
        guardrail_result=graph_result.get("guardrail_result", {}),
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
            message_guardrail_result=session.get("message_guardrail_result", {}),
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
        "candidate_drinks": [],
        "candidate_delivery_items": [],
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
        "message_retry_count": 0,
        "max_retries": 2,
        "guardrail_feedback": {},
    }
    exec_state = await run_execution_graph(graph_state, req.plan_id)
    result = exec_state.get("execution_result", {})
    share_msg = exec_state.get("share_message", "")
    guardrail_result = exec_state.get("guardrail_result", {})
    guardrail_passed = guardrail_result.get("passed", True)
    response_errors = list(result.get("errors", []))
    if not guardrail_passed:
        for issue in guardrail_result.get("issues", []):
            if issue not in response_errors:
                response_errors.append(issue)
        share_msg = None

    # 只有 guardrails 通过后才更新 session
    if guardrail_passed:
        update_session(req.session_id, {
            "status": result.get("status", "failed"),
            "selected_plan_id": req.plan_id,
            "execution_result": result,
            "share_message": share_msg,
            "message_guardrail_result": guardrail_result,
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
        errors=response_errors,
        message_guardrail_result=guardrail_result,
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
    """流式规划接口 (SSE) - 节点完成后立即输出，真正的实时流式"""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    async def event_stream():
        try:
            async for sse_chunk in run_planning_graph_stream(
                user_id=req.user_id,
                message=req.message,
            ):
                yield sse_chunk

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
                "message_retry_count": 0,
                "max_retries": 2,
                "guardrail_feedback": {},
            }
            async for chunk in run_execution_graph_stream(graph_state, req.plan_id):
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
