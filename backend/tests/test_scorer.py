"""评分器测试"""

from backend.agent.schemas import Intent
from backend.agent.scorer import score_plan


def _make_family_intent(**overrides) -> Intent:
    defaults = {
        "scene": "family",
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
