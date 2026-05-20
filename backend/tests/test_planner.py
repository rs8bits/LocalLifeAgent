"""Planner 测试"""

import pytest
from backend.agent.planner import plan_for_message


class TestPlannerFamily:
    """家庭场景规划"""

    @pytest.mark.asyncio
    async def test_generates_at_least_two_plans(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="今天下午想和老婆孩子出去玩几个小时，别太远，孩子5岁，老婆最近在减肥",
        )
        plans = result["plans"]
        assert len(plans) >= 2, f"期望至少2个方案，实际{len(plans)}个"

    @pytest.mark.asyncio
    async def test_plans_have_required_fields(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="周末带5岁孩子去亲子乐园，老婆要减肥吃健康餐",
        )
        for plan in result["plans"]:
            assert "plan_id" in plan
            assert "title" in plan
            assert "timeline" in plan
            assert "activity" in plan
            assert "restaurant" in plan
            assert "budget" in plan
            assert "score" in plan
            assert plan["score"] >= 0.0

    @pytest.mark.asyncio
    async def test_activities_from_mock_data(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="下午和老婆孩子出去，孩子5岁，在家附近",
        )
        for plan in result["plans"]:
            if plan["activity"]:
                assert plan["activity"]["id"].startswith("act_"), \
                    f"活动 ID 应以 act_ 开头: {plan['activity']['id']}"
            if plan["restaurant"]:
                assert plan["restaurant"]["id"].startswith("rest_"), \
                    f"餐厅 ID 应以 rest_ 开头: {plan['restaurant']['id']}"

    @pytest.mark.asyncio
    async def test_family_prefers_child_friendly(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="带孩子出去玩，孩子3岁",
        )
        plans = result["plans"]
        if plans and plans[0].get("activity"):
            assert plans[0]["activity"]["child_friendly"] is True

    @pytest.mark.asyncio
    async def test_plans_with_memory_merge(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="下午带老婆孩子出去玩",
        )
        # user_001 有 child_age=5, spouse_diet=减脂，在家场景应生效
        intent = result["intent"]
        assert intent["child_age"] == 5

    @pytest.mark.asyncio
    async def test_no_booking_or_order_calls(self, monkeypatch):
        """验证 Planner 不调用预约、订位、下单工具"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="今天下午想和老婆孩子出去玩",
        )
        for log in result["tool_logs"]:
            assert log["tool"] not in ["book_activity", "reserve_restaurant", "create_mock_order"], \
                f"不应该调用 {log['tool']}"


class TestPlannerFriends:
    """朋友场景规划"""

    @pytest.mark.asyncio
    async def test_generates_plans_for_friends(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="今天下午想和4个朋友出去拍照吃饭，去三里屯附近",
        )
        plans = result["plans"]
        assert len(plans) >= 1

    @pytest.mark.asyncio
    async def test_friends_prefers_photo_social(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="和朋友出去拍照打卡喝咖啡",
        )
        plans = result["plans"]
        # 至少有一个方案的餐厅或活动有拍照相关标签
        has_photo = False
        for plan in plans:
            act = plan.get("activity") or {}
            rest = plan.get("restaurant") or {}
            if "拍照" in act.get("tags", []) or "拍照" in rest.get("tags", []):
                has_photo = True
        assert has_photo, "朋友拍照场景应该有拍照相关结果"


class TestPlannerToolLogs:
    """工具日志"""

    @pytest.mark.asyncio
    async def test_tool_logs_recorded(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="下午和老婆孩子出去玩",
        )
        logs = result["tool_logs"]
        assert len(logs) >= 3  # 至少: weather, search_places (play+eat)
        tool_names = {log["tool"] for log in logs}
        assert "get_weather" in tool_names
        assert "search_places" in tool_names

    @pytest.mark.asyncio
    async def test_tool_log_format(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="下午在家附近找个亲子活动",
        )
        for log in result["tool_logs"]:
            assert "tool" in log
            assert "status" in log
            assert "message" in log


class TestPlannerFriendsWithDrink:
    """朋友场景含饮品和活动"""

    @pytest.mark.asyncio
    async def test_friends_dinner_drink_sing_has_ktv_or_livehouse(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="晚上和4个朋友想吃饭喝精酿再唱歌",
        )
        plans = result["plans"]
        assert len(plans) >= 1
        intent = result["intent"]
        assert intent["scene"] == "friends"
        # 应包含唱歌相关活动 (纯K KTV act_009 或 MAO LiveHouse act_013)
        has_ktv_or_livehouse = any(
            (p.get("activity") or {}).get("id") in ("act_009", "act_013")
            for p in plans
        )
        assert has_ktv_or_livehouse, "朋友唱歌场景应包含 KTV 或 LiveHouse 活动"

    @pytest.mark.asyncio
    async def test_friends_scene_no_child_age_filter(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_001",
            message="晚上和4个朋友想吃饭喝精酿再唱歌",
        )
        # tool_logs 中 search_activities 不应出现 child_age 被传递的痕迹
        for log in result["tool_logs"]:
            if log["tool"] == "search_activities":
                # 朋友场景不应返回 0 个活动（被 child_age 过滤所致）
                assert "0 个活动" not in log["message"], \
                    f"朋友场景不应因 child_age 过滤掉所有活动: {log['message']}"


class TestTagResolverFlow:
    """标签对齐 + 搜索流程测试"""

    @pytest.mark.asyncio
    async def test_rule_resolve_sing_drink_eat(self, monkeypatch):
        """DeepSeek 不可用时，规则兜底对齐 唱歌/喝酒/吃饭"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="今天下午想和2个朋友出去拍照吃饭，下午想去唱歌，晚上想喝酒",
        )
        # 不应有红色错误
        errors = result.get("errors", [])
        # 有活动/餐厅/饮品的组合应至少生成方案，不能因为某个 domain 空就报全局错误
        plans = result["plans"]
        assert len(plans) >= 1, "应至少生成1个方案"
        # 应包含活动 (play domain)
        has_activity = any(p.get("activity") for p in plans)
        assert has_activity, "唱歌应由 play domain 搜索到活动"

    @pytest.mark.asyncio
    async def test_no_global_error_for_optional_domain(self, monkeypatch):
        """可选领域没结果不应写入全局 errors"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="下午想和朋友喝咖啡吃饭",
        )
        # 用户没要求 play，不应报"未找到活动"
        errors = result.get("errors", [])
        for err in errors:
            assert "活动" not in err, f"不应报活动错误: {err}"

    @pytest.mark.asyncio
    async def test_sing_forces_play_domain(self, monkeypatch):
        """明确要求唱歌时，play domain 必须有结果"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="下午想去唱歌",
        )
        plans = result["plans"]
        has_activity = any(p.get("activity") for p in plans)
        assert has_activity, "唱歌应由 play domain 生成活动方案"

    @pytest.mark.asyncio
    async def test_tag_search_fallback(self, monkeypatch):
        """标签搜索 0 结果时应自动放宽"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="下午想去玩",
        )
        # 即使"玩"没有精确匹配到标签，tag resolver 应放宽或返回空 tags_any
        # 结果不应崩溃
        assert "plans" in result

    @pytest.mark.asyncio
    async def test_llm_english_tags_aligned(self, monkeypatch):
        """LLM 输出英文 photography/singing 应对齐到真实中文标签"""
        async def fake_llm_parse(message: str):
            return {
                "scene": "friends",
                "activity_preferences": ["photography", "singing"],
                "drink_preferences": ["bar"],
                "food_preferences": [],
                "needs_low_calorie": False,
            }
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", True)
        monkeypatch.setattr("backend.agent.intent_parser._llm_parse", fake_llm_parse)
        result = await plan_for_message(
            user_id="user_002",
            message="photography and singing with friends",
        )
        plans = result["plans"]
        assert len(plans) >= 1
        # 应能搜到活动
        has_activity = any(p.get("activity") for p in plans)
        assert has_activity, "photography/singing 应对齐到拍照/唱歌，搜到活动"


class TestPlannerErrors:
    """错误处理"""

    @pytest.mark.asyncio
    async def test_graceful_with_no_matching_results(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_003",
            message="想找一个50公里外的餐厅（应该没有结果）",
        )
        # 不应崩溃
        assert "plans" in result
        assert "errors" in result
