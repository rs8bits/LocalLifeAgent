"""多轮方案修改：把自然语言修改转成结构化 patch。"""

from __future__ import annotations

import re
from typing import Any

from backend.agent.intent_parser import _extract_people_count
from backend.agent.semantic_rules import (
    activity_aliases_for_preference,
    activity_preference_from_message,
    activity_preferences_from_item,
    delivery_aliases_for_preference,
    delivery_tags_for_preferences,
    extract_delivery_preferences,
    item_matches_activity_preference,
    negated_activity_preferences,
    negated_delivery_preferences,
    negates_delivery,
    ordered_unique,
    requests_activity_change,
    requests_activity_keep,
    strip_aliases,
)


DINNER_REPLACE_RE = re.compile(r"(只)?(替换|更换|换|改)(一下)?(晚饭|晚餐|晚上吃饭)|((晚饭|晚餐).*(换|改))")
LUNCH_REPLACE_RE = re.compile(r"(只)?(替换|更换|换|改)(一下)?(中饭|午饭|午餐)|((中饭|午饭|午餐).*(换|改))")
MEAL_REPLACE_RE = re.compile(
    r"(只)?(替换|更换|换|改)(一下|个|一家)?(餐厅|饭店|餐馆|馆子|吃饭|吃的|这家店)"
    r"|((餐厅|饭店|餐馆|馆子|吃饭|吃的|这家店).{0,8}(替换|更换|换|改))"
)
MEAL_KEEP_RE = re.compile(
    r"(不要动|别动|保留|继续|保持).{0,8}(餐厅|饭店|餐馆|馆子|吃饭|午餐|晚餐)"
    r"|((餐厅|饭店|餐馆|馆子|午餐|晚餐).{0,8}(不变|别动|不要动|挺好))"
)


def build_revision_message(session: dict[str, Any], revision_message: str) -> str:
    """构造用于重新规划的消息。

    新消息保留上一轮原始需求，同时声明“未明确修改的部分继续保留”。
    具体锁定和局部替换由 build_revision_patch 提供结构化约束。
    """
    previous_message = str(session.get("message") or "").strip()
    revision = revision_message.strip()
    if not previous_message:
        return revision

    cleaned_previous = previous_message
    if _negates_child(revision):
        cleaned_previous = _remove_child_mentions(cleaned_previous)
    cleaned_previous = _remove_negated_delivery_mentions(cleaned_previous, revision)
    cleaned_previous = _remove_negated_activity_mentions(cleaned_previous, revision)

    parts = [
        f"上一轮需求：{cleaned_previous}",
        f"用户本轮修改：{revision}",
        "请保留上一轮中用户未明确修改的安排，只调整本轮明确提出的部分。",
    ]
    return "。".join(part for part in parts if part)


def build_revision_patch(
    session: dict[str, Any],
    revision_message: str,
    base_plan_id: str | None = None,
) -> dict[str, Any]:
    """将本轮修改解析成可传给 planner/composer 的结构化约束。"""
    revision = revision_message.strip()
    base_plan = select_base_plan(session, base_plan_id)
    base_slots = _extract_plan_slots(base_plan)
    replace_slots = _detect_replace_slots(revision, base_slots)
    add_slots = _detect_add_slots(revision)
    remove_slots = _detect_remove_slots(revision, add_slots)
    keep_slots = _detect_keep_slots(revision, base_slots)
    intent_patch = _build_intent_patch(session, revision, base_slots, add_slots, replace_slots, remove_slots)
    activity_pref = _activity_preference_from_message(revision)
    if activity_pref and base_slots.get("activity"):
        base_activity = base_slots["activity"].get("item") or {}
        if _item_matches_activity_preference(base_activity, activity_pref):
            keep_slots.add("activity")
        elif _is_positive_activity_preference(revision, activity_pref):
            replace_slots.add("activity")
            keep_slots.discard("activity")

    if _should_lock_activity(revision, base_slots, replace_slots, keep_slots):
        keep_slots.add("activity")

    only_replace_slots = _only_replace_slots(revision, replace_slots)
    if only_replace_slots:
        for slot in base_slots:
            if slot not in only_replace_slots:
                keep_slots.add(slot)
    elif _should_preserve_unchanged_slots(revision, add_slots, replace_slots, remove_slots, keep_slots, intent_patch):
        for slot, slot_info in base_slots.items():
            if slot in replace_slots or slot in remove_slots:
                continue
            if _negates_child(revision) and _is_child_oriented_item(slot_info.get("item") or {}):
                continue
            keep_slots.add(slot)

    locked_slots = {
        slot: value
        for slot, value in base_slots.items()
        if slot in keep_slots and slot not in replace_slots and slot not in remove_slots
    }

    return {
        "mode": "edit_existing_plan",
        "base_plan_id": (base_plan or {}).get("plan_id") or base_plan_id,
        "revision_message": revision,
        "keep_slots": sorted(keep_slots),
        "replace_slots": sorted(replace_slots),
        "add_slots": sorted(add_slots),
        "remove_slots": sorted(remove_slots),
        "locked_slots": locked_slots,
        "locked_poi_ids": [
            slot_info["item"]["id"]
            for slot_info in locked_slots.values()
            if slot_info.get("item", {}).get("id")
        ],
        "intent_patch": intent_patch,
        "base_plan_summary": _plan_summary(base_plan),
    }


