"""意图解析器 - 从自然语言提取结构化 Intent"""

import re
import json
from typing import Optional

from backend.agent.schemas import Intent
from backend.agent.time_utils import (
    detect_time_window,
    extract_start_time,
    infer_time_window_from_clock,
    normalize_time_window,
)
from backend.llm.deepseek_client import deepseek_client, LLMResult


CHILD_KW = ["孩子", "儿子", "女儿", "亲子", "宝宝", "小朋友", "儿童", "娃"]
SPOUSE_KW = ["老婆", "老公", "妻子", "丈夫", "爱人"]
ELDER_KW = ["爸妈", "父母", "爸爸", "妈妈", "老人", "长辈", "爷爷", "奶奶", "外公", "外婆", "公婆", "岳父", "岳母"]
RELATIVE_KW = ["亲戚", "亲人", "全家", "一家人", "家里人", "表哥", "表姐", "堂哥", "堂姐", "兄弟姐妹"]
COUPLE_KW = ["情侣", "约会", "对象", "女朋友", "男朋友", "纪念日", "二人世界"]
FRIENDS_KW = ["朋友", "同学", "哥们", "闺蜜", "聚会", "拍照", "好玩", "桌游", "喝咖啡"]
EXPLICIT_FRIEND_KW = ["朋友", "同学", "哥们", "闺蜜", "同事", "团队", "团建", "部门"]
BUSINESS_KW = ["客户", "商务", "领导", "老板", "合作方", "商务饭局", "商务宴请"]
COLLEAGUE_KW = ["同事", "团队", "团建", "部门"]
SOLO_KW = ["一个人", "自己", "独自", "单人", "我一个"]
DISTANCE_KW = [
    "不太远", "附近", "周边", "就近", "别太远", "离家近", "近一点",
    "远一点", "无所谓距离", "远一点也行",
]
DISTANCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(公里|千米|km|KM|米|m)")

TAG_RULES = [
    (["纪念日", "周年", "情人节", "七夕"], "纪念日"),
    (["约会", "二人世界", "情侣", "对象", "女朋友", "男朋友"], "约会"),
    (["仪式感", "正式一点", "有感觉"], "仪式感"),
    (["拍照", "打卡", "好看", "出片", "网红"], "拍照"),
    (["高端", "高级", "品质", "精致", "贵一点", "好一点"], "高端"),
    (["安静", "别吵", "不吵", "私密", "适合聊天", "叙旧", "聊天"], "安静"),
    (["包间", "包房"], "包间"),
    (["清淡", "低卡", "轻食", "健康", "减脂", "减肥"], "健康"),
    (["少走路", "别太累", "不累", "腿脚", "老人方便"], "少走路"),
    (["好停车", "停车方便"], "好停车"),
    (["爸妈", "父母", "老人", "长辈"], "长辈友好"),
    (["商务", "客户", "领导", "老板", "宴请"], "商务"),
    (["一个人", "独自", "单人"], "独处"),
    (["亲子", "孩子", "宝宝", "儿童", "小朋友"], "亲子"),
    (["生日"], "生日"),
    (["惊喜", "礼物", "礼盒"], "惊喜"),
    (["鲜花", "花束"], "鲜花"),
]


def _has_any(message: str, keywords: list[str]) -> bool:
    return any(kw in message for kw in keywords)


def _has_explicit_distance_preference(message: str) -> bool:
    """只有用户真的提到距离时，才让 LLM 覆盖距离半径。"""
    return bool(DISTANCE_RE.search(message)) or _has_any(message, DISTANCE_KW)


def _has_negated_child_context(message: str) -> bool:
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


