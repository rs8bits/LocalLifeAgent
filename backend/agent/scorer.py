"""评分器 - 对候选方案进行可解释评分"""

from typing import Any

from backend.agent.schemas import Intent


def score_plan(plan: dict[str, Any], intent: Intent) -> dict[str, Any]:
    """对单个方案评分，返回带分值的方案"""
    party_type = intent.party_type
    if party_type == "family_with_child" or _intent_has_child(intent):
        scored = _score_family(plan, intent)
    elif party_type in {"family_elder", "family"}:
        scored = _score_family_group(plan, intent)
    elif party_type == "couple":
        scored = _score_couple(plan, intent)
    elif party_type == "business":
        scored = _score_business(plan, intent)
    elif party_type == "solo":
        scored = _score_solo(plan, intent)
    else:
        scored = _score_friends(plan, intent)
    return _apply_tag_match_bonus(scored)


def _intent_has_child(intent: Intent) -> bool:
    return intent.child_age is not None or any(c.get("role") == "child" for c in intent.companions)


def _plan_restaurants(plan: dict[str, Any]) -> list[dict[str, Any]]:
    entries = plan.get("meal_restaurants") or []
    restaurants = [
        entry.get("restaurant") for entry in entries
        if isinstance(entry, dict) and entry.get("restaurant")
    ]
    if restaurants:
        return restaurants
    restaurant = plan.get("restaurant")
    return [restaurant] if restaurant else []


def _score_restaurant_view(plan: dict[str, Any]) -> dict[str, Any]:
    restaurants = _plan_restaurants(plan)
    if not restaurants:
        return {}
    if len(restaurants) == 1:
        return restaurants[0]
    tags: list[str] = []
    party_types: list[str] = []
    for restaurant in restaurants:
        for tag in restaurant.get("tags", []) or []:
            if tag not in tags:
                tags.append(tag)
        for party_type in restaurant.get("party_types", []) or []:
            if party_type not in party_types:
                party_types.append(party_type)
    return {
        **restaurants[0],
        "tags": tags,
        "party_types": party_types,
        "avg_price": sum(r.get("avg_price", 0) for r in restaurants),
        "queue_minutes": sum(r.get("queue_minutes", 0) for r in restaurants),
        "distance_km": max(r.get("distance_km", 0) for r in restaurants),
        "rating": sum(r.get("rating", 0) for r in restaurants) / len(restaurants),
        "recommended_duration_min": sum(r.get("recommended_duration_min", 75) for r in restaurants),
        "_match_score": sum(r.get("_match_score", 0) for r in restaurants),
        "available": all(r.get("available", True) for r in restaurants),
        "bookable": all(r.get("bookable", True) for r in restaurants),
    }


def _apply_tag_match_bonus(plan: dict[str, Any]) -> dict[str, Any]:
    match_count = 0
    for key in ["activity", "drink"]:
        poi = plan.get(key) or {}
        match_count += int(poi.get("_match_score") or 0)
    for restaurant in _plan_restaurants(plan):
        match_count += int((restaurant or {}).get("_match_score") or 0)
    for item in plan.get("delivery_items") or []:
        match_count += int((item or {}).get("_match_score") or 0)
    if not match_count:
        return plan
    bonus = min(0.12, 0.015 * match_count)
    plan["score"] = round(min(1.0, plan.get("score", 0.0) + bonus), 3)
    plan.setdefault("score_reasons", []).append(f"标签匹配{match_count}项，按匹配数量加分")
    return plan


def _score_family(plan: dict[str, Any], intent: Intent) -> dict[str, Any]:
    """家庭场景评分"""
    activity = plan.get("activity") or {}
    restaurant = _score_restaurant_view(plan)
    drink = plan.get("drink") or {}

    reasons: list[str] = []

    # 1. 儿童适配 (0.30)
    child_fit = _score_child_fit(activity, intent, reasons)

    # 2. 距离 (0.15) -- 调整权重，给 drink 留空间
    distance = _score_distance(activity, restaurant, drink, intent, reasons)

    # 3. 餐厅健康 (0.20)
    health = _score_restaurant_health(restaurant, intent, reasons)

    # 4. 排队 (0.10)
    queue = _score_queue(activity, restaurant, drink, intent, reasons)

    # 5. 时间适配 (0.10)
    time_fit = _score_time_fit(activity, restaurant, drink, reasons)

    # 6. 价格 (0.05)
    price = _score_price(activity, restaurant, drink, intent, reasons)

    # 7. 饮品 (0.10)
    drink_score = _score_drink(drink, intent, reasons)

    score = round(
        child_fit * 0.30
        + distance * 0.15
        + health * 0.20
        + queue * 0.10
        + time_fit * 0.10
        + price * 0.05
        + drink_score * 0.10,
        3,
    )

    plan["score"] = score
    plan["score_reasons"] = reasons
    return plan


