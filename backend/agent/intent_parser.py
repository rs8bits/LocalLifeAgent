"""意图解析器 - 从自然语言提取结构化 Intent"""

import re
import json
from typing import Optional

from backend.agent.schemas import Intent
from backend.llm.deepseek_client import deepseek_client, LLMResult


# ── 规则兜底解析 ──────────────────────────────────────────────

def _rule_parse(message: str) -> Intent:
    """基于关键词规则的意图解析，始终可用"""
    msg = message.lower()

    # 场景
    family_kw = ["老婆", "孩子", "儿子", "女儿", "亲子", "家庭", "宝宝", "小朋友", "老公"]
    friends_kw = ["朋友", "同学", "同事", "几个人", "聚会", "拍照", "好玩", "桌游", "喝咖啡"]

    scene = "general"
    if any(kw in message for kw in family_kw):
        scene = "family"
    elif any(kw in message for kw in friends_kw):
        scene = "friends"

    # 时间窗口
    time_window = "afternoon"
    if any(kw in message for kw in ["傍晚", "晚上", "晚餐", "晚饭", "夜间"]):
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
    # 家庭默认：有老婆+孩子 → 至少 3 人
    if people_count is None and scene == "family":
        count = 1  # self
        if any(kw in message for kw in ["老婆", "老公"]):
            count += 1
        if any(kw in message for kw in ["孩子", "儿子", "女儿", "宝宝", "小朋友"]):
            count += 1
        if count > 1:
            people_count = count

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
        delivery_preferences.append("儿童礼物" if scene == "family" else "惊喜")
    if any(kw in message for kw in ["水果", "水果拼盘"]):
        delivery_preferences.append("水果")

    # 低卡需求
    needs_low_calorie = any(
        kw in message for kw in ["减肥", "减脂", "清淡", "低卡", "轻食", "健康餐"]
    )

    # 拍照需求
    needs_photo_spot = any(kw in message for kw in ["拍照", "打卡", "好看", "出片"])

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
        date=date,
        time_window=time_window,
        duration_hours=duration_hours,
        people_count=people_count,
        companions=_build_companions(message, scene, child_age),
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
        avoid_queue_minutes=avoid_queue_minutes,
    )


def _build_companions(message: str, scene: str, child_age: Optional[int]) -> list[dict]:
    """从消息中提取同行人信息"""
    companions = []
    if "老婆" in message:
        companions.append({"role": "spouse", "diet_preference": "减脂" if "减肥" in message else None})
    if "老公" in message:
        companions.append({"role": "spouse"})
    if any(kw in message for kw in ["孩子", "儿子", "女儿", "宝宝", "小朋友"]):
        companions.append({"role": "child", "age": child_age})
    if scene == "friends":
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
  "avoid_queue_minutes": int
}

规则：
- scene: 提到老婆/孩子/亲子 → family；朋友/同学/聚会 → friends
- child_age: 从"孩子X岁"中提取
- needs_low_calorie: 提到减肥/减脂/清淡/低卡 → true
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
            for key in ["scene", "date", "time_window", "duration_hours",
                        "people_count", "radius_km", "distance_preference",
                        "budget_per_person", "child_age", "needs_low_calorie",
                        "needs_photo_spot", "avoid_queue_minutes"]:
                if key in intent_dict and intent_dict[key] is not None:
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

    # 合并用户记忆（用户输入优先，记忆仅作为默认值）
    # 家庭/个人属性仅在家场景或用户明确提到家庭成员时合并
    if user_memory:
        prefs = user_memory.get("preferences", {})
        is_family_context = intent.scene == "family"
        if not intent.child_age and prefs.get("child_age") and is_family_context:
            intent.child_age = prefs["child_age"]
        if intent.radius_km == 5.0 and prefs.get("max_distance_km"):
            intent.radius_km = float(prefs["max_distance_km"])
        if intent.avoid_queue_minutes == 30 and prefs.get("max_queue_minutes"):
            intent.avoid_queue_minutes = prefs["max_queue_minutes"]
        if not intent.food_preferences and prefs.get("cuisine_likes"):
            intent.food_preferences = [tag for tag in prefs.get("cuisine_likes", [])]
        if prefs.get("spouse_diet") == "减脂" and is_family_context:
            intent.needs_low_calorie = True

        # companions: 朋友场景不加入 child/spouse
        if is_family_context and not intent.companions:
            if prefs.get("child_age") and prefs.get("child_name"):
                intent.companions.append({"role": "child", "age": prefs["child_age"]})
            if prefs.get("spouse_diet"):
                intent.companions.append({"role": "spouse", "diet_preference": prefs["spouse_diet"]})

    _normalize_preferences(intent)
    return intent


def _normalize_preferences(intent: Intent) -> None:
    """将 LLM 的自然语言偏好归一化到 Mock Data 标签体系"""
    food_map = {
        "清淡": "健康",
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