def _infer_party_type_and_scene(message: str) -> tuple[str, str]:
    """推断真实同行人画像，并让兼容字段 scene 与 party_type 保持一致。"""
    negated_child = _has_negated_child_context(message)
    has_child = _has_any(message, CHILD_KW) and not negated_child
    has_spouse = _has_any(message, SPOUSE_KW)
    has_elder = _has_any(message, ELDER_KW)
    has_relative = _has_any(message, RELATIVE_KW)
    has_couple = _has_any(message, COUPLE_KW)
    has_friends = _has_any(message, FRIENDS_KW)
    has_business = _has_any(message, BUSINESS_KW)
    has_colleague = _has_any(message, COLLEAGUE_KW)
    has_solo = _has_any(message, SOLO_KW)

    if has_business:
        return "business", "business"
    if has_child:
        return "family_with_child", "family_with_child"
    if has_elder:
        return "family_elder", "family_elder"
    if has_relative:
        return "family", "family"
    if (has_friends or has_colleague) and (not has_spouse or _has_any(message, EXPLICIT_FRIEND_KW)):
        return "friends", "friends"
    if has_couple or has_spouse:
        return "couple", "couple"
    if has_solo:
        return "solo", "solo"
    return "general", "general"


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _extract_meal_slots(message: str) -> list[str]:
    """识别用户是否明确要求午餐/晚餐两个独立用餐槽位。"""
    slots: list[str] = []
    lunch_patterns = [
        r"中饭", r"午饭", r"午餐", r"中午.*吃", r"中午.*用餐",
    ]
    dinner_patterns = [
        r"晚饭", r"晚餐", r"晚上.*吃", r"晚上.*用餐", r"傍晚.*吃",
    ]
    if any(re.search(pattern, message) for pattern in lunch_patterns):
        slots.append("lunch")
    if any(re.search(pattern, message) for pattern in dinner_patterns):
        slots.append("dinner")
    if "两顿" in message and "吃" in message:
        for slot in ["lunch", "dinner"]:
            _append_unique(slots, slot)
    return slots


def _chinese_digit_to_int(value: str | None) -> int | None:
    mapping = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return mapping.get(value or "")


def _extract_duration_hours(message: str) -> int | None:
    range_match = re.search(r"(\d+)\s*[-~到至]\s*(\d+)\s*个?小?时", message)
    if range_match:
        low = int(range_match.group(1))
        high = int(range_match.group(2))
        if high >= low:
            return round((low + high) / 2)

    dur_match = re.search(r"(\d+)\s*个小?时|(\d+)\s*小时", message)
    if dur_match:
        return int(dur_match.group(1) or dur_match.group(2))

    cn_dur_match = re.search(r"([一二两三四五六七八九十])\s*个小?时|([一二两三四五六七八九十])\s*小时", message)
    if cn_dur_match:
        return _chinese_digit_to_int(cn_dur_match.group(1) or cn_dur_match.group(2))

    if any(kw in message for kw in ["几个小时", "一下午", "下午是空的", "下午空", "半天"]):
        return 5
    return None