def _score_friends(plan: dict[str, Any], intent: Intent) -> dict[str, Any]:
    """朋友场景评分"""
    activity = plan.get("activity") or {}
    restaurant = _score_restaurant_view(plan)
    drink = plan.get("drink") or {}

    reasons: list[str] = []

    # 1. 社交属性 (0.20)
    social = _score_social(activity, restaurant, reasons)

    # 2. 拍照 (0.15)
    photo = _score_photo(activity, restaurant, drink, intent, reasons)

    # 3. 美食 (0.15)
    food = _score_food(restaurant, reasons)

    # 4. 距离 (0.10)
    distance = _score_distance(activity, restaurant, drink, intent, reasons)

    # 5. 时间适配 (0.10)
    time_fit = _score_time_fit(activity, restaurant, drink, reasons)

    # 6. 价格 (0.10)
    price = _score_price(activity, restaurant, drink, intent, reasons)

    # 7. 饮品 (0.20) -- 朋友场景饮品权重更高
    drink_score = _score_drink(drink, intent, reasons)

    score = round(
        social * 0.20
        + photo * 0.15
        + food * 0.15
        + distance * 0.10
        + time_fit * 0.10
        + price * 0.10
        + drink_score * 0.20,
        3,
    )

    plan["score"] = score
    plan["score_reasons"] = reasons
    return plan


def _score_family_group(plan: dict[str, Any], intent: Intent) -> dict[str, Any]:
    """不带儿童的家庭/长辈场景评分：少折腾、少排队、健康和安静优先。"""
    activity = plan.get("activity") or {}
    restaurant = _score_restaurant_view(plan)
    drink = plan.get("drink") or {}
    reasons: list[str] = []

    distance = _score_distance(activity, restaurant, drink, intent, reasons)
    queue = _score_queue(activity, restaurant, drink, intent, reasons)
    health = _score_restaurant_health(restaurant, intent, reasons)
    quiet = _score_quiet_comfort(activity, restaurant, drink, intent, reasons)
    food = _score_food(restaurant, reasons)
    time_fit = _score_time_fit(activity, restaurant, drink, reasons)
    price = _score_price(activity, restaurant, drink, intent, reasons)

    if intent.party_type == "family_elder":
        score = round(
            distance * 0.25
            + queue * 0.20
            + quiet * 0.20
            + health * 0.15
            + food * 0.10
            + time_fit * 0.05
            + price * 0.05,
            3,
        )
    else:
        score = round(
            distance * 0.20
            + queue * 0.15
            + health * 0.20
            + quiet * 0.10
            + food * 0.15
            + time_fit * 0.10
            + price * 0.10,
            3,
        )

    plan["score"] = score
    plan["score_reasons"] = reasons
    return plan


def _score_couple(plan: dict[str, Any], intent: Intent) -> dict[str, Any]:
    """情侣/夫妻二人场景评分：氛围、拍照、品质和距离优先。"""
    activity = plan.get("activity") or {}
    restaurant = _score_restaurant_view(plan)
    drink = plan.get("drink") or {}
    reasons: list[str] = []

    photo = _score_photo(activity, restaurant, drink, intent, reasons)
    ambience = _score_ambience(activity, restaurant, drink, reasons)
    food = _score_food(restaurant, reasons)
    drink_score = _score_drink(drink, intent, reasons)
    distance = _score_distance(activity, restaurant, drink, intent, reasons)
    queue = _score_queue(activity, restaurant, drink, intent, reasons)
    price = _score_price(activity, restaurant, drink, intent, reasons)

    score = round(
        ambience * 0.20
        + photo * 0.20
        + food * 0.20
        + drink_score * 0.15
        + distance * 0.10
        + queue * 0.10
        + price * 0.05,
        3,
    )
    plan["score"] = score
    plan["score_reasons"] = reasons
    return plan


