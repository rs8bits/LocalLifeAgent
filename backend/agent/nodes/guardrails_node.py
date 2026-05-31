"""Guardrails 节点 - 安全边界校验，支持 plan/message 分阶段和条件重试"""

from backend.agent.state import AgentState
from backend.agent.event_bus import emit_event
from backend.mock_api.storage import read_json


async def guardrails_node(state: AgentState) -> AgentState:
    """校验安全边界。

    规划阶段: 校验方案 POI/action/reference 合法性
    执行阶段: 校验转发消息内容
    """
    await emit_event(state, {
        "event": "guardrails_start",
        "message": "正在进行安全校验...",
        "data": {},
    })

    phase = state.get("phase", "planning")

    if phase == "execution":
        result = _check_message_guardrails(state)
    else:
        result = _check_plan_guardrails(state)

    state["guardrail_result"] = result

    if result.get("retryable") and not result.get("passed"):
        retry_key = "planner_retry_count" if phase == "planning" else "message_retry_count"
        retry_count = state.get(retry_key, 0)
        max_retries = state.get("max_retries", 2)
        can_retry = retry_count < max_retries
        result["can_retry"] = can_retry
        state["guardrail_result"] = result
        if can_retry:
            state[retry_key] = retry_count + 1
            await emit_event(state, {
                "event": "guardrails_retry",
                "message": f"发现可修复问题，将重试 (第{retry_count + 1}次)",
                "data": result,
            })
        else:
            await emit_event(state, {
                "event": "guardrails_done",
                "message": "安全校验未通过，已达到重试上限",
                "data": result,
            })
    elif result.get("passed"):
        await emit_event(state, {
            "event": "guardrails_done",
            "message": f"安全校验通过",
            "data": result,
        })
    else:
        await emit_event(state, {
            "event": "guardrails_done",
            "message": f"安全校验被阻止 ({len(result.get('issues', []))}个问题)",
            "data": result,
        })

    return state


def _check_plan_guardrails(state: AgentState) -> dict:
    """规划阶段 guardrails: POI/action 校验"""
    issues: list[str] = []
    retryable_issues: list[str] = []
    fatal_issues: list[str] = []

    plans = state.get("plans", [])

    # 加载所有合法 ID
    valid_activity_ids = {a["id"] for a in read_json("activities.json")}
    valid_restaurant_ids = {r["id"] for r in read_json("restaurants.json")}
    valid_deal_ids = {d["id"] for d in read_json("deals.json")}
    valid_drink_ids = {d["id"] for d in read_json("drinks.json")}
    valid_delivery_ids = {d["id"] for d in read_json("delivery_items.json")}

    for plan in plans:
        activity = plan.get("activity") or {}
        restaurant = plan.get("restaurant") or {}
        restaurants = _plan_restaurants(plan)
        drink = plan.get("drink") or {}
        delivery_items = plan.get("delivery_items") or []
        actions = plan.get("actions") or []
        deals = plan.get("deals", [])

        # 1. POI 来源校验 — FATAL (hallucinated data, can't fix by retry)
        act_id = activity.get("id", "")
        if act_id and act_id not in valid_activity_ids:
            msg = f"活动 ID {act_id} 不在合法数据中"
            issues.append(msg)
            fatal_issues.append(msg)

        for rest in restaurants or ([restaurant] if restaurant else []):
            rest_id = rest.get("id", "")
            if rest_id and rest_id not in valid_restaurant_ids:
                msg = f"餐厅 ID {rest_id} 不在合法数据中"
                issues.append(msg)
                fatal_issues.append(msg)

        drink_id = drink.get("id", "")
        if drink_id and drink_id not in valid_drink_ids:
            msg = f"饮品 ID {drink_id} 不在合法数据中"
            issues.append(msg)
            fatal_issues.append(msg)

        for deal in deals:
            deal_id = deal.get("id", "")
            if deal_id and deal_id not in valid_deal_ids:
                msg = f"团购券 ID {deal_id} 不在合法数据中"
                issues.append(msg)
                fatal_issues.append(msg)

        for item in delivery_items:
            delivery_id = item.get("id", "")
            if delivery_id and delivery_id not in valid_delivery_ids:
                msg = f"配送商品 ID {delivery_id} 不在合法数据中"
                issues.append(msg)
                fatal_issues.append(msg)

        # 1b. action 引用校验 — FATAL
        valid_action_refs = {
            "book_activity": valid_activity_ids,
            "book_restaurant": valid_restaurant_ids,
            "book_drink": valid_drink_ids,
            "order_delivery": valid_delivery_ids,
            "order_deal": valid_deal_ids,
        }
        for action in actions:
            action_type = action.get("type", "")
            ref_id = action.get("ref_id", "")
            valid_set = valid_action_refs.get(action_type)
            if valid_set is None:
                msg = f"未知 action 类型: {action_type}"
                issues.append(msg)
                fatal_issues.append(msg)
            elif ref_id and ref_id not in valid_set:
                msg = f"action 引用非法: {action_type}/{ref_id}"
                issues.append(msg)
                fatal_issues.append(msg)

        # 2. 规划阶段不得有 booking_id/order_id — FATAL (system integrity)
        if "booking_id" in plan:
            msg = "规划阶段方案不应包含 booking_id"
            issues.append(msg)
            fatal_issues.append(msg)
        if "order_id" in plan:
            msg = "规划阶段方案不应包含 order_id"
            issues.append(msg)
            fatal_issues.append(msg)
        for action in actions:
            if action.get("booking_id") or action.get("order_id"):
                msg = "规划阶段 action 不应包含 booking_id/order_id"
                issues.append(msg)
                fatal_issues.append(msg)

        # 3. 儿童年龄校验 — RETRYABLE (planner can swap activity)
        intent = state.get("intent", {})
        if intent.get("party_type") == "family_with_child" or intent.get("child_age"):
            child_age = intent.get("child_age")
            if child_age and activity:
                age_min = activity.get("suitable_age_min", 0)
                age_max = activity.get("suitable_age_max", 99)
                if not (age_min <= child_age <= age_max):
                    msg = f"家庭场景中活动「{activity.get('name')}」不适合{child_age}岁儿童"
                    issues.append(msg)
                    retryable_issues.append(msg)

    passed = len(issues) == 0
    blocked = len(fatal_issues) > 0
    retryable = len(retryable_issues) > 0 and not blocked

    feedback = ""
    if retryable_issues:
        feedback = "请重新规划，注意以下问题: " + "; ".join(retryable_issues)
    if fatal_issues:
        feedback = "致命错误: " + "; ".join(fatal_issues)

    result = {
        "passed": passed,
        "blocked": blocked,
        "retryable": retryable,
        "issues": issues,
        "retryable_issues": retryable_issues,
        "fatal_issues": fatal_issues,
        "feedback": feedback,
    }

    state["guardrail_feedback"] = result if retryable else {}
    return result