def _extract_gender_composition(message: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*个?(?:男生|男|男孩|男同学).*?(\d+)\s*个?(?:女生|女|女孩|女同学)", message)
    if match:
        return int(match.group(1)), int(match.group(2))
    cn_match = re.search(
        r"([一二两三四五六七八九十])\s*个?(?:男生|男|男孩|男同学).*?([一二两三四五六七八九十])\s*个?(?:女生|女|女孩|女同学)",
        message,
    )
    if cn_match:
        left = _chinese_digit_to_int(cn_match.group(1)) or 0
        right = _chinese_digit_to_int(cn_match.group(2)) or 0
        return (left, right) if left + right else None
    return None


def _extract_gender_composition_count(message: str) -> int | None:
    composition = _extract_gender_composition(message)
    if composition:
        return composition[0] + composition[1]
    return None


def _extract_people_count(message: str) -> int | None:
    digit_patterns = [
        r"(?:我们|咱们|一共|总共|总共有|有)\s*(\d+)\s*个?\s*(?:人|位)",
        r"(\d+)\s*个人",
        r"(\d+)\s*人(?!均)",
        r"(\d+)\s*位",
        r"(\d+)\s*个(?:朋友|同学|同事|人)",
        r"(\d+)\s*个[人位]",
    ]
    for pattern in digit_patterns:
        match = re.search(pattern, message)
        if match:
            return int(match.group(1))

    chinese_patterns = [
        r"(?:我们|咱们|一共|总共|总共有|有)\s*([一二两三四五六七八九十])\s*个?\s*(?:人|位)",
        r"([一二两三四五六七八九十])\s*个人",
        r"([一二两三四五六七八九十])\s*人",
        r"([一二两三四五六七八九十])\s*位",
        r"([一二两三四五六七八九十])\s*个(?:朋友|同学|同事|人)",
    ]
    for pattern in chinese_patterns:
        match = re.search(pattern, message)
        if match:
            return _chinese_digit_to_int(match.group(1))
    return None


def _has_delivery_verb(message: str) -> bool:
    return any(kw in message for kw in ["送", "送到", "送来", "送过去", "配送", "外卖", "闪送", "跑腿", "急送", "同城送"])


def _has_negated_delivery_context(message: str) -> bool:
    patterns = [
        r"(不需要|不要|不用|别|取消|去掉|删掉|移除).{0,8}(送花|鲜花|花束|配送|外卖|闪送)",
        r"(送花|鲜花|花束|配送|外卖|闪送).{0,8}(不需要|不要|不用|取消)",
    ]
    return any(re.search(pattern, message) for pattern in patterns)


def _has_romantic_context(message: str) -> bool:
    return any(kw in message for kw in ["约会", "纪念日", "周年", "情人节", "七夕", "二人世界", "情侣"])


def _has_friend_spouse_context(message: str) -> bool:
    return _has_any(message, EXPLICIT_FRIEND_KW) and _has_any(message, SPOUSE_KW)


def _extract_intent_tags(message: str, party_type: str) -> list[str]:
    tags: list[str] = []
    for keywords, tag in TAG_RULES:
        if _has_any(message, keywords):
            _append_unique(tags, tag)
    if _has_negated_child_context(message):
        tags = [tag for tag in tags if tag != "亲子"]

    defaults_by_party = {
        "family_with_child": ["亲子"],
        "family_elder": ["长辈友好", "少走路", "安静"],
        "family": ["家庭"],
        "couple": ["约会"],
        "business": ["商务", "安静"],
        "solo": ["独处"],
        "friends": ["聚会"],
    }
    for tag in defaults_by_party.get(party_type, []):
        _append_unique(tags, tag)
    return tags


def _has_child_context(intent: Intent) -> bool:
    if intent.party_type == "family_with_child" or intent.child_age is not None:
        return True
    return any(c.get("role") == "child" for c in intent.companions)


def _has_spouse_context(intent: Intent) -> bool:
    if intent.party_type in {"couple", "family_with_child"}:
        return True
    return any(c.get("role") == "spouse" for c in intent.companions)


# ── 规则兜底解析 ──────────────────────────────────────────────

def _rule_parse(message: str) -> Intent:
    """基于关键词规则的意图解析，始终可用"""
    party_type, scene = _infer_party_type_and_scene(message)

    # 时间窗口
    time_window = detect_time_window(message) or "afternoon"
    start_time, inferred_window = extract_start_time(message)
    if start_time and inferred_window:
        time_window = inferred_window
    meal_slots = _extract_meal_slots(message)
    if {"lunch", "dinner"}.issubset(set(meal_slots)) and not start_time:
        time_window = "lunch"

    # 日期
    date = "today"
    if "明天" in message or "明日" in message:
        date = "tomorrow"

    # 时长
    duration_hours = _extract_duration_hours(message)

    # 人数
    people_count = _extract_people_count(message)
    if people_count is None:
        people_count = _extract_gender_composition_count(message)
    # 同行人默认人数
    if people_count is None and party_type == "family_with_child":
        count = 1  # self
        if _has_any(message, SPOUSE_KW):
            count += 1
        if _has_any(message, CHILD_KW):
            count += 1
        if count > 1:
            people_count = count
    elif people_count is None and party_type == "family_elder":
        people_count = 3 if "爸妈" in message or "父母" in message else 2
    elif people_count is None and party_type == "couple":
        people_count = 2
    elif people_count is None and party_type == "solo":
        people_count = 1

    # 距离偏好
    radius_km = 5.0
    distance_preference = "nearby"
    if any(kw in message for kw in ["不太远", "附近", "就近", "别太远", "离家近", "近一点"]):
        radius_km = 5.0
        distance_preference = "nearby"
    elif any(kw in message for kw in ["远一点", "无所谓距离", "远一点也行"]):
        radius_km = 15.0
        distance_preference = "flexible"
    dist_match = re.search(r"(\d+)\s*公里", message)
    if dist_match:
        radius_km = float(dist_match.group(1))

    # 儿童年龄
    child_age = None
    if not _has_negated_child_context(message):
        age_match = re.search(r"孩子\s*(\d+)\s*岁", message)
        if not age_match:
            age_match = re.search(r"(\d+)\s*岁.*孩", message)
        if not age_match:
            age_match = re.search(r"宝宝\s*(\d+)\s*岁", message)
        if not age_match:
            age_match = re.search(r"(\d+)\s*岁\s*宝宝", message)
        if age_match:
            child_age = int(age_match.group(1))

    # 饮食偏好
    food_preferences = []
    if any(kw in message for kw in ["减肥", "减脂", "清淡", "健康", "轻食", "沙拉"]):
        food_preferences.append("健康")
    if any(kw in message for kw in ["好吃", "美食", "想吃", "好吃的", "味道"]):
        food_preferences.append("美食")
    if any(kw in message for kw in ["拍照", "好看", "网红"]):
        food_preferences.append("拍照")

    # 活动偏好
    activity_preferences = []
    if any(kw in message for kw in ["亲子", "孩子玩", "儿童", "乐园", "宝宝"]):
        activity_preferences.append("亲子")
    if any(kw in message for kw in ["拍照", "打卡"]):
        activity_preferences.append("拍照")
    if any(kw in message for kw in ["户外", "公园", "散步"]):
        activity_preferences.append("户外")
    if any(kw in message for kw in ["逛逛", "逛一逛", "走走", "游览", "参观", "citywalk", "Citywalk", "来我的城市", "带他们逛"]):
        activity_preferences.append("散步")
    if party_type == "family_elder" and any(kw in message for kw in ["逛逛", "走走", "城市", "参观", "游览", "爸妈", "父母"]):
        activity_preferences.append("安静")
    if any(kw in message for kw in ["KTV", "唱歌", "密室", "撸猫", "电竞", "蹦床", "LiveHouse", "livehouse", "演出"]):
        activity_preferences.append("社交")
    if any(kw in message for kw in ["桌游", "剧本杀", "小吃街", "citywalk", "Citywalk"]):
        activity_preferences.append("社交")
    if party_type == "friends" and any(kw in message for kw in ["叙旧", "聊天", "聊聊天"]):
        activity_preferences.append("桌游")
    if any(kw in message for kw in ["电影", "看电影", "影院", "电影院"]):
        activity_preferences.append("观影")

    # 饮品偏好
    drink_preferences = []
    if any(kw in message for kw in ["咖啡", "喝咖啡", "奶茶", "茶饮", "果茶", "奶盖", "奈雪", "喜茶", "星巴克", "瑞幸"]):
        drink_preferences.append("coffee_tea")
    if any(kw in message for kw in ["精酿", "啤酒", "酒吧", "喝酒", "小酌", "清吧"]):
        drink_preferences.append("bar")

    # 外卖/闪送偏好
    delivery_preferences = []
    delivery_verb = _has_delivery_verb(message)
    if not _has_negated_delivery_context(message):
        if any(kw in message for kw in ["外卖", "点个", "送餐", "送到餐厅", "送到", "送来", "送过去", "配送"]):
            delivery_preferences.append("外卖")
        if any(kw in message for kw in ["闪送", "跑腿", "急送", "同城送"]):
            delivery_preferences.append("闪送")
        if delivery_verb and any(kw in message for kw in ["奶茶", "果茶", "奶盖", "奈雪", "喜茶"]):
            delivery_preferences.append("奶茶")
        if any(kw in message for kw in ["蛋糕", "生日蛋糕"]):
            delivery_preferences.append("蛋糕")
        if any(kw in message for kw in ["花", "鲜花", "花束"]):
            delivery_preferences.append("鲜花")
        if any(kw in message for kw in ["礼物", "礼盒", "气球", "惊喜"]):
            delivery_preferences.append("儿童礼物" if party_type == "family_with_child" else "惊喜")
        if any(kw in message for kw in ["水果", "水果拼盘"]):
            delivery_preferences.append("水果")

    tags = _extract_intent_tags(message, party_type)

    # 低卡需求
    needs_low_calorie = any(
        kw in message for kw in ["减肥", "减脂", "清淡", "低卡", "轻食", "健康餐"]
    )
    if needs_low_calorie:
        _append_unique(tags, "健康")

    # 拍照需求
    needs_photo_spot = any(kw in message for kw in ["拍照", "打卡", "好看", "出片"])
    if needs_photo_spot:
        _append_unique(tags, "拍照")

    needs_quiet = any(kw in message for kw in ["安静", "别吵", "不吵", "私密", "包间", "适合聊天", "正式"])
    if needs_quiet:
        _append_unique(tags, "安静")
    needs_less_walking = (
        party_type == "family_elder"
        or any(kw in message for kw in ["少走路", "别太累", "不累", "腿脚", "老人方便", "好停车"])
    )
    if needs_less_walking:
        _append_unique(tags, "少走路")

    # 排队容忍
    avoid_queue_minutes = 30
    if any(kw in message for kw in ["不想排队", "别排队", "排队少", "不等位"]):
        avoid_queue_minutes = 10
    elif any(kw in message for kw in ["排队久", "排队长", "网红"]):
        avoid_queue_minutes = 60

    # 预算
    budget_per_person = None
    budget_match = re.search(r"人均\s*(\d+)", message)
    if not budget_match:
        budget_match = re.search(r"预算\s*(\d+)", message)
    if budget_match:
        budget_per_person = int(budget_match.group(1))

    return Intent(
        scene=scene,
        party_type=party_type,
        tags=tags,
        date=date,
        time_window=time_window,
        start_time=start_time,
        duration_hours=duration_hours,
        meal_slots=meal_slots,
        people_count=people_count,
        companions=_build_companions(message, party_type, child_age),
        radius_km=radius_km,
        distance_preference=distance_preference,
        budget_per_person=budget_per_person,
        food_preferences=food_preferences,
        activity_preferences=activity_preferences,
        drink_preferences=drink_preferences,
        delivery_preferences=delivery_preferences,
        child_age=child_age,
        needs_low_calorie=needs_low_calorie,
        needs_photo_spot=needs_photo_spot,
        needs_quiet=needs_quiet,
        needs_less_walking=needs_less_walking,
        avoid_queue_minutes=avoid_queue_minutes,
    )


def _build_companions(message: str, party_type: str, child_age: Optional[int]) -> list[dict]:
    """从消息中提取同行人信息"""
    companions = []
    if "老婆" in message or "妻子" in message:
        companions.append({"role": "spouse", "diet_preference": "减脂" if "减肥" in message else None})
    if "老公" in message or "丈夫" in message:
        companions.append({"role": "spouse"})
    if _has_any(message, CHILD_KW) and not _has_negated_child_context(message):
        companions.append({"role": "child", "age": child_age})
    if _has_any(message, ELDER_KW):
        role = "parent" if any(kw in message for kw in ["爸妈", "父母", "爸爸", "妈妈"]) else "elder"
        companions.append({"role": role, "mobility": "low" if party_type == "family_elder" else None})
    if _has_any(message, RELATIVE_KW):
        companions.append({"role": "relative"})
    if party_type == "business":
        companions.append({"role": "client" if "客户" in message else "colleague"})
    if party_type == "friends":
        composition = _extract_gender_composition(message)
        if composition:
            male_count, female_count = composition
            companions.extend({"role": "friend", "gender": "male"} for _ in range(male_count))
            companions.extend({"role": "friend", "gender": "female"} for _ in range(female_count))
        else:
            # 提取朋友人数
            m = re.search(r"(\d+)\s*(个|位)", message)
            count = int(m.group(1)) if m else 2
            for _ in range(count):
                companions.append({"role": "friend"})
    return companions


# ── LLM 解析 ───────────────────────────────────────────────────

INTENT_SYSTEM_PROMPT = """你是一个意图解析器。根据用户输入，提取以下结构化信息，仅输出 JSON：

{
  "party_type": "family_with_child" | "family_elder" | "family" | "friends" | "couple" | "solo" | "business" | "general",
  "tags": [string],
  "date": "today" | "tomorrow" | 具体日期,
  "time_window": "morning" | "lunch" | "afternoon" | "dinner" | "evening" | "night" | "unknown",
  "start_time": "HH:MM" | null,
  "duration_hours": int | null,
  "meal_slots": ["lunch" | "dinner"],
  "people_count": int | null,
  "companions": [{"role": "...", "age": null | int, "diet_preference": null | string}],
  "radius_km": float,
  "distance_preference": "nearby" | "flexible",
  "budget_per_person": int | null,
  "food_preferences": [string],
  "activity_preferences": [string],
  "drink_preferences": [string],
  "delivery_preferences": [string],
  "child_age": int | null,
  "needs_low_calorie": bool,
  "needs_photo_spot": bool,
  "needs_quiet": bool,
  "needs_less_walking": bool,
  "avoid_queue_minutes": int
}

规则：
- party_type 是真实同行人画像：带孩子 → family_with_child；爸妈/老人 → family_elder；亲戚/全家 → family；情侣/夫妻二人 → couple；朋友/同学/同事 → friends；客户/商务/领导 → business；一个人 → solo
- tags 统一表达时机、体验、偏好和约束，如：纪念日、约会、仪式感、拍照、高端、安静、包间、清淡、少走路、好停车、长辈友好、商务、亲子、生日、惊喜、鲜花
- child_age: 从"孩子X岁"中提取
- needs_low_calorie: 提到减肥/减脂/清淡/低卡 → true
- needs_quiet: 提到安静/包间/私密/正式 → true
- needs_less_walking: 提到爸妈/老人/少走路/别太累/腿脚不便 → true
- time_window: 中午/午饭/午餐 → lunch；晚饭/晚餐/晚上吃饭 → dinner；晚上活动 → evening；宵夜/深夜 → night
- meal_slots: 用户明确说中饭/午饭/午餐则包含 lunch；明确说晚饭/晚餐则包含 dinner；“中饭晚饭都要吃/两顿饭”应输出 ["lunch","dinner"]
- start_time: 提取精确开始时间，如"下午三点"→"15:00"，"15:30"→"15:30"，"两点半"默认按下午理解为"14:30"
- drink_preferences: 提到咖啡/奶茶 → ["coffee_tea"]，精酿/啤酒/酒吧 → ["bar"]
- delivery_preferences: 提到外卖/闪送/蛋糕/鲜花/礼物/送到餐厅 → 提取对应商品或配送偏好
- avoid_queue_minutes: 默认为30，提到不想排队→10，网红/排队久→60
"""


async def _llm_parse(message: str) -> Optional[dict]:
    """使用 LLM 解析意图，失败返回 None"""
    msgs = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]
    result: LLMResult = await deepseek_client.chat_json(msgs, temperature=0.1)
    if not result.ok:
        return None
    if isinstance(result.json_data, dict):
        return result.json_data
    try:
        # 尝试提取 JSON
        text = result.text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except (json.JSONDecodeError, IndexError):
        return None


