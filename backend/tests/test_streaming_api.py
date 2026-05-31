"""流式 API 测试"""

import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.agent.session_store import reset_sessions
from backend.mock_api.storage import write_json

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_all():
    reset_sessions()
    write_json("bookings.json", [])
    write_json("orders.json", [])


class TestPlanStreaming:
    """流式规划 API"""

    def test_plan_stream_returns_sse(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        body = resp.text
        assert "intent_start" in body or "intent_done" in body
        assert "tool_done" in body or "planner_start" in body

    def test_plan_stream_includes_reflection(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        assert resp.status_code == 200
        assert "reflection_start" in resp.text or "reflection_done" in resp.text

    def test_plan_stream_includes_guardrails(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        assert resp.status_code == 200
        assert "guardrails_done" in resp.text

    def test_plan_stream_has_plan_done(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        assert resp.status_code == 200
        assert "plan_done" in resp.text

    def test_plan_stream_empty_message(self):
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_001",
            "message": "   ",
        })
        assert resp.status_code == 400

    def test_plan_stream_includes_tag_events(self, monkeypatch):
        """新流程 SSE 应包含标签对齐和场所搜索事件"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_002",
            "message": "下午想去唱歌拍照，晚上喝酒",
        })
        assert resp.status_code == 200
        body = resp.text
        assert "tag_catalog_done" in body, "SSE 应包含 tag_catalog_done 事件"
        assert "place_search_start" in body, "SSE 应包含 place_search_start 事件"
        assert "plan_done" in body


class TestConfirmStreaming:
    """流式确认 API"""

    def test_confirm_stream_works(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        # 先规划
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        data = plan_resp.json()
        session_id = data["session_id"]
        plan_id = data["plans"][0]["plan_id"]

        # 流式确认
        resp = client.post("/api/agent/confirm/stream", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert resp.status_code == 200
        assert "confirm_start" in resp.text or "confirm_done" in resp.text

    def test_confirm_stream_nonexistent_session(self):
        resp = client.post("/api/agent/confirm/stream", json={
            "session_id": "session_nonexistent",
            "plan_id": "plan_001",
        })
        assert resp.status_code == 404


class TestExistingAPIsUnaffected:
    """确保现有 API 不受影响"""

    def test_plan_still_works(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert len(data["plans"]) >= 1

    def test_confirm_still_works(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        data = plan_resp.json()
        conf_resp = client.post("/api/agent/confirm", json={
            "session_id": data["session_id"],
            "plan_id": data["plans"][0]["plan_id"],
        })
        assert conf_resp.status_code == 200
        assert conf_resp.json()["status"] in ("success", "partial_success")

    def test_session_still_works(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        sid = plan_resp.json()["session_id"]
        resp = client.get(f"/api/agent/session/{sid}")
        assert resp.status_code == 200


class TestRealStreamingOrder:
    """P1: 验证真正的流式输出顺序"""

    def test_memory_loaded_before_plan_done(self, monkeypatch):
        """memory_loaded 应在 plan_done 之前到达"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        assert resp.status_code == 200
        body = resp.text
        mem_pos = body.find("memory_loaded")
        plan_done_pos = body.find("plan_done")
        assert mem_pos >= 0, "应包含 memory_loaded 事件"
        assert plan_done_pos >= 0, "应包含 plan_done 事件"
        assert mem_pos < plan_done_pos, \
            f"memory_loaded 应在 plan_done 之前 (mem={mem_pos}, done={plan_done_pos})"

    def test_node_level_events_in_order(self, monkeypatch):
        """验证节点级事件的出现顺序"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        assert resp.status_code == 200
        body = resp.text
        # 关键事件顺序检查
        expected_order = [
            "memory_loaded",
            "intent_start",
            "intent_done",
            "planner_start",
            "tag_resolve_start",
            "tag_resolve_done",
            "place_search_start",
            "place_search_done",
            "composer_start",
            "composer_done",
            "reflection_start",
            "reflection_done",
            "guardrails_start",
            "guardrails_done",
            "plan_done",
        ]
        positions = {}
        for evt in expected_order:
            pos = body.find(evt)
            if pos >= 0:
                positions[evt] = pos

        # 验证已出现的事件按顺序排列
        found_events = [e for e in expected_order if e in positions]
        for i in range(len(found_events) - 1):
            assert positions[found_events[i]] < positions[found_events[i + 1]], \
                f"{found_events[i]} 应在 {found_events[i + 1]} 之前"

    def test_light_lunch_streaming_no_play_drink(self, monkeypatch):
        """流式接口「中午想吃点清淡的」不应出现 play/drink/delivery"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_002",
            "message": "中午想吃点清淡的",
        })
        assert resp.status_code == 200
        body = resp.text
        assert "plan_done" in body
        # 不应出现无关领域搜索
        assert "(play)" not in body, f"不应搜索 play: {body[:500]}"
        assert "(drink)" not in body, f"不应搜索 drink: {body[:500]}"
        assert "search_delivery_items" not in body, f"不应搜索 delivery: {body[:500]}"
        assert "(eat)" in body, "应搜索 eat 领域"

    def test_parent_city_visit_streaming_has_full_itinerary(self, monkeypatch):
        """流式接口的长辈来访场景不能退化成空方案或纯吃饭。"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        resp = client.post("/api/agent/plan/stream", json={
            "user_id": "user_001",
            "message": "明天爸妈来我的城市，我想带他们逛逛，帮我安排一下",
        })
        assert resp.status_code == 200
        plan_done = None
        for chunk in resp.text.split("\n\n"):
            if chunk.startswith("event: plan_done"):
                data_line = next(line for line in chunk.splitlines() if line.startswith("data: "))
                plan_done = json.loads(data_line[6:])
                break
        assert plan_done is not None
        result = plan_done["data"]["result"]
        assert result["errors"] == []
        assert result["plans"], result["tool_logs"]
        first = result["plans"][0]
        assert first.get("activity"), "应包含活动"
        assert first.get("restaurant"), "应包含餐厅"
        assert first.get("drink"), "应包含茶饮/咖啡休息点"

    @pytest.mark.asyncio
    async def test_planner_internal_events_emit_before_slow_composer(self, monkeypatch):
        """planner_node 内部事件应在慢 LLM 组合完成前就被推送"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        async def slow_compose_plan_specs_with_llm(**kwargs):
            await asyncio.sleep(0.5)
            return [], None

        monkeypatch.setattr(
            "backend.agent.nodes.planner_node.compose_plan_specs_with_llm",
            slow_compose_plan_specs_with_llm,
        )

        from backend.agent.graph import run_planning_graph_stream

        seen_events = []
        started = time.perf_counter()
        gen = run_planning_graph_stream(
            user_id="user_002",
            message="中午想吃点清淡的",
        )
        try:
            async for chunk in gen:
                for line in chunk.splitlines():
                    if line.startswith("data: "):
                        seen_events.append(json.loads(line[6:])["event"])
                if "composer_start" in seen_events:
                    break
        finally:
            await gen.aclose()

        elapsed = time.perf_counter() - started
        assert "composer_start" in seen_events
        assert elapsed < 0.4, f"composer_start 没有实时吐出，耗时 {elapsed:.3f}s"
