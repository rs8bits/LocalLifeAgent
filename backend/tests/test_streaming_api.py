"""流式 API 测试"""

import json
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