# ── 主入口 ─────────────────────────────────────────────────────

async def parse_intent(message: str, user_memory: Optional[dict] = None) -> Intent:
    """解析用户意图，LLM 优先，失败时规则兜底"""
    intent_dict = None

    if deepseek_client.available:
        intent_dict = await _llm_parse(message)

    intent = _rule_parse(message)

    if intent_dict:
        # LLM 结果补充（不覆盖规则推导的基本字段，但信任 LLM 的正确解析）
        try:
            for key in ["party_type", "date", "time_window", "start_time", "duration_hours",
                        "people_count", "radius_km", "distance_preference",
                        "budget_per_person", "child_age", "needs_low_calorie",
                        "needs_photo_spot", "needs_quiet", "needs_less_walking",
                        "avoid_queue_minutes"]:
                if key in intent_dict and _valid_llm_field(key, intent_dict[key]):
                    if key in {"radius_km", "distance_preference"} and not _has_explicit_distance_preference(message):
                        continue
                    if key in {"needs_low_calorie", "needs_photo_spot", "needs_quiet", "needs_less_walking"}:
                        setattr(intent, key, bool(getattr(intent, key) or intent_dict[key]))
                    else:
                        setattr(intent, key, intent_dict[key])
            if "food_preferences" in intent_dict and intent_dict["food_preferences"]:
                intent.food_preferences = intent_dict["food_preferences"]
            if "activity_preferences" in intent_dict and intent_dict["activity_preferences"]:
                intent.activity_preferences = intent_dict["activity_preferences"]
            if "drink_preferences" in intent_dict and intent_dict["drink_preferences"]:
                intent.drink_preferences = intent_dict["drink_preferences"]
            if "delivery_preferences" in intent_dict and intent_dict["delivery_preferences"]:
                intent.delivery_preferences = intent_dict["delivery_preferences"]
            if "meal_slots" in intent_dict and isinstance(intent_dict["meal_slots"], list):
                for slot in intent_dict["meal_slots"]:
                    if slot in {"lunch", "dinner"}:
                        _append_unique(intent.meal_slots, slot)
            if "tags" in intent_dict and isinstance(intent_dict["tags"], list):
                for tag in intent_dict["tags"]:
                    if isinstance(tag, str):
                        _append_unique(intent.tags, tag)
        except Exception:
            pass  # LLM 部分字段解析失败，保留规则结果

    _apply_negative_child_override(intent, message)
    _apply_negative_delivery_override(intent, message)
    _apply_friend_spouse_override(intent, message)
    _normalize_time_fields(intent)
    _normalize_party_fields(intent)

    # 合并用户记忆（用户输入优先，记忆仅作为默认值）
    # 家庭/个人属性仅在家场景或用户明确提到家庭成员时合并
    if user_memory:
        prefs = user_memory.get("preferences", {})
        if not intent.child_age and prefs.get("child_age") and _has_child_context(intent):
            intent.child_age = prefs["child_age"]
        if intent.radius_km == 5.0 and prefs.get("max_distance_km"):
            intent.radius_km = float(prefs["max_distance_km"])
        if intent.avoid_queue_minutes == 30 and prefs.get("max_queue_minutes"):
            intent.avoid_queue_minutes = prefs["max_queue_minutes"]
        _merge_memory_tags(intent, prefs)

        # companions: 朋友场景不加入 child/spouse
        if not intent.companions:
            if _has_child_context(intent) and prefs.get("child_age") and prefs.get("child_name"):
                intent.companions.append({"role": "child", "age": prefs["child_age"]})
            if _has_spouse_context(intent) and prefs.get("spouse_diet"):
                intent.companions.append({"role": "spouse", "diet_preference": prefs["spouse_diet"]})

    _normalize_preferences(intent)
    _apply_negative_child_override(intent, message)
    _apply_negative_delivery_override(intent, message)
    _apply_friend_spouse_override(intent, message)
    _normalize_time_fields(intent)
    _normalize_party_fields(intent)
    _apply_negative_child_override(intent, message)
    _apply_negative_delivery_override(intent, message)
    _apply_friend_spouse_override(intent, message)
    return intent


