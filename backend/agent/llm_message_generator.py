"""LLM 转发消息生成器 - LLM 生成自然转发文案，规则兜底"""

from typing import Any

from backend.llm.deepseek_client import deepseek_client
from backend.agent.message_generator import generate_share_message

MESSAGE_SYSTEM_PROMPT = """你是一个本地生活助手的转发消息生成模块。根据执行结果生成一段自然的转发文案。

## 核心要求
1. 语气自然，像朋友之间的消息，不像固定模板。
2. 必须如实反映执行状态：
   - 全部成功：说明已完成哪些 Mock 预约/订单
   - 部分成功：说明哪些成功、哪些失败
   - 失败：如实说明，不要假装完成
3. **必须明确说明这是 Demo/Mock，不产生真实交易。** 例如加一句"以上为 Demo 模拟结果，非真实交易"。
4. **绝对禁止出现：**
   - "真实支付成功"
   - "已真实下单"
   - "保证有位"
   - "保证免排队"
   - 编造真实订单号/真实核销码
5. 文案长度控制在 2-5 句，简洁自然。
6. 如果 guardrail_feedback 有内容，说明上一版本被拦截，请根据反馈重写。

## 输出 JSON 格式
{
  "share_message": "转发文案",
  "tone": "family|friends|general",
  "summary": "简短摘要",
  "warnings": ["这是 Demo Mock，不产生真实交易"]
}"""


async def generate_share_message_llm(
    original_user_message: str,
    intent: dict[str, Any],
    selected_plan: dict[str, Any],
    execution_result: dict[str, Any],
    guardrail_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """LLM 生成转发消息，失败时规则兜底。

    返回:
        {
            "share_message": str,
            "tone": str,
            "summary": str,
            "warnings": list[str],
        }
    """
    bookings = execution_result.get("bookings", [])
    orders = execution_result.get("orders", [])

    if not deepseek_client.available:
        return _rule_fallback(selected_plan, intent, bookings, orders)

    feedback_text = ""
    if guardrail_feedback:
        issues = guardrail_feedback.get("issues", []) or guardrail_feedback.get("retryable_issues", [])
        feedback_content = guardrail_feedback.get("feedback", "")
        feedback_text = f"上一版被拦截。问题: {'; '.join(issues)}。建议: {feedback_content}"

    user_prompt = f"""原始用户输入: {original_user_message}
意图: {intent}
选中方案: {selected_plan.get("title", "")}
执行状态: {execution_result.get("status", "unknown")}
预约结果: {bookings}
订单结果: {orders}
{feedback_text}"""

    try:
        messages = [
            {"role": "system", "content": MESSAGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        resp = await deepseek_client.chat_json(messages, temperature=0.3)
        if resp.ok and resp.json_data:
            result = resp.json_data
            # 后置规则过滤：强制替换被禁止的短语
            share_msg = result.get("share_message", "")
            share_msg = _sanitize_forbidden_phrases(share_msg)
            result["share_message"] = share_msg
            return result
    except Exception:
        pass

    return _rule_fallback(selected_plan, intent, bookings, orders)


def _rule_fallback(plan: dict, intent: dict, bookings: list, orders: list) -> dict[str, Any]:
    """规则兜底"""
    msg = generate_share_message(plan=plan, intent=intent, bookings=bookings, orders=orders)
    return {
        "share_message": msg,
        "tone": intent.get("scene", "general"),
        "summary": "已生成转发消息（规则兜底）",
        "warnings": ["这是 Demo Mock，不产生真实交易"],
    }


def _sanitize_forbidden_phrases(text: str) -> str:
    """后置清理被禁止的短语"""
    forbidden = [
        ("真实支付成功", "Mock 支付成功"),
        ("已真实下单", "已提交 Mock 订单"),
        ("已真实预约", "已提交 Mock 预约"),
        ("保证有位", "已提交订位请求"),
        ("保证免排队", "已提交排队请求"),
    ]
    for bad, replacement in forbidden:
        text = text.replace(bad, replacement)
    return text
