"""意图解析器 - 从自然语言提取结构化 Intent"""

import re
import json
from typing import Optional

from backend.agent.schemas import Intent
from backend.llm.deepseek_client import deepseek_client, LLMResult


CHILD_KW = ["孩子", "儿子", "女儿", "亲子", "宝宝", "小朋友", "儿童", "娃"]
SPOUSE_KW = ["老婆", "老公", "妻子", "丈夫", "爱人"]
ELDER_KW = ["爸妈", "父母", "爸爸", "妈妈", "老人", "长辈", "爷爷", "奶奶", "外公", "外婆", "公婆", "岳父", "岳母"]
RELATIVE_KW = ["亲戚", "亲人", "全家", "一家人", "家里人", "表哥", "表姐", "堂哥", "堂姐", "兄弟姐妹"]
COUPLE_KW = ["情侣", "约会", "对象", "女朋友", "男朋友", "纪念日", "二人世界"]
FRIENDS_KW = ["朋友", "同学", "哥们", "闺蜜", "聚会", "拍照", "好玩", "桌游", "喝咖啡"]
BUSINESS_KW = ["客户", "商务", "领导", "老板", "合作方", "商务饭局", "商务宴请"]
COLLEAGUE_KW = ["同事", "团队", "团建", "部门"]
SOLO_KW = ["一个人", "自己", "独自", "单人", "我一个"]


def _has_any(message: str, keywords: list[str]) -> bool:
    return any(kw in message for kw in keywords)


def _infer_party_type_and_scene(message: str) -> tuple[str, str]:
    """推断真实同行人画像和兼容 mock 数据的粗 scene。"""
    has_child = _has_any(message, CHILD_KW)
    has_spouse = _has_any(message, SPOUSE_KW)
    has_elder = _has_any(message, ELDER_KW)
    has_relative = _has_any(message, RELATIVE_KW)
    has_couple = _has_any(message, COUPLE_KW)
    has_friends = _has_any(message, FRIENDS_KW)
    has_business = _has_any(message, BUSINESS_KW)
    has_colleague = _has_any(message, COLLEAGUE_KW)
    has_solo = _has_any(message, SOLO_KW)

    if has_business:
        return "business", "friends"
    if has_child:
        return "family_with_child", "family"
    if has_elder:
        return "family_elder", "family"
    if has_relative:
        return "family", "family"
    if has_couple or has_spouse:
        return "couple", "friends"
    if has_friends or has_colleague:
        return "friends", "friends"
    if has_solo:
        return "solo", "general"
    return "general", "general"


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
    time_window = "afternoon"
    if any(kw in message for kw in ["傍晚", "晚上", "今晚", "晚餐", "晚饭", "夜间"]):
        time_window = "evening"
    elif any(kw in message for kw in ["上午", "早上", "中午"]):
        time_window = "afternoon"

    # 日期
    date = "today"
    if "明天" in message or "明日" in message:
        date = "tomorrow"

    # 时长
    duration_hours = None
    dur_match = re.search(r"(\d+)\s*个小?时", message)
    if dur_match:
        duration_hours = int(dur_match.group(1))

    # 人数
    people_count = None
    people_patterns = [
        r"(\d+)\s*个人",
        r"(\d+)\s*位",
        r"(\d+)\s*个朋友",
        r"(\d+)\s*个同学",
        r"(\d+)\s*个同事",
        r"(\d+)\s*个[人位]",
    ]
    for pat in people_patterns:
        m = re.search(pat, message)
        if m:
            people_count = int(m.group(1))
            break
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
    if any(kw in message for kw in ["KTV", "唱歌", "密室", "撸猫", "电竞", "蹦床", "LiveHouse", "livehouse", "演出"]):
        activity_preferences.append("社交")
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
    if any(kw in message for kw in ["外卖", "点个", "送餐", "送到餐厅", "送到", "配送"]):
        delivery_preferences.append("外卖")
    if any(kw in message for kw in ["闪送", "跑腿", "急送", "同城送"]):
        delivery_preferences.append("闪送")
    if any(kw in message for kw in ["蛋糕", "生日蛋糕"]):
        delivery_preferences.append("蛋糕")
    if any(kw in message for kw in ["花", "鲜花", "花束"]):
        delivery_preferences.append("鲜花")
    if any(kw in message for kw in ["礼物", "礼盒", "气球", "惊喜"]):
        delivery_preferences.append("儿童礼物" if party_type == "family_with_child" else "惊喜")
    if any(kw in message for kw in ["水果", "水果拼盘"]):
        delivery_preferences.append("水果")

    # 低卡需求
    needs_low_calorie = any(
        kw in message for kw in ["减肥", "减脂", "清淡", "低卡", "轻食", "健康餐"]
    )

    # 拍照需求
    needs_photo_spot = any(kw in message for kw in ["拍照", "打卡", "好看", "出片"])

    needs_quiet = any(kw in message for kw in ["安静", "别吵", "不吵", "私密", "包间", "适合聊天", "正式"])
    needs_less_walking = (
        party_type == "family_elder"
        or any(kw in message for kw in ["少走路", "别太累", "不累", "腿脚", "老人方便", "好停车"])
    )

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
        date=date,
        time_window=time_window,
        duration_hours=duration_hours,
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
    if _has_any(message, CHILD_KW):
        companions.append({"role": "child", "age": child_age})
    if _has_any(message, ELDER_KW):
        role = "parent" if any(kw in message for kw in ["爸妈", "父母", "爸爸", "妈妈"]) else "elder"
        companions.append({"role": role, "mobility": "low" if party_type == "family_elder" else None})
    if _has_any(message, RELATIVE_KW):
        companions.append({"role": "relative"})
    if party_type == "business":
        companions.append({"role": "client" if "客户" in message else "colleague"})
    if party_type == "friends":
        # 提取朋友人数
        m = re.search(r"(\d+)\s*(个|位)", message)
        count = int(m.group(1)) if m else 2
        for _ in range(count):
            companions.append({"role": "friend"})
    return companions