def _normalize_time_fields(intent: Intent) -> None:
    """统一 LLM/规则输出的时间段和精确时间。"""
    intent.meal_slots = [
        slot for slot in ["lunch", "dinner"]
        if slot in set(intent.meal_slots)
    ]
    intent.time_window = normalize_time_window(intent.time_window, default="afternoon")
    if {"lunch", "dinner"}.issubset(set(intent.meal_slots)) and not intent.start_time:
        intent.time_window = "lunch"
    if intent.start_time:
        if not re.fullmatch(r"[0-2]?\d:[0-5]\d", intent.start_time):
            intent.start_time = None
            return
        hour, minute = [int(part) for part in intent.start_time.split(":", 1)]
        if hour > 23:
            intent.start_time = None
            return
        intent.start_time = f"{hour:02d}:{minute:02d}"
        if intent.time_window == "unknown":
            intent.time_window = infer_time_window_from_clock(intent.start_time)


def _normalize_party_fields(intent: Intent) -> None:
    """把 LLM/规则输出统一到 party_type，并同步旧 scene 兼容字段。"""
    party_map = {
        "family_child": "family_with_child",
        "family_with_kids": "family_with_child",
        "with_child": "family_with_child",
        "elder": "family_elder",
        "family_parent": "family_elder",
        "parents": "family_elder",
        "date": "couple",
        "dating": "couple",
        "friend": "friends",
        "colleagues": "friends",
        "business_meal": "business",
        "alone": "solo",
    }
    scene_party_map = {
        "family_with_child": "family_with_child",
        "family_elder": "family_elder",
        "family": "family",
        "friends": "friends",
        "couple": "couple",
        "date": "couple",
        "solo": "solo",
        "business": "business",
        "general": "general",
    }
    party = party_map.get(intent.party_type, intent.party_type)
    if party == "general" and intent.scene in scene_party_map:
        party = scene_party_map[intent.scene]
    if intent.child_age is not None or any(c.get("role") == "child" for c in intent.companions):
        party = "family_with_child"
    if party not in {
        "family_with_child", "family_elder", "family", "friends",
        "couple", "solo", "business", "general",
    }:
        party = "general"
    intent.party_type = party
    intent.scene = party

    if party == "family_elder":
        intent.needs_less_walking = True
        for tag in ["长辈友好", "少走路"]:
            _append_unique(intent.tags, tag)
    if party == "business":
        intent.needs_quiet = True
        for tag in ["商务", "安静"]:
            _append_unique(intent.tags, tag)
    if party == "couple":
        _append_unique(intent.tags, "约会")
    if party == "solo":
        _append_unique(intent.tags, "独处")
    if party == "family_with_child":
        _append_unique(intent.tags, "亲子")


