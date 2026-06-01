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


class TestAgentRevise:
    """POST /api/agent/revise"""

    def test_revise_updates_intent_and_stores_parent_context(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "明天朋友早上到，帮我安排一下带他们逛逛",
        })
        assert first.status_code == 200
        first_data = first.json()

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "message": "我明天不带小孩，晚上想喝酒",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert data["session_id"] != first_data["session_id"]
        assert data["intent"]["party_type"] == "friends"
        assert data["intent"].get("child_age") is None
        assert "亲子" not in data["intent"].get("tags", [])
        assert "bar" in data["intent"].get("drink_preferences", [])
        assert any(
            "domain=drink" in log["message"] and ("bar" in log["message"] or "精酿" in log["message"])
            for log in data["tool_logs"]
            if log["tool"] == "search_places"
        )

        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        assert session["parent_session_id"] == first_data["session_id"]
        assert session["previous_intent"]
        assert session["tag_resolve_result"]
        assert session["revision_patch"]

    def test_revise_adds_meals_without_replacing_locked_activity(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "明天和朋友下午玩桌游",
        })
        assert first.status_code == 200
        first_data = first.json()
        base_plan = first_data["plans"][0]
        assert base_plan["activity"]["id"] == "act_006"

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "base_plan_id": base_plan["plan_id"],
            "message": "中饭晚饭都要吃",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert data["intent"]["meal_slots"] == ["lunch", "dinner"]
        assert data["plans"]
        assert data["plans"][0]["activity"]["id"] == "act_006"
        meals = data["plans"][0].get("meal_restaurants") or []
        assert [meal["meal"] for meal in meals] == ["lunch", "dinner"]

        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert "activity" in patch["keep_slots"]
        assert patch["locked_slots"]["activity"]["item"]["id"] == "act_006"

    def test_revise_adds_lunch_and_preserves_existing_dinner(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "明天爸妈来我的城市，我想带他们逛逛，帮我安排一下",
        })
        assert first.status_code == 200
        first_data = first.json()
        base_plan = first_data["plans"][0]
        base_activity_id = base_plan["activity"]["id"]
        base_dinner_id = base_plan["restaurant"]["id"]

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "message": "第一个方案安排一下中饭",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert data["intent"]["meal_slots"] == ["lunch", "dinner"]
        first_revised = data["plans"][0]
        assert first_revised["activity"]["id"] == base_activity_id
        meals = first_revised.get("meal_restaurants") or []
        assert [meal["meal"] for meal in meals] == ["lunch", "dinner"]
        assert meals[1]["restaurant"]["id"] == base_dinner_id

        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert patch["base_plan_id"] == base_plan["plan_id"]
        assert "meal:lunch" in patch["add_slots"]
        assert patch["locked_slots"]["meal:dinner"]["item"]["id"] == base_dinner_id
        assert patch["locked_slots"]["activity"]["item"]["id"] == base_activity_id

    def test_revise_adds_milk_tea_delivery_and_updates_people_count(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "明天爸妈来我的城市，我想带他们逛逛，帮我安排一下",
        })
        assert first.status_code == 200
        first_data = first.json()
        base_plan = first_data["plans"][0]

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "base_plan_id": base_plan["plan_id"],
            "message": "下午逛的时候送两杯奶茶过去，我们有四个人",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert data["intent"]["people_count"] == 4
        assert "奶茶" in data["intent"]["delivery_preferences"]
        first_plan = data["plans"][0]
        assert first_plan["delivery_items"]
        delivery = first_plan["delivery_items"][0]
        assert delivery["id"] == "delivery_002"
        assert delivery["_delivery_target_area"] == "国贸商圈"
        assert delivery["_delivery_target_ref_id"] == base_plan["activity"]["id"]
        assert first_plan["actions"]
        assert any(
            action["type"] == "order_delivery"
            and action["ref_id"] == "delivery_002"
            and action["target_ref_id"] == base_plan["activity"]["id"]
            for action in first_plan["actions"]
        )
        assert any(action.get("quantity") == 4 for action in first_plan["actions"] if action["type"] == "book_activity")

        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert patch["intent_patch"]["people_count"] == 4
        assert patch["intent_patch"]["delivery_preferences"] == ["奶茶"]
        assert "delivery" in patch["add_slots"]

    def test_revise_negates_delivery_item_generically(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "今天下午和4个朋友去唱歌吃饭，再送奶茶到餐厅",
        })
        assert first.status_code == 200
        first_data = first.json()
        base_plan = next(plan for plan in first_data["plans"] if plan.get("delivery_items"))

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "base_plan_id": base_plan["plan_id"],
            "message": "不要奶茶了，其他不变",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert "奶茶" not in data["intent"].get("delivery_preferences", [])
        assert all(not plan.get("delivery_items") for plan in data["plans"])
        assert all(
            action["type"] != "order_delivery"
            for plan in data["plans"]
            for action in plan.get("actions", [])
        )

        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert "delivery" in patch["remove_slots"]
        assert patch["intent_patch"]["remove_delivery_preferences"] == ["奶茶"]

    def test_revise_replaces_delivery_item_generically(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "今天下午和4个朋友去唱歌吃饭，再送奶茶到餐厅",
        })
        assert first.status_code == 200
        first_data = first.json()
        base_plan = next(plan for plan in first_data["plans"] if plan.get("delivery_items"))

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "base_plan_id": base_plan["plan_id"],
            "message": "不要奶茶了，换成生日蛋糕，其他不变",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert "奶茶" not in data["intent"].get("delivery_preferences", [])
        assert "蛋糕" in data["intent"].get("delivery_preferences", [])
        first_plan = next(plan for plan in data["plans"] if plan.get("delivery_items"))
        assert first_plan["delivery_items"][0]["id"] == "delivery_003"

        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert "delivery" in patch["add_slots"]
        assert "delivery" not in patch["remove_slots"]
        assert patch["intent_patch"]["remove_delivery_preferences"] == ["奶茶"]
        assert patch["intent_patch"]["delivery_preferences"] == ["蛋糕"]

    def test_revise_spouse_join_does_not_add_flower_delivery(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "明天两个朋友来，我要和他们叙叙旧，帮我安排一下",
        })
        assert first.status_code == 200
        first_data = first.json()
        ktv_plan = next(
            plan for plan in first_data["plans"]
            if plan.get("activity", {}).get("id") == "act_009"
        )

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "base_plan_id": ktv_plan["plan_id"],
            "message": "我老婆也去，四个人",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert data["intent"]["party_type"] == "friends"
        assert data["intent"]["people_count"] == 4
        assert "约会" not in data["intent"].get("tags", [])
        assert "鲜花" not in data["intent"].get("delivery_preferences", [])
        assert all(not plan.get("delivery_items") for plan in data["plans"])
        assert not any(log["tool"] == "search_delivery_items" for log in data["tool_logs"])

    def test_revise_negates_flower_and_recovers_parent_boardgame_plan(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "明天两个朋友来，我要和他们叙叙旧，帮我安排一下",
        })
        assert first.status_code == 200
        first_data = first.json()
        boardgame_plan = next(
            plan for plan in first_data["plans"]
            if plan.get("activity", {}).get("id") == "act_006"
        )
        ktv_plan = next(
            plan for plan in first_data["plans"]
            if plan.get("activity", {}).get("id") == "act_009"
        )

        spouse_revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "base_plan_id": ktv_plan["plan_id"],
            "message": "我老婆也去，四个人",
        })
        assert spouse_revised.status_code == 200
        spouse_data = spouse_revised.json()

        corrected = client.post("/api/agent/revise", json={
            "session_id": spouse_data["session_id"],
            "message": "不需要送花，只是带上我老婆一起玩，主要还是叙叙旧，你前面给的桌游和晚上喝酒方案挺好的",
        })
        assert corrected.status_code == 200
        data = corrected.json()

        assert data["intent"]["people_count"] == 4
        assert "bar" in data["intent"]["drink_preferences"]
        assert "鲜花" not in data["intent"].get("delivery_preferences", [])
        assert data["plans"][0]["activity"]["id"] == "act_006"
        assert all(not plan.get("delivery_items") for plan in data["plans"])
        assert all(
            action["type"] != "order_delivery"
            for plan in data["plans"]
            for action in plan.get("actions", [])
        )

        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert patch["base_plan_id"] == boardgame_plan["plan_id"]
        assert "delivery" in patch["remove_slots"]
        assert patch["locked_slots"]["activity"]["item"]["id"] == "act_006"

    def test_revise_can_reselect_activity_by_generic_preference(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "明天两个朋友来，我要和他们叙叙旧，帮我安排一下",
        })
        assert first.status_code == 200
        first_data = first.json()
        ktv_plan = next(
            plan for plan in first_data["plans"]
            if plan.get("activity", {}).get("id") == "act_009"
        )

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "message": "你前面给的KTV和餐厅方案挺好的，四个人",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert data["plans"][0]["activity"]["id"] == "act_009"
        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert patch["base_plan_id"] == ktv_plan["plan_id"]
        assert patch["locked_slots"]["activity"]["item"]["id"] == "act_009"

    def test_revise_only_replace_dinner_keeps_activity(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "明天和4个朋友中饭晚饭都要吃，中间玩桌游",
        })
        assert first.status_code == 200
        first_data = first.json()
        base_plan = first_data["plans"][0]
        assert base_plan["activity"]["id"] == "act_006"

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "base_plan_id": base_plan["plan_id"],
            "message": "只替换晚餐，其他不变",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert data["plans"][0]["activity"]["id"] == "act_006"
        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert "meal:dinner" in patch["replace_slots"]
        assert "activity" in patch["keep_slots"]

    def test_revise_generic_restaurant_replace_keeps_activity(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_002",
            "message": "今天下午和4个朋友去唱歌吃饭",
        })
        assert first.status_code == 200
        first_data = first.json()
        base_plan = first_data["plans"][0]
        base_activity_id = base_plan["activity"]["id"]
        base_restaurant_id = base_plan["restaurant"]["id"]

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "base_plan_id": base_plan["plan_id"],
            "message": "餐厅换一家，活动不要动",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert data["plans"][0]["activity"]["id"] == base_activity_id
        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert "meal:dinner" in patch["replace_slots"]
        assert "activity" in patch["keep_slots"]
        assert patch["locked_slots"]["activity"]["item"]["id"] == base_activity_id
        assert patch["locked_slots"].get("meal:dinner", {}).get("item", {}).get("id") != base_restaurant_id

    def test_revise_not_bringing_child_can_replace_child_activity(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)

        first = client.post("/api/agent/plan", json={
            "user_id": "user_001",
            "message": "明天带老婆孩子去亲子乐园，孩子5岁，帮我安排一下",
        })
        assert first.status_code == 200
        first_data = first.json()
        base_plan = first_data["plans"][0]
        assert base_plan["activity"]["child_friendly"] is True

        revised = client.post("/api/agent/revise", json={
            "session_id": first_data["session_id"],
            "base_plan_id": base_plan["plan_id"],
            "message": "这次不带小孩，换成展览，晚上想喝酒",
        })
        assert revised.status_code == 200
        data = revised.json()

        assert data["intent"]["child_age"] is None
        assert data["intent"]["party_type"] == "general"
        assert "亲子" not in data["intent"].get("tags", [])
        assert data["plans"][0]["activity"]["child_friendly"] is False
        assert data["plans"][0]["activity"]["id"] != base_plan["activity"]["id"]
        assert data["plans"][0]["drink"]["sub_category"] == "bar"

        session = client.get(f"/api/agent/session/{data['session_id']}").json()
        patch = session["revision_patch"]
        assert "activity" in patch["replace_slots"]
        assert not patch["locked_slots"]

    def test_revise_nonexistent_session_returns_404(self):
        resp = client.post("/api/agent/revise", json={
            "session_id": "session_missing",
            "message": "晚上想喝酒",
        })
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