# ── LLM 解析 ───────────────────────────────────────────────────

INTENT_SYSTEM_PROMPT = """你是一个意图解析器。根据用户输入，提取以下结构化信息，仅输出 JSON：

{
  "scene": "family" | "friends" | "general",
  "party_type": "family_with_child" | "family_elder" | "family" | "friends" | "couple" | "solo" | "business" | "general",
  "date": "today" | "tomorrow" | 具体日期,
  "time_window": "morning" | "afternoon" | "evening" | "unknown",
  "duration_hours": int | null,
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
- scene 是兼容搜索字段：亲子/爸妈/亲戚 → family；朋友/同事/情侣/商务 → friends；单人/不明确 → general
- party_type 是真实同行人画像：带孩子 → family_with_child；爸妈/老人 → family_elder；亲戚/全家 → family；情侣/夫妻二人 → couple；朋友/同学/同事 → friends；客户/商务/领导 → business；一个人 → solo
- child_age: 从"孩子X岁"中提取
- needs_low_calorie: 提到减肥/减脂/清淡/低卡 → true
- needs_quiet: 提到安静/包间/私密/正式 → true
- needs_less_walking: 提到爸妈/老人/少走路/别太累/腿脚不便 → true
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
            for key in ["scene", "party_type", "date", "time_window", "duration_hours",
                        "people_count", "radius_km", "distance_preference",
                        "budget_per_person", "child_age", "needs_low_calorie",
                        "needs_photo_spot", "needs_quiet", "needs_less_walking",
                        "avoid_queue_minutes"]:
                if key in intent_dict and _valid_llm_field(key, intent_dict[key]):
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
        except Exception:
            pass  # LLM 部分字段解析失败，保留规则结果

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
        if not intent.food_preferences and prefs.get("cuisine_likes"):
            intent.food_preferences = [tag for tag in prefs.get("cuisine_likes", [])]
        if prefs.get("spouse_diet") == "减脂" and _has_spouse_context(intent):
            intent.needs_low_calorie = True

        # companions: 朋友场景不加入 child/spouse
        if not intent.companions:
            if _has_child_context(intent) and prefs.get("child_age") and prefs.get("child_name"):
                intent.companions.append({"role": "child", "age": prefs["child_age"]})
            if _has_spouse_context(intent) and prefs.get("spouse_diet"):
                intent.companions.append({"role": "spouse", "diet_preference": prefs["spouse_diet"]})

    _normalize_preferences(intent)
    _normalize_party_fields(intent)
    return intent


def _normalize_party_fields(intent: Intent) -> None:
    """把 LLM/规则输出统一到 party_type + 兼容 scene。"""
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

    if party in {"family_with_child", "family_elder", "family"}:
        intent.scene = "family"
    elif party in {"friends", "couple", "business"}:
        intent.scene = "friends"
    else:
        intent.scene = "general"

    if party == "family_elder":
        intent.needs_less_walking = True
    if party == "business":
        intent.needs_quiet = True


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
    intent.activity_preferences = normalize(intent.activity_preferences, activity_map)
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
