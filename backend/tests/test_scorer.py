"""评分器测试"""

from backend.agent.schemas import Intent
from backend.agent.scorer import score_plan


def _make_family_intent(**overrides) -> Intent:
    defaults = {
        "scene": "family",
        "party_type": "family_with_child",
        "child_age": 5,
        "needs_low_calorie": True,
        "radius_km": 5.0,
        "avoid_queue_minutes": 30,
        "people_count": 3,
        "needs_photo_spot": False,
    }
    defaults.update(overrides)
    return Intent(**defaults)


def _make_friends_intent(**overrides) -> Intent:
    defaults = {
        "scene": "friends",
        "party_type": "friends",
        "needs_photo_spot": True,
        "radius_km": 8.0,
        "avoid_queue_minutes": 45,
        "people_count": 4,
        "needs_low_calorie": False,
    }
    defaults.update(overrides)
    return Intent(**defaults)


class TestScorerFamily:
    """家庭场景评分"""

    def test_child_friendly_scores_high(self):
        intent = _make_family_intent()
        plan = {
            "plan_id": "test_001",
            "activity": {
                "name": "亲子乐园", "distance_km": 2.0,
                "child_friendly": True, "suitable_age_min": 2, "suitable_age_max": 12,
                "queue_minutes": 5, "avg_price": 100, "recommended_duration_min": 120,
            },
            "restaurant": {
                "name": "健康餐厅", "distance_km": 2.5,
                "low_calorie_options": True, "tags": ["健康", "轻食"],
                "queue_minutes": 5, "avg_price": 68, "recommended_duration_min": 60,
            },
        }
        result = score_plan(plan, intent)
        assert result["score"] > 0.6
        assert len(result["score_reasons"]) > 0

    def test_not_child_friendly_scores_low(self):
        intent = _make_family_intent(child_age=3)
        plan = {
            "plan_id": "test_002",
            "activity": {
                "name": "成人展览", "distance_km": 3.0,
                "child_friendly": False, "suitable_age_min": 12, "suitable_age_max": 99,
                "queue_minutes": 10, "avg_price": 150, "recommended_duration_min": 90,
            },
            "restaurant": {
                "name": "酒吧餐厅", "distance_km": 3.0,
                "low_calorie_options": False, "tags": ["酒吧"],
                "queue_minutes": 5, "avg_price": 200, "recommended_duration_min": 60,
            },
        }
        result = score_plan(plan, intent)
        assert result["score"] < 0.5

    def test_long_queue_penalized(self):
        intent = _make_family_intent(avoid_queue_minutes=15)
        plan = {
            "plan_id": "test_003",
            "activity": {
                "name": "热门乐园", "distance_km": 2.0,
                "child_friendly": True, "suitable_age_min": 2, "suitable_age_max": 12,
                "queue_minutes": 60, "avg_price": 100, "recommended_duration_min": 120,
            },
            "restaurant": {
                "name": "网红店", "distance_km": 2.0,
                "low_calorie_options": False, "tags": [],
                "queue_minutes": 50, "avg_price": 80, "recommended_duration_min": 60,
            },
        }
        result = score_plan(plan, intent)
        # 排队分应该很低
        assert result["score"] < 0.7

    def test_far_distance_penalized(self):
        intent = _make_family_intent(radius_km=3.0)
        plan = {
            "plan_id": "test_004",
            "activity": {
                "name": "远郊乐园", "distance_km": 15.0,
                "child_friendly": True, "suitable_age_min": 2, "suitable_age_max": 12,
                "queue_minutes": 5, "avg_price": 80, "recommended_duration_min": 120,
            },
            "restaurant": {
                "name": "远郊餐厅", "distance_km": 15.0,
                "low_calorie_options": True, "tags": ["健康"],
                "queue_minutes": 5, "avg_price": 60, "recommended_duration_min": 60,
            },
        }
        result = score_plan(plan, intent)
        # 远距离应该降低分数（满分1.0，远距离会显著降分）
        assert result["score"] < 0.82, f"远距离方案分数应较低，但得到{result['score']}"

    def test_score_range_zero_to_one(self):
        intent = _make_family_intent()
        plan = {
            "plan_id": "test_range",
            "activity": {
                "name": "正常活动", "distance_km": 3.0,
                "child_friendly": True, "suitable_age_min": 2, "suitable_age_max": 12,
                "queue_minutes": 10, "avg_price": 120, "recommended_duration_min": 120,
            },
            "restaurant": {
                "name": "正常餐厅", "distance_km": 3.0,
                "low_calorie_options": True, "tags": ["健康"],
                "queue_minutes": 10, "avg_price": 80, "recommended_duration_min": 60,
            },
        }
        result = score_plan(plan, intent)
        assert 0.0 <= result["score"] <= 1.0