def _score_business(plan: dict[str, Any], intent: Intent) -> dict[str, Any]:
    """商务/客户场景评分：品质、安静、稳定可执行优先。"""
    activity = plan.get("activity") or {}
    restaurant = _score_restaurant_view(plan)
    drink = plan.get("drink") or {}
    reasons: list[str] = []

    food = _score_food(restaurant, reasons)
    quiet = _score_quiet_comfort(activity, restaurant, drink, intent, reasons)
    queue = _score_queue(activity, restaurant, drink, intent, reasons)
    distance = _score_distance(activity, restaurant, drink, intent, reasons)
    time_fit = _score_time_fit(activity, restaurant, drink, reasons)
    price = _score_price(activity, restaurant, drink, intent, reasons)

    score = round(
        food * 0.25
        + quiet * 0.25
        + queue * 0.20
        + distance * 0.15
        + time_fit * 0.10
        + price * 0.05,
        3,
    )
    plan["score"] = score
    plan["score_reasons"] = reasons
    return plan


def _score_solo(plan: dict[str, Any], intent: Intent) -> dict[str, Any]:
    """单人场景评分：近、轻量、性价比和偏好匹配优先。"""
    activity = plan.get("activity") or {}
    restaurant = _score_restaurant_view(plan)
    drink = plan.get("drink") or {}
    reasons: list[str] = []

    distance = _score_distance(activity, restaurant, drink, intent, reasons)
    food = _score_food(restaurant, reasons)
    drink_score = _score_drink(drink, intent, reasons)
    queue = _score_queue(activity, restaurant, drink, intent, reasons)
    time_fit = _score_time_fit(activity, restaurant, drink, reasons)
    price = _score_price(activity, restaurant, drink, intent, reasons)

    score = round(
        distance * 0.25
        + food * 0.20
        + drink_score * 0.15
        + queue * 0.15
        + time_fit * 0.10
        + price * 0.15,
        3,
    )
    plan["score"] = score
    plan["score_reasons"] = reasons
    return plan


# ── 各维度评分函数 (0.0 ~ 1.0) ─────────────────────────────

def _score_child_fit(activity: dict, intent: Intent, reasons: list[str]) -> float:
    if not activity:
        reasons.append("无活动信息，儿童适配默认0.5")
        return 0.5

    child_friendly = activity.get("child_friendly", False)
    child_age = intent.child_age

    if not child_age:
        reasons.append("未提供儿童年龄，儿童适配默认0.6")
        return 0.6 if child_friendly else 0.3

    age_min = activity.get("suitable_age_min", 0)
    age_max = activity.get("suitable_age_max", 99)

    if age_min <= child_age <= age_max and child_friendly:
        reasons.append(f"活动适合{child_age}岁儿童，且亲子友好 (+0.30)")
        return 1.0
    elif age_min <= child_age <= age_max:
        reasons.append(f"活动适合{child_age}岁儿童 (+0.23)")
        return 0.75
    elif child_friendly:
        reasons.append("活动标注为亲子友好 (+0.15)")
        return 0.5
    else:
        reasons.append(f"活动不适合{child_age}岁儿童 (+0.0)")
        return 0.0


def _score_distance(
    activity: dict, restaurant: dict, drink: dict | None, intent: Intent, reasons: list[str]
) -> float:
    act_dist = activity.get("distance_km", 0) if activity else 0
    rest_dist = restaurant.get("distance_km", 0) if restaurant else 0
    drink_dist = drink.get("distance_km", 0) if drink else 0
    max_dist = max(act_dist, rest_dist, drink_dist)
    radius = intent.radius_km

    if max_dist <= radius:
        reasons.append(f"距离{max_dist}km在范围内")
        return 1.0
    elif max_dist <= radius * 1.5:
        reasons.append(f"距离{max_dist}km稍超范围")
        return 0.6
    elif max_dist <= radius * 2:
        reasons.append(f"距离{max_dist}km较远")
        return 0.3
    else:
        reasons.append(f"距离{max_dist}km过远")
        return 0.1


def _score_restaurant_health(
    restaurant: dict, intent: Intent, reasons: list[str]
) -> float:
    if not restaurant:
        reasons.append("无餐厅信息，健康分默认0.5")
        return 0.5

    if not intent.needs_low_calorie:
        reasons.append("无特殊饮食需求 (+0.20)")
        return 1.0

    score = 0.0
    if restaurant.get("low_calorie_options"):
        score += 0.5
        reasons.append("餐厅提供低卡选项 (+0.10)")
    tags = restaurant.get("tags", [])
    if any(t in tags for t in ["健康", "轻食", "低卡", "减脂"]):
        score += 0.3
        reasons.append("餐厅标签含健康/轻食 (+0.06)")
    if restaurant.get("cuisine") in ["健康轻食", "素食"]:
        score += 0.2
        reasons.append("餐厅类型为健康轻食/素食 (+0.04)")

    return min(score, 1.0)


