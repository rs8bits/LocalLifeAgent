"""LLM Reflection - 语义层方案质量检查"""

import json
from typing import Any

from backend.llm.deepseek_client import deepseek_client, LLMResult


REFLECTION_SYSTEM_PROMPT = """你是本地生活规划 Agent 的反思检查器。
你只检查“方案是否满足用户意图”，不能编造新的 POI、订单或库存。

请严格输出 JSON：
{
  "plan_results": [
    {
      "plan_id": "plan_001",
      "passed": true,
      "issues": [],
      "suggestions": []
    }
  ],
  "issues": [],
  "suggestions": []
}

检查重点：
- 用户明确要求的吃/喝/玩/外卖闪送是否都被覆盖。
- 标签是否语义匹配，例如“唱歌”应对应 KTV/唱歌类活动，“喝酒”应对应酒吧/精酿类饮品。
- 时间线是否自然，配送送达时间是否和餐厅/活动匹配。
- 家庭场景是否照顾孩子年龄和低卡/减脂需求。
- 朋友场景是否适合多人社交、拍照、聚会等偏好。

只指出语义和体验问题；安全、ID 合法性和支付承诺由 Guardrails 处理。
"""


async def run_llm_reflection(state: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """调用 LLM 做语义反思。失败返回 (None, reason)。"""
    if not deepseek_client.available:
        return None, None

    payload = {
        "user_message": state.get("user_message", ""),
        "intent": _compact_intent(state.get("intent", {})),
        "tag_result": _compact_tag_result(state.get("tag_resolve_result", {})),
        "plans": [_compact_plan(plan) for plan in state.get("plans", [])[:4]],
    }
    messages = [
        {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    result: LLMResult = await deepseek_client.chat_json(messages, temperature=0.1)
    if not result.ok:
        return None, result.error
    if not isinstance(result.json_data, dict):
        return None, "LLM Reflection 输出不是 JSON object"
    return _validate_reflection_result(result.json_data), None


def _validate_reflection_result(data: dict[str, Any]) -> dict[str, Any]:
    plan_results = []
    for item in data.get("plan_results", [])[:4]:
        if not isinstance(item, dict):
            continue
        plan_results.append({
            "plan_id": str(item.get("plan_id", "")),
            "passed": bool(item.get("passed", True)),
            "issues": [str(x) for x in item.get("issues", [])[:6]],
            "suggestions": [str(x) for x in item.get("suggestions", [])[:6]],
        })
    issues = [str(x) for x in data.get("issues", [])[:10]]
    suggestions = [str(x) for x in data.get("suggestions", [])[:10]]
    return {
        "passed": all(item["passed"] for item in plan_results) and not issues,
        "plan_results": plan_results,
        "issues": issues,
        "suggestions": suggestions,
    }


def _compact_intent(intent: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "scene", "time_window", "duration_hours", "people_count", "radius_km",
        "food_preferences", "activity_preferences", "drink_preferences",
        "delivery_preferences", "child_age", "needs_low_calorie",
        "needs_photo_spot", "avoid_queue_minutes",
    ]
    return {k: intent.get(k) for k in keep}


def _compact_tag_result(tag_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain_specs": tag_result.get("domain_specs", []),
        "domain_required": tag_result.get("domain_required", {}),
    }


def _compact_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": plan.get("plan_id"),
        "title": plan.get("title"),
        "timeline": plan.get("timeline", []),
        "activity": _compact_item(plan.get("activity")),
        "restaurant": _compact_item(plan.get("restaurant")),
        "drink": _compact_item(plan.get("drink")),
        "delivery_items": [_compact_item(item) for item in plan.get("delivery_items", [])],
        "actions": plan.get("actions", []),
        "risk_tips": plan.get("risk_tips", []),
        "recommend_reasons": plan.get("recommend_reasons", []),
    }


def _compact_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    keep = [
        "id", "name", "category", "sub_category", "area", "tags", "distance_km",
        "queue_minutes", "available", "bookable", "business_hours",
        "recommended_duration_min", "estimated_delivery_min", "risk",
        "child_friendly", "suitable_age_min", "suitable_age_max",
        "low_calorie_options",
    ]
    compact = {k: item.get(k) for k in keep if k in item}
    if "tags" in compact:
        compact["tags"] = compact["tags"][:6]
    return compact
