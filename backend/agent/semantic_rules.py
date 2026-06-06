"""Shared semantic rules for intent and revision parsing."""

from __future__ import annotations

import re
from typing import Iterable


DELIVERY_METHOD_RULES = [
    ("外卖", ["外卖", "点个", "点份", "送餐", "送到餐厅", "送到", "送来", "送过去", "配送"]),
    ("闪送", ["闪送", "跑腿", "急送", "同城送"]),
]

DELIVERY_ITEM_RULES = [
    ("奶茶", ["奶茶", "果茶", "奶盖", "奈雪", "喜茶", "茶饮", "milk tea", "bubble tea"], True),
    ("蛋糕", ["生日蛋糕", "蛋糕", "cake", "birthday cake"], False),
    ("鲜花", ["送花", "鲜花", "花束", "玫瑰", "flower", "flowers"], False),
    ("水果", ["水果拼盘", "水果", "果盘"], True),
    ("儿童礼物", ["儿童礼物", "小玩具", "玩具", "气球"], False),
    ("礼物", ["伴手礼", "礼盒", "礼物", "礼品", "gift", "present"], False),
    ("轻食", ["轻食", "沙拉", "低卡餐"], True),
]

DELIVERY_METHOD_ORDER = ["外卖", "闪送"]
DELIVERY_ITEM_ORDER = ["奶茶", "蛋糕", "鲜花", "水果", "儿童礼物", "礼物", "轻食"]
DELIVERY_NEGATION_WORDS = ["不需要", "不要", "不用", "别", "取消", "去掉", "删掉", "移除", "不送", "别送", "不用送", "不点", "别点"]
DELIVERY_NEGATION_TAILS = ["不需要", "不要", "不用", "取消", "不用了", "算了", "别送了", "不送了", "不点了"]
DELIVERY_GENERIC_ALIASES = ["配送", "外卖", "闪送", "跑腿", "送货", "送餐", "送东西", "送过去", "送来"]


ACTIVITY_RULES = [
    ("桌游", ["桌游", "剧本杀", "叙旧", "叙叙旧", "聊天", "聊聊天", "board game"]),
    ("唱歌", ["KTV", "ktv", "唱歌", "K歌", "卡拉OK", "karaoke"]),
    ("艺术", ["展览", "看展", "美术馆", "博物馆", "艺术展", "画展"]),
    ("散步", ["citywalk", "Citywalk", "小吃街", "逛街", "逛逛", "逛一逛", "走走", "散步", "游览"]),
    ("密室", ["密室", "escape room"]),
    ("观影", ["电影", "影院", "电影院", "看电影"]),
    ("撸猫", ["撸猫", "猫咖"]),
    ("电竞", ["电竞", "游戏", "开黑"]),
    ("运动", ["蹦床", "运动", "健身", "攀岩"]),
    ("音乐", ["LiveHouse", "livehouse", "演出", "音乐会", "乐队"]),
    ("购物", ["购物", "商场"]),
    ("亲子", ["亲子", "乐园", "儿童乐园"]),
]