def _apply_negative_child_override(intent: Intent, message: str) -> None:
    """处理“这次不带小孩/不是亲子”这类显式纠偏。"""
    if not _has_negated_child_context(message):
        return
    intent.child_age = None
    intent.companions = [c for c in intent.companions if c.get("role") != "child"]
    intent.tags = [tag for tag in intent.tags if tag != "亲子"]
    if intent.party_type == "family_with_child":
        if _has_any(message, FRIENDS_KW) or _has_any(message, COLLEAGUE_KW):
            intent.party_type = "friends"
        elif _has_any(message, COUPLE_KW) or _has_any(message, SPOUSE_KW):
            intent.party_type = "couple"
        else:
            intent.party_type = "general"
        intent.scene = intent.party_type


def _apply_negative_delivery_override(intent: Intent, message: str) -> None:
    """处理“不需要送花/取消闪送”这类显式配送否定。"""
    if not _has_negated_delivery_context(message):
        return
    intent.delivery_preferences = []
    intent.tags = [
        tag for tag in intent.tags
        if tag not in {"鲜花", "flower", "闪送", "外卖"}
    ]


def _apply_friend_spouse_override(intent: Intent, message: str) -> None:
    """朋友局里临时带上配偶，不应被改写成约会/送花场景。"""
    if not _has_friend_spouse_context(message):
        return
    if intent.party_type in {"couple", "general"}:
        intent.party_type = "friends"
        intent.scene = "friends"
    if not _has_romantic_context(message):
        intent.tags = [tag for tag in intent.tags if tag != "约会"]
        if not any(kw in message for kw in ["送花", "鲜花", "花束"]):
            intent.delivery_preferences = [
                pref for pref in intent.delivery_preferences
                if pref not in {"鲜花", "flower"}
            ]