def _score_queue(
    activity: dict, restaurant: dict, drink: dict | None, intent: Intent, reasons: list[str]
) -> float:
    act_queue = activity.get("queue_minutes", 0) if activity else 0
    rest_queue = restaurant.get("queue_minutes", 0) if restaurant else 0
    drink_queue = drink.get("queue_minutes", 0) if drink else 0
    total_queue = act_queue + rest_queue + drink_queue

    threshold = intent.avoid_queue_minutes

    if total_queue <= threshold:
        reasons.append(f"总排队{total_queue}分钟，可接受")
        return 1.0
    elif total_queue <= threshold * 2:
        reasons.append(f"总排队{total_queue}分钟，稍长")
        return 0.5
    else:
        reasons.append(f"总排队{total_queue}分钟，过长")
        return 0.1


def _score_time_fit(activity: dict, restaurant: dict, drink: dict | None, reasons: list[str]) -> float:
    act_dur = activity.get("recommended_duration_min", 90) if activity else 90
    rest_dur = restaurant.get("recommended_duration_min", 60) if restaurant else 60
    drink_dur = drink.get("recommended_duration_min", 25) if drink else 0
    total = act_dur + rest_dur + drink_dur

    if 180 <= total <= 420:
        reasons.append(f"总时长{total}分钟适合出行")
        return 1.0
    elif total < 180:
        reasons.append(f"总时长{total}分钟偏短")
        return 0.5
    else:
        reasons.append(f"总时长{total}分钟偏长")
        return 0.3


def _score_price(
    activity: dict, restaurant: dict, drink: dict | None, intent: Intent, reasons: list[str]
) -> float:
    act_price = activity.get("avg_price", 0) if activity else 0
    rest_price = restaurant.get("avg_price", 0) if restaurant else 0
    drink_price = drink.get("avg_price", 0) if drink else 0
    total = act_price + rest_price + drink_price
    per_person = total  # avg_price 已经是人均

    if intent.budget_per_person and per_person > intent.budget_per_person:
        reasons.append(f"人均{per_person}元超出预算{intent.budget_per_person}元 (+0.0)")
        return 0.2

    if per_person <= 100:
        reasons.append(f"人均{per_person}元经济实惠 (+0.05)")
        return 1.0
    elif per_person <= 200:
        reasons.append(f"人均{per_person}元适中 (+0.04)")
        return 0.8
    elif per_person <= 300:
        reasons.append(f"人均{per_person}元中等偏上 (+0.02)")
        return 0.5
    else:
        reasons.append(f"人均{per_person}元较贵 (+0.01)")
        return 0.3


def _score_social(activity: dict, restaurant: dict, reasons: list[str]) -> float:
    score = 0.0
    act_tags = activity.get("tags", [])
    rest_tags = restaurant.get("tags", [])

    social_tags = {"社交", "聚会", "桌游", "互动"}
    if any(t in social_tags for t in act_tags):
        score += 0.15
        reasons.append("活动有社交标签 (+0.04)")
    if any(t in social_tags for t in rest_tags):
        score += 0.1
        reasons.append("餐厅有聚会标签 (+0.03)")

    if "friends" in activity.get("party_types", []) or activity.get("scene") == "friends":
        score += 0.2
        reasons.append("活动适合朋友同行 (+0.05)")
    if "friends" in restaurant.get("party_types", []) or restaurant.get("scene") == "friends":
        score += 0.2
        reasons.append("餐厅适合朋友同行 (+0.05)")

    # 人数适配
    party_max = restaurant.get("party_size_max", 4)
    if party_max >= 4:
        score += 0.2
        reasons.append("餐厅支持4人以上 (+0.05)")
    else:
        score += 0.05

    return min(score, 1.0)


def _score_photo(
    activity: dict, restaurant: dict, drink: dict | None, intent: Intent, reasons: list[str]
) -> float:
    if not intent.needs_photo_spot:
        reasons.append("无拍照需求")
        return 1.0

    score = 0.0
    act_tags = activity.get("tags", []) if activity else []
    rest_tags = restaurant.get("tags", []) if restaurant else []
    drink_tags = drink.get("tags", []) if drink else []

    if any(t in act_tags for t in ["拍照", "打卡", "颜值"]):
        score += 0.3
        reasons.append("活动适合拍照")
    if any(t in rest_tags for t in ["拍照", "约会", "出片"]):
        score += 0.3
        reasons.append("餐厅适合拍照")
    if any(t in drink_tags for t in ["拍照", "打卡", "网红"]):
        score += 0.2
        reasons.append("饮品店适合拍照")
    score += 0.2  # base
    return min(score, 1.0)