ACTIVITY_NEGATION_WORDS = ["不玩", "不要", "不去", "别去", "别玩", "不想", "取消", "去掉", "删掉", "移除"]
ACTIVITY_KEEP_WORDS = ["保留", "继续", "保持", "还是", "不变", "不要动", "别动", "挺好"]
ACTIVITY_CHANGE_WORDS = ["换成", "改成", "换", "改", "更换", "替换", "想去", "想玩", "想看", "想唱"]


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def ordered_unique(values: Iterable[str], order: list[str] | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    if order:
        value_set = set(values)
        for value in order:
            if value in value_set and value not in seen:
                seen.add(value)
                result.append(value)
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def latest_user_instruction(message: str) -> str:
    marker = "用户本轮修改："
    if marker in message:
        return message.rsplit(marker, 1)[-1]
    return message


def has_delivery_verb(message: str) -> bool:
    return contains_any(message, _all_delivery_method_aliases() + ["送", "送达", "送货", "代买"])


def extract_delivery_preferences(
    message: str,
    *,
    party_type: str | None = None,
    include_methods: bool = True,
    skip_negated: bool = True,
) -> list[str]:
    negated = set(negated_delivery_preferences(message)) if skip_negated else set()
    if "*" in negated and not _has_positive_delivery_replacement(message):
        return []

    preferences: list[str] = []
    if include_methods:
        for preference, aliases in DELIVERY_METHOD_RULES:
            if preference not in negated and contains_any(message, aliases):
                preferences.append(preference)

    delivery_signal = has_delivery_verb(message) or bool(preferences) or bool(negated)
    for preference, aliases, needs_delivery_signal in DELIVERY_ITEM_RULES:
        if needs_delivery_signal and not delivery_signal:
            continue
        if not contains_any(message, aliases):
            continue
        mapped = _map_delivery_preference_for_party(preference, party_type)
        if mapped not in negated:
            preferences.append(mapped)

    return ordered_unique(preferences, [*DELIVERY_METHOD_ORDER, *DELIVERY_ITEM_ORDER])


def negated_delivery_preferences(message: str) -> list[str]:
    message = latest_user_instruction(message)
    found: list[str] = []
    if re.search(r"(不|别|不用)送.{0,2}(花|鲜花|花束|玫瑰)", message):
        found.append("鲜花")

    for preference, aliases, _ in DELIVERY_ITEM_RULES:
        if _negates_any_alias(message, aliases, DELIVERY_NEGATION_WORDS, DELIVERY_NEGATION_TAILS):
            found.append(preference)
            if preference in {"礼物", "儿童礼物"}:
                found.extend(["礼物", "儿童礼物"])

    if _negates_any_alias(message, DELIVERY_GENERIC_ALIASES, DELIVERY_NEGATION_WORDS, DELIVERY_NEGATION_TAILS):
        found.append("*")
    if re.search(r"(不需要|不要|不用|取消|去掉|删掉|移除|别).{0,6}(送|送了|送过去|送来)", message):
        found.append("*")

    return ordered_unique(found, DELIVERY_ITEM_ORDER + ["*"])


def negates_delivery(message: str) -> bool:
    return bool(negated_delivery_preferences(message))


def delivery_aliases_for_preference(preference: str) -> list[str]:
    aliases: list[str] = []
    for pref, pref_aliases, _ in DELIVERY_ITEM_RULES:
        if pref == preference:
            aliases.extend(pref_aliases)
    for pref, pref_aliases in DELIVERY_METHOD_RULES:
        if pref == preference:
            aliases.extend(pref_aliases)
    if preference == "*":
        aliases.extend(DELIVERY_GENERIC_ALIASES)
    return ordered_unique(aliases)


def delivery_tags_for_preferences(preferences: Iterable[str] | None = None) -> set[str]:
    prefs = set(preferences or DELIVERY_ITEM_ORDER + DELIVERY_METHOD_ORDER)
    if "*" in prefs:
        prefs = set(DELIVERY_ITEM_ORDER + DELIVERY_METHOD_ORDER)
    tags: set[str] = {"delivery", "takeout", "flash delivery", "courier"}
    for preference in prefs:
        tags.add(preference)
        if preference == "外卖":
            tags.update({"外卖", "takeout", "food delivery"})
        elif preference == "闪送":
            tags.update({"闪送", "flash delivery", "courier"})
        elif preference == "奶茶":
            tags.update({"奶茶", "果茶", "drink", "milk_tea"})
        elif preference == "蛋糕":
            tags.update({"蛋糕", "生日蛋糕", "cake"})
        elif preference == "鲜花":
            tags.update({"鲜花", "花束", "flower", "flowers"})
        elif preference == "水果":
            tags.update({"水果", "水果拼盘", "fruit"})
        elif preference in {"儿童礼物", "礼物"}:
            tags.update({"儿童礼物", "礼物", "礼盒", "气球", "gift", "present"})
        elif preference == "轻食":
            tags.update({"轻食", "沙拉", "food", "低卡"})
    return tags


def has_delivery_with_deliverable(message: str) -> bool:
    return has_delivery_verb(message) and any(
        contains_any(message, aliases)
        for _, aliases, _ in DELIVERY_ITEM_RULES
    )


def delivery_keywords_from_message(message: str) -> list[str]:
    found: list[str] = []
    for _, aliases in DELIVERY_METHOD_RULES:
        found.extend(alias for alias in aliases if alias in message)
    for preference, aliases, needs_delivery_signal in DELIVERY_ITEM_RULES:
        if needs_delivery_signal and not has_delivery_verb(message):
            continue
        if contains_any(message, aliases):
            found.append(preference)
    return ordered_unique(found, [*DELIVERY_METHOD_ORDER, *DELIVERY_ITEM_ORDER])


def activity_preference_from_message(message: str) -> str | None:
    for preference, aliases in ACTIVITY_RULES:
        if contains_any(message, aliases) and is_positive_activity_preference(message, preference):
            return preference
    return None


def is_positive_activity_preference(message: str, preference: str) -> bool:
    return preference not in set(negated_activity_preferences(message))


def negated_activity_preferences(message: str) -> list[str]:
    message = latest_user_instruction(message)
    found: list[str] = []
    if re.search(r"(不要动|别动).{0,4}活动|活动.{0,4}(不要动|别动|不变)", message):
        return []
    if _negates_any_alias(message, ["活动", "玩", "项目"], ACTIVITY_NEGATION_WORDS, ["不需要", "不要", "不用", "取消"]):
        found.append("*")
    for preference, aliases in ACTIVITY_RULES:
        if _negates_any_alias(message, aliases, ACTIVITY_NEGATION_WORDS, ["不需要", "不要", "不用", "取消", "不去了", "不玩了"]):
            found.append(preference)
    return ordered_unique(found, [preference for preference, _ in ACTIVITY_RULES] + ["*"])


def requests_activity_change(message: str) -> bool:
    if contains_any(message, ["换活动", "改活动", "换个活动", "更换活动", "替换活动"]):
        return True
    if negated_activity_preferences(message):
        return True
    preference = activity_preference_from_message(message)
    if not preference:
        return False
    return contains_any(message, ACTIVITY_CHANGE_WORDS)


def requests_activity_keep(message: str) -> bool:
    if contains_any(message, ["不要动活动", "活动不要动", "保留活动", "继续这个活动", "活动不变"]):
        return True
    return any(
        contains_any(message, aliases) and contains_any(message, ACTIVITY_KEEP_WORDS)
        for _, aliases in ACTIVITY_RULES
    )


def item_matches_activity_preference(item: dict, preference: str) -> bool:
    if not item:
        return False
    aliases = activity_aliases_for_preference(preference) or [preference]
    haystack = " ".join(
        str(value)
        for value in [
            item.get("name", ""),
            item.get("category", ""),
            " ".join(item.get("tags") or []),
        ]
    )
    return contains_any(haystack, aliases)


def activity_aliases_for_preference(preference: str) -> list[str]:
    for pref, aliases in ACTIVITY_RULES:
        if pref == preference:
            return aliases
    return []


def activity_preferences_from_item(item: dict) -> list[str]:
    if not item:
        return []
    return [
        preference
        for preference, _ in ACTIVITY_RULES
        if item_matches_activity_preference(item, preference)
    ]


def strip_aliases(text: str, aliases: Iterable[str]) -> str:
    cleaned = text
    for alias in sorted(set(aliases), key=len, reverse=True):
        if not alias or len(alias) <= 1:
            continue
        cleaned = re.sub(re.escape(alias), "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ，,。；;")


def _all_delivery_method_aliases() -> list[str]:
    aliases: list[str] = []
    for _, method_aliases in DELIVERY_METHOD_RULES:
        aliases.extend(method_aliases)
    return aliases


def _map_delivery_preference_for_party(preference: str, party_type: str | None) -> str:
    if preference == "礼物" and party_type == "family_with_child":
        return "儿童礼物"
    return preference


def _has_positive_delivery_replacement(message: str) -> bool:
    latest = latest_user_instruction(message)
    negated = set(negated_delivery_preferences(latest))
    for preference, aliases, _ in DELIVERY_ITEM_RULES:
        if preference not in negated and contains_any(latest, aliases):
            return True
    return False


def _negates_any_alias(
    message: str,
    aliases: Iterable[str],
    prefixes: Iterable[str],
    tails: Iterable[str],
) -> bool:
    alias_group = _regex_group(aliases)
    if not alias_group:
        return False
    prefix_group = _regex_group(prefixes)
    tail_group = _regex_group(tails)
    prefix_pattern = re.compile(rf"({prefix_group})(.{{0,12}})({alias_group})")
    for match in prefix_pattern.finditer(message):
        if not re.search(r"(换成|改成|替换成|换为|改为|换|改)", match.group(2)):
            return True
    return bool(re.search(rf"({alias_group}).{{0,12}}({tail_group})", message))


def _regex_group(values: Iterable[str]) -> str:
    escaped = [re.escape(value) for value in sorted(set(values), key=len, reverse=True) if value]
    return "|".join(escaped)
