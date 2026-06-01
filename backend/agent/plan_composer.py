"""LLM 方案组合器 - 基于已检索候选生成可执行 JSON"""

import json
from typing import Any

from backend.agent.schemas import Intent
from backend.llm.deepseek_client import deepseek_client, LLMResult


COMPOSER_SYSTEM_PROMPT = """你是本地生活短时活动规划 Agent 的方案组合器。
你不能搜索外部信息，只能使用输入 candidates 中给出的候选 ID。

请输出严格 JSON：
{
  "plans": [
    {
      "plan_id": "plan_001",
      "title": "简短标题",
      "selected_refs": {
        "activity_id": "act_001 或 null",
        "restaurant_id": "rest_001 或 null",
        "meal_restaurant_ids": {"lunch": "rest_001 或 null", "dinner": "rest_002 或 null"},
        "drink_id": "drink_001 或 null",
        "delivery_item_ids": ["delivery_001"]
      },
      "timeline": [
        {"time": "14:00", "type": "activity|restaurant|drink|delivery|transit", "ref_id": "候选ID或空", "title": "展示标题", "duration_min": 60}
      ],
      "actions": [
        {"action_id": "a1", "type": "book_activity|book_restaurant|book_drink|order_delivery|order_deal", "ref_id": "候选ID", "scheduled_time": "14:00", "quantity": 1, "target_ref_id": "rest_001 或 null"}
      ],
      "recommend_reasons": ["为什么适合"],
      "risk_tips": ["需要用户知道的风险"]
    }
  ]
}

规则：
- 只使用 candidates 中出现的 ID，不允许编造 POI、商品、团购券或订单号。
- planning 阶段只能给 actions，不允许出现 booking_id/order_id。
- 时间线要符合用户时间段：lunch 从11:30左右开始，afternoon 可从13:30或用户 start_time 开始，dinner/evening 从17:30以后开始，night 从20:30以后开始。
- 如果 intent.meal_slots 同时包含 lunch 和 dinner，必须分别选择午餐/晚餐餐厅；有 2 个以上可用餐厅时，午餐和晚餐不要使用同一个 restaurant_id，且优先不同菜系。
- 如果输入包含 revision_patch.locked_slots，锁定槽位必须保留：activity/drink/meal:lunch/meal:dinner 对应 ID 不能被替换或遗漏；如果 revision_patch.remove_slots 包含某槽位，该槽位不能再出现在方案里。
- 多轮修改只改用户明确修改的槽位；不要把“带上某人/人数变化/关系变化”自动理解成新增配送商品、换活动或换餐厅。
- 根据 party_type 做组合：family_with_child 优先儿童年龄、亲子友好、低卡/健康和少排队；family_elder 优先少走路、少排队、安静和清淡；friends 优先社交、拍照、唱歌/喝酒；couple 优先氛围、拍照和品质；business 优先安静、稳定可订和品质；solo 优先近、轻量和性价比。
- 只有用户明确要求外卖/闪送/跑腿或可配送商品时，才选择 delivery_item_ids 并生成 order_delivery；不要从约会、纪念日、带配偶等语境自动推断具体商品。
- 外卖/闪送 action 要包含 order_delivery，target_ref_id 优先选择餐厅，其次活动地点；scheduled_time 是希望送达或下单时间。
- 如果某个候选不可预约，也可以放进方案，但 actions 中不要为它生成预约动作，并在 risk_tips 说明。
- 最多输出4个方案。
"""