def _merge_memory_tags(intent: Intent, prefs: dict) -> None:
    """将用户长期记忆整理成打分标签，不进入本轮搜索过滤。"""
    for tag in prefs.get("preferred_tags", []) or []:
        _append_unique(intent.memory_tags, tag)
    for tag in prefs.get("cuisine_likes", []) or []:
        _append_unique(intent.memory_tags, tag)
    if prefs.get("spouse_diet") == "减脂" and _has_spouse_context(intent):
        for tag in ["减脂", "健康", "低卡"]:
            _append_unique(intent.memory_tags, tag)


def _normalize_preferences(intent: Intent) -> None:
    """将 LLM 的自然语言偏好归一化到 Mock Data 标签体系"""
    food_map = {
        "清淡": "健康",
        "light": "健康",
        "healthy": "健康",
        "low calorie": "健康",
        "low_calorie": "健康",
        "低脂": "健康",
        "低卡": "健康",
        "减脂": "健康",
        "健康餐": "健康",
        "轻食": "健康",
        "沙拉": "健康",
    }
    activity_map = {
        "室内活动": "室内", "室内游玩": "室内",
        "适合小孩": "亲子", "适合孩子": "亲子", "儿童": "亲子",
        "小孩": "亲子", "宝宝": "亲子",
        "拍照打卡": "拍照", "打卡": "拍照",
        # LLM 可能输出的英文/类别词
        "amusement_park": "亲子", "amusement park": "亲子",
        "playground": "亲子", "trampoline": "运动",
        "KTV": "唱歌", "ktv": "唱歌", "karaoke": "唱歌",
        "cat_cafe": "撸猫", "cat cafe": "撸猫",
        "escape_room": "密室", "escape room": "密室",
        "live_house": "音乐", "live house": "音乐",
        "cinema": "观影", "movie": "观影", "电影": "观影",
        "esports": "电竞", "gaming": "电竞",
        "board_game": "桌游", "board game": "桌游",
        "park": "户外", "shopping": "购物",
        "coffee_shop": "咖啡", "cafe": "咖啡",
        "exhibition": "艺术", "museum": "艺术",
        "citywalk": "散步", "hiking": "户外",
    }

    def normalize(values: list[str], mapping: dict[str, str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            mapped = mapping.get(value, value)
            if mapped not in normalized:
                normalized.append(mapped)
        return normalized

    intent.food_preferences = normalize(intent.food_preferences, food_map)
    for value in intent.food_preferences:
        _append_unique(intent.tags, value)
    intent.activity_preferences = normalize(intent.activity_preferences, activity_map)
    for value in intent.activity_preferences:
        _append_unique(intent.tags, value)
    # 饮品偏好映射
    drink_map = {
        "喝咖啡": "coffee_tea", "咖啡": "coffee_tea", "奶茶": "coffee_tea",
        "喝酒": "bar", "啤酒": "bar", "精酿": "bar", "酒吧": "bar",
    }
    intent.drink_preferences = normalize(intent.drink_preferences, drink_map)
    delivery_map = {
        "takeout": "外卖",
        "delivery": "外卖",
        "food delivery": "外卖",
        "flash delivery": "闪送",
        "courier": "闪送",
        "cake": "蛋糕",
        "birthday cake": "蛋糕",
        "flower": "鲜花",
        "flowers": "鲜花",
        "gift": "儿童礼物",
        "present": "儿童礼物",
        "balloon": "儿童礼物",
        "fruit": "水果",
        "salad": "轻食",
    }
    intent.delivery_preferences = normalize(intent.delivery_preferences, delivery_map)
    for value in intent.delivery_preferences:
        if value not in {"外卖", "闪送"}:
            _append_unique(intent.tags, value)


def _valid_llm_field(key: str, value) -> bool:
    """过滤 LLM 常见的占位/零值，避免覆盖规则默认值。"""
    if value is None:
        return False
    if key in {"radius_km", "duration_hours"}:
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False
    if key in {"people_count", "budget_per_person", "child_age", "avoid_queue_minutes"}:
        try:
            return int(value) > 0
        except (TypeError, ValueError):
            return False
    return True
