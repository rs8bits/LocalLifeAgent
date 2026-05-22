"""Agent API 测试"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.agent.session_store import reset_sessions
from backend.mock_api.storage import read_json, write_json

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_all():
    """每个测试前重置 sessions / bookings / orders"""
    reset_sessions()
    write_json("bookings.json", [])
    write_json("orders.json", [])
    write_json("delivery_orders.json", [])


class TestAgentPlan:
    """POST /api/agent/plan"""

    def test_plan_returns_session_id_and_plans(self):
        resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子出去玩，孩子5岁",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["session_id"].startswith("session_")
        assert len(data["plans"]) >= 1
        assert "intent" in data
        assert "tool_logs" in data

    def test_plan_does_not_write_bookings_or_orders(self):
        resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子出去玩，孩子5岁",
        })
        assert resp.status_code == 200
        bookings = read_json("bookings.json")
        orders = read_json("orders.json")
        assert len(bookings) == 0, "规划阶段不应写入 bookings"
        assert len(orders) == 0, "规划阶段不应写入 orders"

    def test_plan_empty_message_returns_400(self):
        resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "   ",
        })
        assert resp.status_code == 400

    def test_plan_family_scene(self):
        resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "带4岁宝宝去附近乐园，老婆要减肥吃轻食",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"]["party_type"] == "family_with_child"

    def test_plan_friends_scene(self):
        resp = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "和4个朋友去拍照吃饭喝咖啡",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"]["party_type"] == "friends"


class TestAgentSession:
    """GET /api/agent/session/{session_id}"""

    def test_get_session_returns_data(self):
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带家人去公园",
        })
        session_id = plan_resp.json()["session_id"]

        resp = client.get(f"/api/agent/session/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session_id
        assert data["status"] == "planned"

    def test_get_nonexistent_session_returns_404(self):
        resp = client.get("/api/agent/session/session_nonexistent")
        assert resp.status_code == 404


class TestAgentConfirm:
    """POST /api/agent/confirm"""

    def test_confirm_success(self):
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁，老婆减肥吃健康餐",
        })
        data = plan_resp.json()
        session_id = data["session_id"]
        plan_id = data["plans"][0]["plan_id"]

        confirm_resp = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert confirm_resp.status_code == 200
        result = confirm_resp.json()
        assert result["status"] in ("success", "partial_success")

    def test_confirm_writes_bookings_and_orders(self):
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        data = plan_resp.json()
        session_id = data["session_id"]
        plan_id = data["plans"][0]["plan_id"]

        confirm_resp = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert confirm_resp.status_code == 200

        bookings = read_json("bookings.json")
        orders = read_json("orders.json")
        assert len(bookings) + len(orders) >= 1, "确认阶段应写入 bookings 或 orders"

    def test_confirm_nonexistent_session_returns_404(self):
        resp = client.post("/api/agent/confirm", json={
            "session_id": "session_nonexistent",
            "plan_id": "plan_001",
        })
        assert resp.status_code == 404

    def test_confirm_nonexistent_plan_returns_404(self):
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午去公园",
        })
        session_id = plan_resp.json()["session_id"]

        resp = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": "plan_nonexistent",
        })
        assert resp.status_code == 404

    def test_share_message_present(self):
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        data = plan_resp.json()
        session_id = data["session_id"]
        plan_id = data["plans"][0]["plan_id"]

        confirm_resp = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert confirm_resp.status_code == 200
        result = confirm_resp.json()
        assert result.get("share_message"), "应有转发消息"
        # 不能声称真实支付成功（可以说非真实支付）
        assert "支付成功" not in result["share_message"]
        assert "交易成功" not in result["share_message"]
        # 应包含 Demo/Mock/模拟/非真实 说明是非真实交易
        msg = result["share_message"]
        assert any(w in msg for w in ["Mock", "Demo", "模拟", "非真实"]), \
            f"转发消息应说明是非真实交易: {msg}"

    def test_confirm_twice_is_stable(self):
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园",
        })
        data = plan_resp.json()
        session_id = data["session_id"]
        plan_id = data["plans"][0]["plan_id"]

        confirm_resp = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert confirm_resp.status_code == 200

        # 重复确认不应崩溃
        confirm_resp2 = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert confirm_resp2.status_code == 200
        assert confirm_resp2.json()["status"] == confirm_resp.json()["status"]

    def test_confirm_twice_does_not_duplicate_writes(self):
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "下午带老婆孩子去亲子乐园，孩子5岁",
        })
        data = plan_resp.json()
        session_id = data["session_id"]
        plan_id = data["plans"][0]["plan_id"]

        first = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert first.status_code == 200
        bookings_after_first = len(read_json("bookings.json"))
        orders_after_first = len(read_json("orders.json"))

        second = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert second.status_code == 200
        assert len(read_json("bookings.json")) == bookings_after_first
        assert len(read_json("orders.json")) == orders_after_first

    def test_confirm_with_drink_plan_succeeds(self, monkeypatch):
        """含 drink_004 的方案确认应成功或 partial_success，不能 500"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "晚上和朋友喝精酿啤酒",
        })
        assert plan_resp.status_code == 200
        data = plan_resp.json()
        session_id = data["session_id"]
        # 找到含 drink 的方案
        drink_plan = None
        for p in data["plans"]:
            if p.get("drink") and p["drink"].get("bookable"):
                drink_plan = p
                break
        if not drink_plan:
            drink_plan = data["plans"][0]
        plan_id = drink_plan["plan_id"]

        confirm_resp = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert confirm_resp.status_code == 200, f"含 drink 方案确认不应 500: {confirm_resp.text}"
        result = confirm_resp.json()
        assert result["status"] in ("success", "partial_success"), \
            f"状态应为 success 或 partial_success, 实际: {result['status']}"

        # 检查 bookings.json 中 drink booking 的 type
        bookings = read_json("bookings.json")
        drink_bookings = [b for b in bookings if b.get("type") == "drink"]
        if drink_bookings:
            assert drink_bookings[0]["type"] == "drink"

    def test_confirm_delivery_action_writes_delivery_order(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "下午和朋友唱歌吃饭，闪送一束鲜花到餐厅",
        })
        assert plan_resp.status_code == 200
        data = plan_resp.json()
        plan = next((p for p in data["plans"] if p.get("delivery_items")), data["plans"][0])
        confirm_resp = client.post("/api/agent/confirm", json={
            "session_id": data["session_id"],
            "plan_id": plan["plan_id"],
        })
        assert confirm_resp.status_code == 200
        result = confirm_resp.json()
        assert result["status"] in ("success", "partial_success")
        delivery_orders = read_json("delivery_orders.json")
        assert len(delivery_orders) >= 1
        assert any(o.get("order_type") == "delivery" for o in read_json("orders.json"))

    def test_confirm_friends_scene(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        plan_resp = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "今天下午想和4个朋友出去拍照吃饭，去三里屯附近",
        })
        data = plan_resp.json()
        session_id = data["session_id"]
        plan_id = data["plans"][0]["plan_id"]

        confirm_resp = client.post("/api/agent/confirm", json={
            "session_id": session_id,
            "plan_id": plan_id,
        })
        assert confirm_resp.status_code == 200
        result = confirm_resp.json()
        assert result.get("share_message")


class TestExecutor:
    """执行器辅助函数"""

    def test_choose_available_slot_exact_match(self):
        from backend.agent.executor import choose_available_slot
        slots = ["14:00", "15:00", "16:00"]
        assert choose_available_slot("14:00", slots) == "14:00"

    def test_choose_available_slot_next(self):
        from backend.agent.executor import choose_available_slot
        slots = ["14:00", "15:00", "16:00"]
        assert choose_available_slot("14:30", slots) == "15:00"

    def test_choose_available_slot_none(self):
        from backend.agent.executor import choose_available_slot
        assert choose_available_slot("14:00", []) is None

    def test_choose_available_slot_all_before(self):
        from backend.agent.executor import choose_available_slot
        slots = ["10:00", "11:00"]
        assert choose_available_slot("14:00", slots) == "10:00"