def select_base_plan(session: dict[str, Any], base_plan_id: str | None = None) -> dict[str, Any] | None:
    plans = session.get("plans") or []
    if base_plan_id:
        found = next((plan for plan in plans if plan.get("plan_id") == base_plan_id), None)
        if found:
            return found
    selected_id = session.get("selected_plan_id")
    if selected_id:
        found = next((plan for plan in plans if plan.get("plan_id") == selected_id), None)
        if found:
            return found
    return plans[0] if plans else None


def infer_base_plan_id(session: dict[str, Any], revision_message: str) -> str | None:
    """从“第一个/桌游方案”这类文本中推断要修改的方案。"""
    plans = session.get("plans") or []
    if not plans:
        return None
    ordinal_patterns = [
        (0, [r"第\s*1\s*个方案", r"第\s*一\s*个方案", r"方案\s*1", r"方案\s*一"]),
        (1, [r"第\s*2\s*个方案", r"第\s*二\s*个方案", r"方案\s*2", r"方案\s*二"]),
        (2, [r"第\s*3\s*个方案", r"第\s*三\s*个方案", r"方案\s*3", r"方案\s*三"]),
    ]
    for index, patterns in ordinal_patterns:
        if index < len(plans) and any(re.search(pattern, revision_message) for pattern in patterns):
            return plans[index].get("plan_id")
    preferred_activity = _activity_preference_from_message(revision_message)
    if preferred_activity:
        found = _find_plan_by_activity_preference(plans, preferred_activity)
        if found:
            return found.get("plan_id")
    return None


def apply_revision_intent_patch(intent: Any, revision_patch: dict[str, Any] | None) -> Any:
    """把结构化 patch 合入 Intent；intent 是 pydantic 对象，原地修改。"""
    if not revision_patch:
        return intent
    patch = revision_patch.get("intent_patch") or {}
    meal_slots = patch.get("meal_slots")
    if isinstance(meal_slots, list):
        intent.meal_slots = _ordered_unique([*(intent.meal_slots or []), *meal_slots], ["lunch", "dinner"])
        if {"lunch", "dinner"}.issubset(set(intent.meal_slots)) and not intent.start_time:
            intent.time_window = "lunch"
    for pref in patch.get("drink_preferences") or []:
        if pref not in intent.drink_preferences:
            intent.drink_preferences.append(pref)
    remove_delivery = set(patch.get("remove_delivery_preferences") or [])
    if "delivery" in set(revision_patch.get("remove_slots") or []):
        remove_delivery.add("*")
    if "*" in remove_delivery:
        intent.delivery_preferences = []
    elif remove_delivery:
        intent.delivery_preferences = [
            pref for pref in intent.delivery_preferences
            if pref not in remove_delivery
        ]
    if remove_delivery:
        intent.tags = [
            tag for tag in intent.tags
            if tag not in delivery_tags_for_preferences(remove_delivery)
        ]
    for pref in patch.get("delivery_preferences") or []:
        if pref not in intent.delivery_preferences:
            intent.delivery_preferences.append(pref)
    remove_activity = set(patch.get("remove_activity_preferences") or [])
    if "activity" in set(revision_patch.get("remove_slots") or []):
        remove_activity.add("*")
    if "*" in remove_activity:
        intent.activity_preferences = []
    elif remove_activity:
        intent.activity_preferences = [
            pref for pref in intent.activity_preferences
            if pref not in remove_activity
        ]
    for pref in patch.get("activity_preferences") or []:
        if pref not in intent.activity_preferences:
            intent.activity_preferences.append(pref)
    for tag in patch.get("tags") or []:
        if tag not in intent.tags:
            intent.tags.append(tag)
    people_count = patch.get("people_count")
    if isinstance(people_count, int) and people_count > 0:
        intent.people_count = people_count
    if patch.get("clear_child_context"):
        intent.child_age = None
        intent.companions = [c for c in intent.companions if c.get("role") != "child"]
        intent.tags = [tag for tag in intent.tags if tag != "亲子"]
        if intent.party_type == "family_with_child":
            intent.party_type = "general"
            intent.scene = "general"
    return intent