async def compose_plan_specs_with_llm(
    *,
    message: str,
    intent: Intent,
    user_memory: dict | None,
    tag_result: dict,
    weather: dict | None,
    candidates: dict[str, list[dict[str, Any]]],
    revision_patch: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """调用 LLM 组合方案，返回经过本地 ID 校验的 plan specs。"""
    if not deepseek_client.available:
        return [], None

    payload = {
        "user_message": message,
        "intent": _compact_intent(intent),
        "user_memory": _compact_memory(user_memory),
        "tag_result": _compact_tag_result(tag_result),
        "revision_patch": _compact_revision_patch(revision_patch),
        "weather": _compact_weather(weather),
        "candidates": {
            "activities": _compact_items(candidates.get("activities", []), "activity"),
            "restaurants": _compact_items(candidates.get("restaurants", []), "restaurant"),
            "drinks": _compact_items(candidates.get("drinks", []), "drink"),
            "delivery_items": _compact_items(candidates.get("delivery_items", []), "delivery"),
        },
    }
    messages = [
        {"role": "system", "content": COMPOSER_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    result: LLMResult = await deepseek_client.chat_json(messages, temperature=0.2)
    if not result.ok:
        return [], f"LLM 组合失败，已使用本地规则: {result.error}"
    if not isinstance(result.json_data, dict):
        return [], "LLM 组合结果不是 JSON object，已使用本地规则"

    specs = result.json_data.get("plans", [])
    if not isinstance(specs, list):
        return [], "LLM 组合结果缺少 plans 数组，已使用本地规则"

    valid_specs, issues = validate_plan_specs(specs, candidates, revision_patch=revision_patch)
    if not valid_specs:
        suffix = f": {'; '.join(issues[:3])}" if issues else ""
        return [], f"LLM 组合结果未通过本地校验，已使用本地规则{suffix}"

    warning = None
    if issues:
        warning = "LLM 部分动作/引用被本地校验丢弃: " + "; ".join(issues[:3])
    return valid_specs, warning


def validate_plan_specs(
    specs: list[dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
    revision_patch: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """校验 LLM 输出中所有引用都来自候选集合。"""
    id_domain = _build_id_domain(candidates)
    issues: list[str] = []
    valid: list[dict[str, Any]] = []

    for idx, raw in enumerate(specs[:4]):
        if not isinstance(raw, dict):
            issues.append(f"plan[{idx}] 不是对象")
            continue
        spec = dict(raw)
        refs = spec.get("selected_refs") if isinstance(spec.get("selected_refs"), dict) else {}
        cleaned_refs = {
            "activity_id": _valid_ref(refs.get("activity_id"), id_domain, "activity", issues),
            "restaurant_id": _valid_ref(refs.get("restaurant_id"), id_domain, "restaurant", issues),
            "meal_restaurant_ids": {},
            "drink_id": _valid_ref(refs.get("drink_id"), id_domain, "drink", issues),
            "delivery_item_ids": [],
        }
        raw_meal_refs = refs.get("meal_restaurant_ids") if isinstance(refs.get("meal_restaurant_ids"), dict) else {}
        for meal in ("lunch", "dinner"):
            meal_ref = _valid_ref(raw_meal_refs.get(meal), id_domain, "restaurant", issues)
            if meal_ref:
                cleaned_refs["meal_restaurant_ids"][meal] = meal_ref
        for item_id in refs.get("delivery_item_ids") or []:
            valid_id = _valid_ref(item_id, id_domain, "delivery", issues)
            if valid_id:
                cleaned_refs["delivery_item_ids"].append(valid_id)
        spec["selected_refs"] = cleaned_refs

        timeline = []
        for item in spec.get("timeline") or []:
            if not isinstance(item, dict):
                continue
            ref_id = str(item.get("ref_id") or "")
            step_type = _normalize_timeline_type(item.get("type"))
            if ref_id and ref_id not in id_domain:
                issues.append(f"timeline 引用了未知 ID: {ref_id}")
                continue
            if ref_id and not _timeline_type_matches(step_type, id_domain.get(ref_id)):
                issues.append(f"timeline 类型与 ID 不匹配: {step_type}/{ref_id}")
                continue
            timeline.append({
                "time": str(item.get("time") or ""),
                "type": step_type,
                "ref_id": ref_id,
                "title": str(item.get("title") or ""),
                "duration_min": int(item.get("duration_min") or 0),
            })
        spec["timeline"] = timeline

        actions = []
        for action in spec.get("actions") or []:
            if not isinstance(action, dict):
                continue
            action_type = str(action.get("type") or "")
            ref_id = str(action.get("ref_id") or "")
            if not _action_ref_matches(action_type, ref_id, id_domain):
                issues.append(f"action 引用不合法: {action_type}/{ref_id}")
                continue
            target_ref_id = action.get("target_ref_id")
            if target_ref_id and target_ref_id not in id_domain:
                issues.append(f"action target_ref_id 未知: {target_ref_id}")
                target_ref_id = None
            actions.append({
                "action_id": str(action.get("action_id") or f"action_{len(actions) + 1}"),
                "type": action_type,
                "ref_id": ref_id,
                "scheduled_time": str(action.get("scheduled_time") or ""),
                "quantity": int(action.get("quantity") or 1),
                "target_ref_id": target_ref_id,
            })
        spec["actions"] = actions

        has_any_ref = any([
            cleaned_refs["activity_id"],
            cleaned_refs["restaurant_id"],
            cleaned_refs["meal_restaurant_ids"],
            cleaned_refs["drink_id"],
            cleaned_refs["delivery_item_ids"],
        ])
        if not has_any_ref:
            issues.append(f"plan[{idx}] 没有任何合法候选引用")
            continue
        locked_issue = _locked_ref_issue(spec, revision_patch)
        if locked_issue:
            issues.append(f"plan[{idx}] {locked_issue}")
            continue
        valid.append(spec)

    return valid, issues


def _compact_items(items: list[dict[str, Any]], domain: str) -> list[dict[str, Any]]:
    keys = [
        "id", "name", "category", "sub_category", "area", "distance_km", "avg_price",
        "tags", "rating", "queue_minutes", "available", "available_slots", "bookable",
        "business_hours", "recommended_duration_min", "risk",
        "child_friendly", "suitable_age_min", "suitable_age_max", "low_calorie_options",
        "estimated_delivery_min", "prep_time_min", "delivery_fee", "available_areas",
        "merchant_name",
    ]
    compacted = []
    for item in items[:4]:
        entry = {k: item.get(k) for k in keys if k in item}
        if "tags" in entry:
            entry["tags"] = entry["tags"][:6]
        if "available_slots" in entry:
            entry["available_slots"] = entry["available_slots"][:5]
        if "available_areas" in entry:
            entry["available_areas"] = entry["available_areas"][:4]
        if item.get("description"):
            entry["description"] = str(item["description"])[:60]
        entry["domain"] = domain
        compacted.append(entry)
    return compacted


def _compact_intent(intent: Intent) -> dict[str, Any]:
    data = intent.model_dump()
    keep = [
        "scene", "party_type", "tags", "date", "time_window", "start_time", "duration_hours", "people_count",
        "meal_slots",
        "radius_km", "budget_per_person", "food_preferences",
        "activity_preferences", "drink_preferences", "delivery_preferences",
        "child_age", "needs_low_calorie", "needs_photo_spot", "needs_quiet",
        "needs_less_walking", "avoid_queue_minutes",
    ]
    return {k: data.get(k) for k in keep}


def _compact_memory(user_memory: dict | None) -> dict[str, Any]:
    if not user_memory:
        return {}
    prefs = user_memory.get("preferences", {})
    return {
        "preferences": {
            "child_age": prefs.get("child_age"),
            "max_distance_km": prefs.get("max_distance_km"),
            "max_queue_minutes": prefs.get("max_queue_minutes"),
            "cuisine_likes": prefs.get("cuisine_likes", [])[:4],
            "spouse_diet": prefs.get("spouse_diet"),
        }
    }


def _compact_tag_result(tag_result: dict) -> dict[str, Any]:
    return {
        "domains": tag_result.get("domains", []),
        "domain_required": tag_result.get("domain_required", {}),
        "domain_tags": tag_result.get("domain_tags", {}),
        "domain_sub_categories": tag_result.get("domain_sub_categories", {}),
    }


def _compact_revision_patch(revision_patch: dict[str, Any] | None) -> dict[str, Any]:
    if not revision_patch:
        return {}
    locked_slots = {}
    for slot, info in (revision_patch.get("locked_slots") or {}).items():
        item = (info or {}).get("item") or {}
        locked_slots[slot] = {
            "id": item.get("id"),
            "name": item.get("name"),
            "domain": info.get("domain"),
            "time": info.get("time"),
        }
    return {
        "keep_slots": revision_patch.get("keep_slots", []),
        "replace_slots": revision_patch.get("replace_slots", []),
        "add_slots": revision_patch.get("add_slots", []),
        "remove_slots": revision_patch.get("remove_slots", []),
        "locked_slots": locked_slots,
        "intent_patch": revision_patch.get("intent_patch", {}),
    }


def _compact_weather(weather: dict | None) -> dict[str, Any]:
    if not weather:
        return {}
    keep = ["date", "location", "condition", "temperature", "outdoor_suitable", "risk"]
    return {k: weather.get(k) for k in keep if k in weather}


def _build_id_domain(candidates: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, domain in [
        ("activities", "activity"),
        ("restaurants", "restaurant"),
        ("drinks", "drink"),
        ("delivery_items", "delivery"),
    ]:
        for item in candidates.get(key, []):
            item_id = item.get("id")
            if item_id:
                mapping[item_id] = domain
    return mapping


def _locked_ref_issue(spec: dict[str, Any], revision_patch: dict[str, Any] | None) -> str | None:
    if not revision_patch:
        return None
    locked_slots = revision_patch.get("locked_slots") or {}
    refs = spec.get("selected_refs") or {}
    timeline_ref_ids = {
        item.get("ref_id")
        for item in spec.get("timeline") or []
        if item.get("ref_id")
    }
    for slot, info in locked_slots.items():
        item_id = ((info or {}).get("item") or {}).get("id")
        if not item_id:
            continue
        if slot == "activity" and refs.get("activity_id") != item_id and item_id not in timeline_ref_ids:
            return f"缺少锁定活动 {item_id}"
        if slot == "drink" and refs.get("drink_id") != item_id and item_id not in timeline_ref_ids:
            return f"缺少锁定饮品 {item_id}"
        if slot.startswith("meal:"):
            meal = slot.split(":", 1)[1]
            meal_refs = refs.get("meal_restaurant_ids") or {}
            if refs.get("restaurant_id") != item_id and meal_refs.get(meal) != item_id and item_id not in timeline_ref_ids:
                return f"缺少锁定餐厅 {item_id}"
    return None


def _valid_ref(
    ref_id: Any,
    id_domain: dict[str, str],
    expected_domain: str,
    issues: list[str],
) -> str | None:
    if not ref_id:
        return None
    ref = str(ref_id)
    if id_domain.get(ref) != expected_domain:
        issues.append(f"引用不合法: {expected_domain}/{ref}")
        return None
    return ref


def _normalize_timeline_type(value: Any) -> str:
    mapping = {
        "play": "activity",
        "activity": "activity",
        "eat": "restaurant",
        "restaurant": "restaurant",
        "drink": "drink",
        "delivery": "delivery",
        "flash": "delivery",
        "takeout": "delivery",
        "transit": "transit",
    }
    return mapping.get(str(value or ""), "activity")


def _timeline_type_matches(step_type: str, domain: str | None) -> bool:
    if step_type == "transit":
        return True
    return {
        "activity": "activity",
        "restaurant": "restaurant",
        "drink": "drink",
        "delivery": "delivery",
    }.get(step_type) == domain


def _action_ref_matches(action_type: str, ref_id: str, id_domain: dict[str, str]) -> bool:
    expected = {
        "book_activity": "activity",
        "book_restaurant": "restaurant",
        "book_drink": "drink",
        "order_delivery": "delivery",
        "order_deal": "deal",
    }.get(action_type)
    if expected == "deal":
        return bool(ref_id)
    return bool(expected and id_domain.get(ref_id) == expected)
