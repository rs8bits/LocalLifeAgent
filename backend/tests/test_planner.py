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
            message="下午出去玩",
        )
        # user_001 有 child_age=5, spouse_diet=减脂，应该生效
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
        assert len(logs) >= 3  # 至少: weather, activities, restaurants
        tool_names = {log["tool"] for log in logs}
        assert "get_weather" in tool_names
        assert "search_activities" in tool_names
        assert "search_restaurants" in tool_names

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
