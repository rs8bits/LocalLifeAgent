"""Agent API 路由"""

from fastapi import APIRouter, HTTPException

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

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/plan", response_model=AgentPlanResponse)
async def agent_plan(req: AgentPlanRequest):
    """规划接口：只生成方案，不预约/不下单"""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    planner_output = await plan_for_message(
        user_id=req.user_id,
        message=req.message,
    )

    session = create_session(
        user_id=req.user_id,
        message=req.message,
        planner_output=planner_output,
    )

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
    """确认接口：用户确认后执行预约、订位、下单"""
    session = get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session 不存在: {req.session_id}")

    # 如果已经确认过，返回已有结果
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

    # 查找 plan
    plans = session.get("plans", [])
    selected_plan = None
    for p in plans:
        if p.get("plan_id") == req.plan_id:
            selected_plan = p
            break

    if selected_plan is None:
        raise HTTPException(status_code=404, detail=f"Plan 不存在: {req.plan_id}")

    # 执行
    result = await execute_plan(session, req.plan_id)

    # 生成转发消息
    share_msg = generate_share_message(
        plan=selected_plan,
        intent=session.get("intent", {}),
        bookings=result["bookings"],
        orders=result["orders"],
    )

    # 更新 session
    update_session(req.session_id, {
        "status": result["status"],
        "selected_plan_id": req.plan_id,
        "execution_result": result,
        "share_message": share_msg,
    })

    return AgentConfirmResponse(
        status=result["status"],
        session_id=req.session_id,
        plan_id=req.plan_id,
        selected_plan=selected_plan,
        execution_result=result,
        bookings=result["bookings"],
        orders=result["orders"],
        share_message=share_msg,
        errors=result["errors"],
    )


@router.get("/session/{session_id}")
async def agent_get_session(session_id: str):
    """查询 session 详情"""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session 不存在: {session_id}")
    return session
