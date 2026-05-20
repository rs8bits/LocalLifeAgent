"""LangGraph 编排测试"""

import pytest
from backend.agent.graph import run_planning_graph, run_execution_graph


class TestPlanningGraph:
    """规划 Graph 测试"""

    @pytest.mark.asyncio
    async def test_graph_returns_plans(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await run_planning_graph(
            user_id="user_001",
            message="下午带老婆孩子去亲子乐园，孩子5岁",
        )
        assert len(result.get("plans", [])) >= 1
        assert "intent" in result
        assert result["intent"].get("scene") == "family"

    @pytest.mark.asyncio
    async def test_graph_includes_all_node_results(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await run_planning_graph(
            user_id="user_001",
            message="下午带老婆孩子去亲子乐园，孩子5岁",
        )
        # 各节点结果应存在
        assert "intent" in result
        assert "user_profile" in result
        assert "plans" in result
        assert "tool_logs" in result
        assert "reflection_result" in result
        assert "guardrail_result" in result

    @pytest.mark.asyncio
    async def test_graph_applies_user_memory_defaults(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await run_planning_graph(
            user_id="user_001",
            message="下午带老婆孩子出去玩",
        )
        assert result["intent"].get("child_age") == 5
        assert result["intent"].get("needs_low_calorie") is True

    @pytest.mark.asyncio
    async def test_graph_plans_have_scores(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await run_planning_graph(
            user_id="user_001",
            message="下午带老婆孩子去亲子乐园，孩子5岁",
        )
        for plan in result.get("plans", []):
            assert "score" in plan
            assert 0.0 <= plan["score"] <= 1.0

    @pytest.mark.asyncio
    async def test_graph_friends_scene(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await run_planning_graph(
            user_id="user_002",
            message="和朋友们去拍照喝咖啡",
        )
        assert result["intent"].get("scene") == "friends"


class TestExecutionGraph:
    """执行 Graph 测试"""

    @pytest.mark.asyncio
    async def test_exec_graph_runs(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        from backend.mock_api.storage import write_json
        write_json("bookings.json", [])
        write_json("orders.json", [])

        planning = await run_planning_graph(
            user_id="user_001",
            message="下午带老婆孩子去亲子乐园，孩子5岁",
        )
        plans = planning.get("plans", [])
        assert len(plans) > 0

        exec_result = await run_execution_graph(planning, plans[0]["plan_id"])
        assert "execution_result" in exec_result
        er = exec_result["execution_result"]
        assert er is not None
        assert er.get("status") in ("success", "partial_success", "failed")
        assert "share_message" in exec_result

        write_json("bookings.json", [])
        write_json("orders.json", [])
