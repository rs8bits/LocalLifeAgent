"""意图解析器测试"""

import pytest
from backend.agent.intent_parser import parse_intent, _rule_parse


class TestRuleParseFamily:
    """家庭场景规则解析"""

    def test_family_basic(self):
        msg = "今天下午想和老婆孩子出去玩几个小时，别太远，孩子5岁，老婆最近在减肥"
        intent = _rule_parse(msg)
        assert intent.scene == "family"
        assert intent.child_age == 5
        assert intent.needs_low_calorie is True
        assert intent.radius_km == 5.0
        assert intent.people_count >= 3

    def test_family_with_distance(self):
        msg = "周末带4岁宝宝去附近公园，不要太远"
        intent = _rule_parse(msg)
        assert intent.scene == "family"
        assert intent.child_age == 4
        assert "亲子" in intent.activity_preferences

    def test_family_no_child_age(self):
        msg = "下午和老婆出去逛逛"
        intent = _rule_parse(msg)
        assert intent.scene == "family"
        assert intent.child_age is None
        assert intent.people_count == 2


class TestRuleParseFriends:
    """朋友场景规则解析"""

    def test_friends_basic(self):
        msg = "今天下午想和4个朋友出去拍照吃饭，别太远"
        intent = _rule_parse(msg)
        assert intent.scene == "friends"
        assert intent.needs_photo_spot is True
        assert intent.people_count >= 4
        assert "拍照" in intent.activity_preferences

    def test_friends_boardgame(self):
        msg = "周末和3个同学去玩桌游，然后吃火锅"
        intent = _rule_parse(msg)
        assert intent.scene == "friends"
        assert intent.people_count == 3

    def test_friends_no_count(self):
        msg = "下午和朋友喝咖啡"
        intent = _rule_parse(msg)
        assert intent.scene == "friends"
        # 朋友场景未指明人数时默认为 None


class TestRuleParseGeneral:
    """通用场景"""

    def test_general(self):
        msg = "下午想出去走走"
        intent = _rule_parse(msg)
        assert intent.scene == "general"

    def test_date_tomorrow(self):
        msg = "明天下午去公园"
        intent = _rule_parse(msg)
        assert intent.date == "tomorrow"

    def test_duration(self):
        msg = "想玩3个小时"
        intent = _rule_parse(msg)
        assert intent.duration_hours == 3

    def test_budget(self):
        msg = "人均100以内"
        intent = _rule_parse(msg)
        assert intent.budget_per_person == 100

    def test_no_queue(self):
        msg = "不想排队的地方"
        intent = _rule_parse(msg)
        assert intent.avoid_queue_minutes <= 10


class TestIntentWithoutAPIKey:
    """无 DeepSeek API Key 时使用规则兜底"""

    @pytest.mark.asyncio
    async def test_rule_fallback_works(self, monkeypatch):
        """模拟没有 API Key 的情况"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        intent = await parse_intent("今天下午想和老婆孩子出去玩，孩子5岁")
        assert intent.scene == "family"
        assert intent.child_age == 5


class TestIntentPreferenceNormalization:
    """LLM 自然语言偏好归一化"""

    @pytest.mark.asyncio
    async def test_llm_natural_preferences_map_to_mock_tags(self, monkeypatch):
        async def fake_llm_parse(message: str):
            return {
                "scene": "family",
                "food_preferences": ["清淡"],
                "activity_preferences": ["室内活动", "适合小孩"],
                "needs_low_calorie": True,
            }

        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", True)
        monkeypatch.setattr("backend.agent.intent_parser._llm_parse", fake_llm_parse)

        intent = await parse_intent("我们三口想找个室内活动，吃清淡点")

        assert intent.food_preferences == ["健康"]
        assert intent.activity_preferences == ["室内", "亲子"]
        assert intent.needs_low_calorie is True


class TestUserMemoryMerge:
    """用户记忆合并"""

    @pytest.mark.asyncio
    async def test_memory_as_default(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        memory = {
            "user_id": "user_001",
            "preferences": {
                "child_age": 5,
                "max_distance_km": 8,
                "max_queue_minutes": 20,
                "spouse_diet": "减脂",
                "cuisine_likes": ["日料"],
            },
        }
        intent = await parse_intent("下午带老婆孩子出去玩", user_memory=memory)
        assert intent.child_age == 5
        assert intent.radius_km == 8.0
        assert intent.avoid_queue_minutes == 20
        assert intent.needs_low_calorie is True

    @pytest.mark.asyncio
    async def test_user_input_overrides_memory(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        memory = {
            "user_id": "user_001",
            "preferences": {"child_age": 5, "max_distance_km": 8},
        }
        intent = await parse_intent("孩子3岁，去3公里内的活动", user_memory=memory)
        assert intent.child_age == 3
        assert intent.radius_km == 3.0


class TestFriendsMemoryIsolation:
    """朋友场景不应被家庭记忆污染"""

    @pytest.mark.asyncio
    async def test_friends_scene_ignores_child_age_from_memory(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        memory = {
            "user_id": "user_001",
            "preferences": {
                "child_age": 5,
                "child_name": "小宝",
                "spouse_diet": "减脂",
                "max_distance_km": 8,
                "max_queue_minutes": 30,
                "cuisine_likes": ["日料"],
            },
        }
        intent = await parse_intent("晚上和4个朋友想吃饭喝精酿再唱歌", user_memory=memory)
        assert intent.scene == "friends"
        assert intent.child_age is None, "朋友场景不应继承 child_age"
        assert intent.needs_low_calorie is False, "朋友场景不应继承配偶减脂偏好"
        # companions 不应包含 child/spouse
        roles = [c.get("role") for c in intent.companions]
        assert "child" not in roles, "朋友场景 companions 不应包含 child"
        assert "spouse" not in roles, "朋友场景 companions 不应包含 spouse"