def _extract_plan_slots(plan: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not plan:
        return {}
    slots: dict[str, dict[str, Any]] = {}
    activity = plan.get("activity")
    if activity:
        slots["activity"] = _slot_info("activity", activity, _timeline_time_for(plan, "activity", activity.get("id")))
    drink = plan.get("drink")
    if drink:
        slots["drink"] = _slot_info("drink", drink, _timeline_time_for(plan, "drink", drink.get("id")))

    meal_entries = plan.get("meal_restaurants") or []
    for entry in meal_entries:
        if not isinstance(entry, dict):
            continue
        meal = entry.get("meal")
        restaurant = entry.get("restaurant")
        if meal in {"lunch", "dinner"} and restaurant:
            slots[f"meal:{meal}"] = _slot_info(
                f"meal:{meal}",
                restaurant,
                entry.get("time") or _timeline_time_for(plan, "restaurant", restaurant.get("id")),
                label=entry.get("label"),
            )

    restaurant = plan.get("restaurant")
    if restaurant and not any(slot.startswith("meal:") for slot in slots):
        meal = _meal_from_time(_timeline_time_for(plan, "restaurant", restaurant.get("id"))) or "dinner"
        slots[f"meal:{meal}"] = _slot_info(
            f"meal:{meal}",
            restaurant,
            _timeline_time_for(plan, "restaurant", restaurant.get("id")),
        )
    return slots


def _slot_info(slot: str, item: dict[str, Any], time: str | None, label: str | None = None) -> dict[str, Any]:
    domain = "restaurant" if slot.startswith("meal:") else slot
    return {
        "slot": slot,
        "domain": domain,
        "time": time,
        "label": label,
        "item": item,
    }


def _timeline_time_for(plan: dict[str, Any], slot_type: str, poi_id: str | None = None) -> str | None:
    for item in plan.get("timeline") or []:
        if item.get("type") != slot_type:
            continue
        if poi_id and item.get("poi_id") != poi_id:
            continue
        return item.get("time")
    return None


def _detect_replace_slots(message: str, base_slots: dict[str, dict[str, Any]] | None = None) -> set[str]:
    slots: set[str] = set()
    if DINNER_REPLACE_RE.search(message):
        slots.add("meal:dinner")
    if LUNCH_REPLACE_RE.search(message):
        slots.add("meal:lunch")
    if MEAL_REPLACE_RE.search(message) and not slots:
        slots.update(_base_meal_slots(base_slots) or {"meal:dinner"})
    if requests_activity_change(message):
        slots.add("activity")
    if any(kw in message for kw in ["换酒吧", "换喝的", "换饮品", "改酒吧", "改喝酒"]):
        slots.add("drink")
    return slots


def _detect_add_slots(message: str) -> set[str]:
    slots: set[str] = set()
    if _mentions_lunch(message):
        slots.add("meal:lunch")
    if _mentions_dinner(message):
        slots.add("meal:dinner")
    if "两顿" in message and "吃" in message:
        slots.update({"meal:lunch", "meal:dinner"})
    if any(kw in message for kw in ["喝酒", "精酿", "酒吧", "小酌", "啤酒"]):
        slots.add("drink")
    if _delivery_preferences_from_message(message):
        slots.add("delivery")
    return slots


def _detect_remove_slots(message: str, add_slots: set[str] | None = None) -> set[str]:
    slots: set[str] = set()
    if any(kw in message for kw in ["不要喝酒", "不喝酒", "别喝酒"]):
        slots.add("drink")
    if any(kw in message for kw in ["不要活动", "不安排活动"]):
        slots.add("activity")
    if _negates_delivery(message) and "delivery" not in (add_slots or set()):
        slots.add("delivery")
    return slots


def _detect_keep_slots(message: str, base_slots: dict[str, dict[str, Any]] | None = None) -> set[str]:
    slots: set[str] = set()
    if requests_activity_keep(message):
        slots.add("activity")
    if any(kw in message for kw in ["不要动午餐", "午餐不变", "保留午餐", "中饭不变"]):
        slots.add("meal:lunch")
    if any(kw in message for kw in ["不要动晚餐", "晚餐不变", "保留晚餐", "晚饭不变"]):
        slots.add("meal:dinner")
    if MEAL_KEEP_RE.search(message) and not any(slot.startswith("meal:") for slot in slots):
        slots.update(_base_meal_slots(base_slots))
    if any(kw in message for kw in ["不要动饮品", "饮品不变", "酒吧不变"]):
        slots.add("drink")
    return slots


def _only_replace_slots(message: str, replace_slots: set[str]) -> set[str]:
    if not replace_slots:
        return set()
    if "只" in message or "别的不要动" in message or "其他不变" in message:
        return set(replace_slots)
    return set()


def _should_lock_activity(
    message: str,
    base_slots: dict[str, dict[str, Any]],
    replace_slots: set[str],
    keep_slots: set[str],
) -> bool:
    if _requests_full_replan(message):
        return False
    if "activity" not in base_slots or "activity" in replace_slots:
        return False
    if "activity" in keep_slots:
        return True
    base_activity = base_slots["activity"].get("item") or {}
    if _negates_child(message) and _is_child_oriented_activity(base_activity):
        return False
    # 默认保留上一轮活动，除非用户明确说要换活动。
    return not requests_activity_change(message)


def _build_intent_patch(
    session: dict[str, Any],
    message: str,
    base_slots: dict[str, dict[str, Any]],
    add_slots: set[str],
    replace_slots: set[str],
    remove_slots: set[str],
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    people_count = _extract_people_count(message)
    if people_count is not None:
        patch["people_count"] = people_count

    meal_slots = [
        slot.split(":", 1)[1]
        for slot in sorted(add_slots | replace_slots)
        if slot.startswith("meal:")
    ]
    if meal_slots:
        meal_slots.extend(
            slot.split(":", 1)[1]
            for slot in base_slots
            if slot.startswith("meal:") and slot not in remove_slots
        )
    if meal_slots:
        patch["meal_slots"] = _ordered_unique(meal_slots, ["lunch", "dinner"])
    if any(kw in message for kw in ["喝酒", "精酿", "酒吧", "小酌", "啤酒"]):
        patch["drink_preferences"] = ["bar"]
        patch.setdefault("tags", []).append("聚会")
    negated_delivery = _negated_delivery_preferences(message)
    if negated_delivery:
        patch["remove_delivery_preferences"] = negated_delivery
    delivery_preferences = _delivery_preferences_from_message(message)
    if delivery_preferences:
        patch["delivery_preferences"] = delivery_preferences
        for pref in delivery_preferences:
            if pref not in {"外卖", "闪送"}:
                patch.setdefault("tags", []).append(pref)
    negated_activity = _negated_activity_preferences(message)
    if negated_activity:
        patch["remove_activity_preferences"] = negated_activity
    activity_pref = _activity_preference_from_message(message)
    if activity_pref:
        patch.setdefault("activity_preferences", []).append(activity_pref)
    if base_slots.get("activity") and "activity" not in replace_slots:
        item = base_slots["activity"]["item"]
        for preference in activity_preferences_from_item(item):
            if preference not in set(negated_activity):
                patch.setdefault("activity_preferences", []).append(preference)
    if _negates_child(message):
        patch["clear_child_context"] = True
    return patch


def _base_meal_slots(base_slots: dict[str, dict[str, Any]] | None) -> set[str]:
    return {
        slot for slot in (base_slots or {})
        if slot.startswith("meal:")
    }


def _negated_delivery_preferences(message: str) -> list[str]:
    return negated_delivery_preferences(message)


def _negated_activity_preferences(message: str) -> list[str]:
    return negated_activity_preferences(message)


def _mentions_lunch(message: str) -> bool:
    return bool(re.search(r"中饭|午饭|午餐|中午.*吃|中午.*用餐", message))


def _mentions_dinner(message: str) -> bool:
    return bool(re.search(r"晚饭|晚餐|晚上.*吃|晚上.*用餐|傍晚.*吃", message))


def _delivery_preferences_from_message(message: str) -> list[str]:
    return extract_delivery_preferences(message)


def _activity_preference_from_message(message: str) -> str | None:
    return activity_preference_from_message(message)


def _is_positive_activity_preference(message: str, preference: str) -> bool:
    return preference not in set(_negated_activity_preferences(message))


def _item_matches_activity_preference(item: dict[str, Any], preference: str) -> bool:
    return item_matches_activity_preference(item, preference)


def _find_plan_by_activity_preference(plans: list[dict[str, Any]], preference: str) -> dict[str, Any] | None:
    for plan in plans:
        if _item_matches_activity_preference(plan.get("activity") or {}, preference):
            return plan
    for plan in plans:
        title = str(plan.get("title") or "")
        if _item_matches_activity_preference({"name": title}, preference):
            return plan
    return None


def _negates_delivery(message: str) -> bool:
    return negates_delivery(message)


def _is_child_oriented_activity(activity: dict[str, Any]) -> bool:
    return _is_child_oriented_item(activity)


def _is_child_oriented_item(item: dict[str, Any]) -> bool:
    tags = set(item.get("tags") or [])
    category = item.get("category")
    return bool(
        item.get("child_friendly")
        or tags.intersection({"亲子", "儿童", "低龄友好"})
        or category in {"亲子乐园", "亲子餐厅"}
    )


def _should_preserve_unchanged_slots(
    message: str,
    add_slots: set[str],
    replace_slots: set[str],
    remove_slots: set[str],
    keep_slots: set[str],
    intent_patch: dict[str, Any],
) -> bool:
    if _requests_full_replan(message):
        return False
    if add_slots or replace_slots or remove_slots or keep_slots or intent_patch:
        return True
    return any(
        kw in message
        for kw in ["这个方案", "这个安排", "第一个方案", "第二个方案", "第三个方案", "在此基础", "基础上", "保持", "保留"]
    )


def _requests_full_replan(message: str) -> bool:
    return any(
        kw in message
        for kw in ["重新规划", "重新安排", "全部重来", "换个方案", "不要这个方案", "别按这个方案"]
    )


def _meal_from_time(time_value: str | None) -> str | None:
    if not time_value or ":" not in time_value:
        return None
    try:
        hour = int(time_value.split(":", 1)[0])
    except ValueError:
        return None
    if 10 <= hour <= 15:
        return "lunch"
    if 16 <= hour <= 22:
        return "dinner"
    return None


def _ordered_unique(values: list[str], order: list[str]) -> list[str]:
    return ordered_unique(values, order)


def _plan_summary(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not plan:
        return {}
    return {
        "plan_id": plan.get("plan_id"),
        "title": plan.get("title"),
        "activity_id": (plan.get("activity") or {}).get("id"),
        "restaurant_id": (plan.get("restaurant") or {}).get("id"),
        "drink_id": (plan.get("drink") or {}).get("id"),
        "meal_restaurant_ids": {
            entry.get("meal"): (entry.get("restaurant") or {}).get("id")
            for entry in plan.get("meal_restaurants") or []
            if isinstance(entry, dict)
        },
    }


def _negates_child(message: str) -> bool:
    patterns = [
        r"不带(小孩|孩子|儿童|宝宝|娃)",
        r"没带(小孩|孩子|儿童|宝宝|娃)",
        r"没有(小孩|孩子|儿童|宝宝|娃)",
        r"无(小孩|孩子|儿童|宝宝|娃)",
        r"不.*亲子",
        r"不是亲子",
        r"不要亲子",
    ]
    return any(re.search(pattern, message) for pattern in patterns)


def _remove_child_mentions(message: str) -> str:
    replacements = [
        r"孩子\s*\d+\s*岁",
        r"\d+\s*岁\s*(孩子|宝宝|小朋友)",
        r"带?(老婆|老公|妻子|丈夫)?孩子",
        r"亲子(乐园|活动|场景|友好)?",
        r"宝宝",
        r"小朋友",
        r"儿童",
    ]
    cleaned = message
    for pattern in replacements:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"[，,。；;]\s*[，,。；;]+", "，", cleaned)
    return cleaned.strip("，,。；; ")


def _remove_negated_delivery_mentions(message: str, revision: str) -> str:
    aliases: list[str] = []
    for preference in _negated_delivery_preferences(revision):
        aliases.extend(delivery_aliases_for_preference(preference))
    return strip_aliases(message, aliases) if aliases else message


def _remove_negated_activity_mentions(message: str, revision: str) -> str:
    aliases: list[str] = []
    for preference in _negated_activity_preferences(revision):
        if preference == "*":
            aliases.extend(["活动", "游玩", "玩"])
        else:
            aliases.extend(activity_aliases_for_preference(preference))
    return strip_aliases(message, aliases) if aliases else message