def _plan_restaurants(plan: dict) -> list[dict]:
    entries = plan.get("meal_restaurants") or []
    restaurants = [
        entry.get("restaurant") for entry in entries
        if isinstance(entry, dict) and entry.get("restaurant")
    ]
    if restaurants:
        return restaurants
    restaurant = plan.get("restaurant")
    return [restaurant] if restaurant else []


def _check_message_guardrails(state: AgentState) -> dict:
    """执行阶段 guardrails: 转发消息内容校验"""
    issues: list[str] = []
    retryable_issues: list[str] = []
    fatal_issues: list[str] = []

    # share_message 内容校验 — RETRYABLE (message_llm can regenerate)
    share_msg = state.get("share_message") or ""
    forbidden = ["真实支付成功", "已真实下单", "已真实预约", "保证有位", "保证免排队"]
    for phrase in forbidden:
        if phrase in share_msg:
            msg = f"share_message 包含违规内容: {phrase}"
            issues.append(msg)
            retryable_issues.append(msg)

    # 检查是否包含 Demo/Mock 声明
    disclosure_words = ["Demo", "Mock", "模拟", "非真实", "演示"]
    if share_msg and not any(word in share_msg for word in disclosure_words):
        msg = "share_message 缺少 Demo/Mock 声明"
        issues.append(msg)
        retryable_issues.append(msg)

    # 执行结果中的系统级错误 — FATAL
    execution = state.get("execution_result") or {}
    if execution.get("errors"):
        for err in execution["errors"]:
            if isinstance(err, str) and ("系统错误" in err or "API" in err or "不可用" in err):
                msg = f"执行系统错误: {err}"
                issues.append(msg)
                fatal_issues.append(msg)

    passed = len(issues) == 0
    blocked = len(fatal_issues) > 0
    retryable = len(retryable_issues) > 0 and not blocked

    feedback = ""
    if retryable_issues:
        feedback = "请重写转发消息，注意以下问题: " + "; ".join(retryable_issues)

    result = {
        "passed": passed,
        "blocked": blocked,
        "retryable": retryable,
        "issues": issues,
        "retryable_issues": retryable_issues,
        "fatal_issues": fatal_issues,
        "feedback": feedback,
    }

    state["guardrail_feedback"] = result if retryable else {}
    return result