class TestScorerFriends:
    """朋友场景评分"""

    def test_social_photo_scores_high(self):
        intent = _make_friends_intent()
        plan = {
            "plan_id": "test_friends_001",
            "activity": {
                "name": "桌游俱乐部", "distance_km": 3.0,
                "tags": ["社交", "聚会"], "scene": "friends",
                "avg_price": 68, "queue_minutes": 10, "recommended_duration_min": 120,
            },
            "restaurant": {
                "name": "网红餐厅", "distance_km": 3.0,
                "tags": ["拍照", "约会"], "scene": "friends",
                "rating": 4.8, "popularity_score": 90,
                "party_size_max": 6,
                "avg_price": 150, "queue_minutes": 20, "recommended_duration_min": 75,
            },
        }
        result = score_plan(plan, intent)
        assert result["score"] > 0.5
        assert len(result["score_reasons"]) > 0

    def test_photo_score_high_when_needed(self):
        intent = _make_friends_intent(needs_photo_spot=True)
        plan = {
            "plan_id": "test_photo",
            "activity": {
                "name": "艺术展", "distance_km": 4.0,
                "tags": ["拍照", "打卡"], "scene": "friends",
                "avg_price": 128, "queue_minutes": 15, "recommended_duration_min": 90,
            },
            "restaurant": {
                "name": "网红打卡店", "distance_km": 4.0,
                "tags": ["拍照", "出片"], "scene": "friends",
                "rating": 4.6, "popularity_score": 85, "party_size_max": 4,
                "avg_price": 180, "queue_minutes": 25, "recommended_duration_min": 60,
            },
        }
        result = score_plan(plan, intent)
        assert result["score"] > 0.5

    def test_photo_not_penalized_when_not_needed(self):
        intent = _make_friends_intent(needs_photo_spot=False)
        plan = {
            "plan_id": "test_no_photo",
            "activity": {
                "name": "普通活动", "distance_km": 3.0,
                "tags": [], "scene": "friends",
                "avg_price": 50, "queue_minutes": 5, "recommended_duration_min": 60,
            },
            "restaurant": {
                "name": "普通餐厅", "distance_km": 3.0,
                "tags": [], "scene": "friends",
                "rating": 4.0, "popularity_score": 60, "party_size_max": 4,
                "avg_price": 80, "queue_minutes": 10, "recommended_duration_min": 60,
            },
        }
        result = score_plan(plan, intent)
        assert result["score"] > 0.3  # 拍照无需求时不应惩罚


class TestScorerWithDrink:
    """含饮品方案的评分"""

    def test_drink_scores_nonzero(self):
        intent = _make_friends_intent(drink_preferences=["bar"])
        plan = {
            "plan_id": "test_drink_001",
            "activity": {
                "name": "LiveHouse", "distance_km": 3.0,
                "tags": ["音乐", "社交"], "scene": "friends",
                "avg_price": 150, "queue_minutes": 10, "recommended_duration_min": 120,
            },
            "restaurant": {
                "name": "火锅店", "distance_km": 3.0,
                "tags": ["聚会", "社交"], "scene": "friends",
                "rating": 4.5, "popularity_score": 85, "party_size_max": 6,
                "avg_price": 120, "queue_minutes": 15, "recommended_duration_min": 75,
            },
            "drink": {
                "name": "京A精酿啤酒", "distance_km": 3.0,
                "sub_category": "bar", "rating": 4.6,
                "popularity_score": 85, "avg_price": 85,
                "tags": ["聚会", "拍照"], "bookable": True,
            },
        }
        result = score_plan(plan, intent)
        assert result["score"] > 0.0, "含饮品方案评分不应为0"
        assert len(result["score_reasons"]) > 0, "应有评分理由"

    def test_drink_bar_matches_preference(self):
        intent = _make_friends_intent(drink_preferences=["bar"])
        plan = {
            "plan_id": "test_drink_002",
            "drink": {
                "name": "京A精酿啤酒", "distance_km": 2.0,
                "sub_category": "bar", "rating": 4.6,
                "popularity_score": 85, "avg_price": 85,
                "tags": ["聚会"], "bookable": True,
            },
            "activity": None,
            "restaurant": None,
        }
        result = score_plan(plan, intent)
        assert result["score"] > 0.0