def _score_food(restaurant: dict, reasons: list[str]) -> float:
    if not restaurant:
        reasons.append("无餐厅信息，美食评分默认0.5")
        return 0.5

    rating = restaurant.get("rating", 4.0)
    popularity = restaurant.get("popularity_score", 50)
    tags = restaurant.get("tags", [])

    score = 0.0
    if rating >= 4.5:
        score += 0.35
        reasons.append(f"评分{rating}高 (+0.07)")
    else:
        score += 0.2
        reasons.append(f"评分{rating}中等 (+0.04)")

    if popularity >= 80:
        score += 0.2
        reasons.append(f"热度{popularity}高 (+0.04)")
    else:
        score += 0.1

    if any(t in tags for t in ["美食", "好吃", "品质", "网红"]):
        score += 0.25
        reasons.append("餐厅有美食/品质标签 (+0.05)")
    else:
        score += 0.1

    return min(score, 1.0)


def _score_quiet_comfort(
    activity: dict, restaurant: dict, drink: dict | None, intent: Intent, reasons: list[str]
) -> float:
    """安静舒适/少走路评分，服务长辈和商务场景。"""
    score = 0.5
    all_tags = (
        (activity.get("tags", []) if activity else [])
        + (restaurant.get("tags", []) if restaurant else [])
        + (drink.get("tags", []) if drink else [])
    )
    if any(t in all_tags for t in ["安静", "包间", "高品质", "约会", "舒适"]):
        score += 0.25
        reasons.append("标签匹配安静/舒适需求")
    if restaurant.get("bookable") or restaurant.get("available"):
        score += 0.10
        reasons.append("餐厅可订/可用，适合稳定安排")
    if intent.needs_less_walking:
        max_dist = max(
            activity.get("distance_km", 0) if activity else 0,
            restaurant.get("distance_km", 0) if restaurant else 0,
            drink.get("distance_km", 0) if drink else 0,
        )
        if max_dist <= min(intent.radius_km, 5):
            score += 0.15
            reasons.append("距离较近，适合少走路")
        else:
            score -= 0.15
            reasons.append("距离偏远，长辈/少走路场景扣分")
    if intent.needs_quiet and not any(t in all_tags for t in ["安静", "包间", "高品质", "约会", "舒适"]):
        score -= 0.10
        reasons.append("缺少安静/私密标签")
    return max(0.0, min(score, 1.0))


def _score_ambience(activity: dict, restaurant: dict, drink: dict | None, reasons: list[str]) -> float:
    """约会/二人场景氛围评分。"""
    all_tags = (
        (activity.get("tags", []) if activity else [])
        + (restaurant.get("tags", []) if restaurant else [])
        + (drink.get("tags", []) if drink else [])
    )
    score = 0.4
    if any(t in all_tags for t in ["约会", "拍照", "出片", "网红", "高品质", "音乐"]):
        score += 0.4
        reasons.append("氛围/约会标签匹配")
    rating = max(
        activity.get("rating", 0) if activity else 0,
        restaurant.get("rating", 0) if restaurant else 0,
        drink.get("rating", 0) if drink else 0,
    )
    if rating >= 4.5:
        score += 0.2
        reasons.append(f"最高评分{rating}，品质较稳")
    return min(score, 1.0)


def _score_drink(drink: dict | None, intent: Intent, reasons: list[str]) -> float:
    """饮品评分"""
    if not drink:
        return 0.5  # 无饮品时不惩罚

    score = 0.0
    prefs = intent.drink_preferences or []

    # 品类匹配
    sub_cat = drink.get("sub_category", "")
    if "bar" in prefs and sub_cat == "bar":
        score += 0.4
        reasons.append("酒吧匹配用户偏好")
    elif "coffee_tea" in prefs and sub_cat in ("coffee", "tea", "milk_tea"):
        score += 0.4
        reasons.append("茶饮/咖啡匹配用户偏好")
    elif not prefs:
        score += 0.3
        reasons.append("无明确饮品偏好")
    else:
        score += 0.1

    # 评分
    rating = drink.get("rating", 4.0)
    if rating >= 4.5:
        score += 0.25
        reasons.append(f"饮品评分{rating}高")

    # 热门度
    popularity = drink.get("popularity_score", 50)
    if popularity >= 80:
        score += 0.15
        reasons.append("饮品店热度高")

    # 预约可用
    if drink.get("bookable"):
        score += 0.1
        reasons.append("饮品支持预约")
    else:
        score += 0.1  # 不扣分但也不加分

    return min(score, 1.0)