class TestScorerPartyTypes:
    """更细同行人画像评分"""

    def test_family_elder_does_not_use_child_penalty(self):
        intent = Intent(
            scene="family",
            party_type="family_elder",
            needs_less_walking=True,
            needs_low_calorie=True,
            radius_km=5.0,
            avoid_queue_minutes=20,
            people_count=3,
        )
        plan = {
            "plan_id": "elder_001",
            "activity": {
                "name": "安静展览", "distance_km": 2.0,
                "child_friendly": False, "tags": ["艺术", "安静"],
                "queue_minutes": 5, "avg_price": 60, "recommended_duration_min": 90,
            },
            "restaurant": {
                "name": "清淡餐厅", "distance_km": 2.0,
                "low_calorie_options": True, "tags": ["健康", "高品质"],
                "available": True, "rating": 4.6,
                "queue_minutes": 5, "avg_price": 90, "recommended_duration_min": 70,
            },
        }
        result = score_plan(plan, intent)
        assert result["score"] > 0.6
        assert not any("儿童适配" in reason for reason in result["score_reasons"])

    def test_couple_prefers_ambience(self):
        intent = Intent(
            scene="friends",
            party_type="couple",
            needs_photo_spot=True,
            radius_km=8.0,
            avoid_queue_minutes=30,
            people_count=2,
        )
        plan = {
            "plan_id": "couple_001",
            "activity": {
                "name": "艺术展", "distance_km": 3.0,
                "tags": ["拍照", "艺术"], "rating": 4.6,
                "queue_minutes": 5, "avg_price": 120, "recommended_duration_min": 90,
            },
            "restaurant": {
                "name": "约会餐厅", "distance_km": 3.2,
                "tags": ["约会", "高品质", "出片"], "rating": 4.7,
                "popularity_score": 80, "party_size_max": 4,
                "queue_minutes": 5, "avg_price": 180, "recommended_duration_min": 75,
            },
        }
        result = score_plan(plan, intent)
        assert result["score"] > 0.6
        assert any("氛围" in reason or "约会" in reason for reason in result["score_reasons"])

    def test_business_prefers_quiet_stable(self):
        intent = Intent(
            scene="friends",
            party_type="business",
            needs_quiet=True,
            radius_km=8.0,
            avoid_queue_minutes=20,
            people_count=2,
        )
        plan = {
            "plan_id": "biz_001",
            "activity": None,
            "restaurant": {
                "name": "商务餐厅", "distance_km": 2.0,
                "tags": ["高品质", "包间"], "rating": 4.8,
                "popularity_score": 75, "available": True,
                "queue_minutes": 0, "avg_price": 220, "recommended_duration_min": 90,
            },
        }
        result = score_plan(plan, intent)
        assert result["score"] > 0.6
        assert any("安静" in reason or "稳定" in reason for reason in result["score_reasons"])

    def test_memory_tags_add_bonus_without_being_required(self):
        intent = Intent(
            scene="couple",
            party_type="couple",
            memory_tags=["日料", "健康"],
            radius_km=8.0,
            avoid_queue_minutes=30,
            people_count=2,
        )
        plan = {
            "plan_id": "memory_bonus_001",
            "activity": {
                "name": "香氛手作",
                "distance_km": 2.0,
                "tags": ["约会", "仪式感"],
                "rating": 4.7,
                "queue_minutes": 5,
                "avg_price": 180,
                "recommended_duration_min": 90,
            },
            "restaurant": {
                "name": "约会日料",
                "distance_km": 2.3,
                "category": "日料",
                "cuisine": "日料",
                "tags": ["约会", "纪念日"],
                "rating": 4.7,
                "popularity_score": 80,
                "party_size_max": 4,
                "queue_minutes": 5,
                "avg_price": 260,
                "recommended_duration_min": 75,
            },
        }

        result = score_plan(plan, intent)

        assert any("记忆偏好匹配" in reason for reason in result["score_reasons"])
