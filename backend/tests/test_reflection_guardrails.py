"""Reflection 与 Guardrails 测试"""

import pytest
from backend.agent.state import AgentState
from backend.agent.nodes.reflection_node import reflection_node
from backend.agent.nodes.guardrails_node import guardrails_node
from backend.llm.deepseek_client import LLMResult
from backend.mock_api.storage import read_json


def _make_state(**overrides):
    s: AgentState = {
        "session_id": "test_session",
        "user_id": "user_001",
        "user_message": "test",
        "intent": {
            "scene": "family",
            "child_age": 5,
            "radius_km": 5.0,
            "avoid_queue_minutes": 30,
            "needs_low_calorie": True,
        },
        "user_profile": {},
        "candidate_activities": [],
        "candidate_restaurants": [],
        "plans": [],
        "selected_plan_id": None,
        "tool_logs": [],
        "reflection_result": {},
        "guardrail_result": {},
        "execution_result": None,
        "share_message": None,
        "errors": [],
        "stream_events": [],
        "phase": "planning",
    }
    s.update(overrides)
    return s


class TestReflection:
    """Reflection 节点测试"""

    @pytest.mark.asyncio
    async def test_child_age_mismatch_detected(self):
        state = _make_state(
            intent={"scene": "family", "child_age": 3, "radius_km": 5.0, "avoid_queue_minutes": 30},
            plans=[{
                "plan_id": "p1",
                "title": "test",
                "activity": {
                    "name": "成人展览", "suitable_age_min": 12,
                    "suitable_age_max": 99, "child_friendly": False,
                    "distance_km": 3.0, "queue_minutes": 10,
                    "recommended_duration_min": 90, "avg_price": 100,
                    "bookable": True,
                },
                "restaurant": {
                    "name": "bar", "distance_km": 3.0,
                    "low_calorie_options": False, "tags": [],
                    "queue_minutes": 5, "recommended_duration_min": 60,
                    "avg_price": 80, "available": True,
                },
                "risk_tips": [],
            }],
        )
        result = await reflection_node(state)
        pr = result["reflection_result"]["plan_results"][0]
        assert not pr["passed"]
        assert any("儿童" in i or "适合" in i for i in pr["issues"])

    @pytest.mark.asyncio
    async def test_far_distance_detected(self):
        state = _make_state(
            intent={"scene": "family", "radius_km": 3.0, "avoid_queue_minutes": 30},
            plans=[{
                "plan_id": "p2",
                "title": "test",
                "activity": {
                    "name": "远郊乐园", "distance_km": 20.0,
                    "suitable_age_min": 2, "suitable_age_max": 12,
                    "child_friendly": True, "queue_minutes": 5,
                    "recommended_duration_min": 120, "avg_price": 80,
                    "bookable": True,
                },
                "restaurant": {
                    "name": "远郊餐厅", "distance_km": 20.0,
                    "low_calorie_options": False, "tags": [],
                    "queue_minutes": 5, "recommended_duration_min": 60,
                    "avg_price": 60, "available": True,
                },
                "risk_tips": [],
            }],
        )
        result = await reflection_node(state)
        pr = result["reflection_result"]["plan_results"][0]
        assert not pr["passed"]
        assert any("距离" in i for i in pr["issues"])

    @pytest.mark.asyncio
    async def test_long_queue_detected(self):
        state = _make_state(
            intent={"scene": "family", "radius_km": 10.0, "avoid_queue_minutes": 15},
            plans=[{
                "plan_id": "p3",
                "title": "test",
                "activity": {
                    "name": "热门乐园", "distance_km": 3.0,
                    "suitable_age_min": 2, "suitable_age_max": 12,
                    "child_friendly": True, "queue_minutes": 60,
                    "recommended_duration_min": 120, "avg_price": 100,
                    "bookable": True,
                },
                "restaurant": {
                    "name": "网红店", "distance_km": 3.0,
                    "low_calorie_options": False, "tags": [],
                    "queue_minutes": 50, "recommended_duration_min": 60,
                    "avg_price": 80, "available": True,
                },
                "risk_tips": [],
            }],
        )
        result = await reflection_node(state)
        pr = result["reflection_result"]["plan_results"][0]
        assert not pr["passed"]
        assert any("排队" in i for i in pr["issues"])

    @pytest.mark.asyncio
    async def test_low_calorie_missing_detected(self):
        state = _make_state(
            intent={"scene": "family", "needs_low_calorie": True, "radius_km": 5.0, "avoid_queue_minutes": 30},
            plans=[{
                "plan_id": "p4",
                "title": "test",
                "activity": {
                    "name": "公园", "distance_km": 2.0,
                    "suitable_age_min": 0, "suitable_age_max": 99,
                    "child_friendly": True, "queue_minutes": 0,
                    "recommended_duration_min": 60, "avg_price": 0,
                    "bookable": False,
                },
                "restaurant": {
                    "name": "火锅店", "distance_km": 2.0,
                    "low_calorie_options": False, "tags": ["火锅", "重口味"],
                    "queue_minutes": 10, "recommended_duration_min": 60,
                    "avg_price": 120, "available": True,
                },
                "risk_tips": [],
            }],
        )
        result = await reflection_node(state)
        pr = result["reflection_result"]["plan_results"][0]
        assert any("减脂" in i or "低卡" in i or "健康" in i for i in pr["issues"]), \
            f"应检测到减脂需求未满足, got issues={pr['issues']}"

    @pytest.mark.asyncio
    async def test_llm_reflection_merges_semantic_issue(self, monkeypatch):
        async def fake_chat_json(messages, temperature=0.1):
            return LLMResult(json_data={
                "plan_results": [{
                    "plan_id": "p_llm",
                    "passed": False,
                    "issues": ["用户明确想唱歌，但方案里的活动不是 KTV/唱歌类"],
                    "suggestions": ["换成 KTV 类活动"],
                }],
                "issues": [],
                "suggestions": [],
            })

        monkeypatch.setattr("backend.agent.reflection.deepseek_client.available", True)
        monkeypatch.setattr("backend.agent.reflection.deepseek_client.chat_json", fake_chat_json)
        state = _make_state(
            intent={"scene": "friends", "radius_km": 5.0, "avoid_queue_minutes": 30},
            tag_resolve_result={
                "domain_required": {"play": True},
                "domain_specs": [{
                    "domain": "play", "required": True,
                    "categories": ["KTV"], "tags": ["唱歌"], "sub_categories": [],
                }],
            },
            plans=[{
                "plan_id": "p_llm",
                "title": "test",
                "activity": {
                    "id": "act_003", "name": "展览", "category": "展览",
                    "tags": ["艺术"], "distance_km": 2.0,
                    "queue_minutes": 0, "recommended_duration_min": 120,
                    "bookable": True,
                },
                "restaurant": {},
                "route": None,
                "risk_tips": [],
            }],
        )
        result = await reflection_node(state)
        pr = result["reflection_result"]["plan_results"][0]
        assert pr["passed"] is False
        assert any("KTV" in issue or "唱歌" in issue for issue in pr["issues"])
        assert any("KTV" in tip or "唱歌" in tip for tip in result["plans"][0]["risk_tips"])


class TestGuardrails:
    """Guardrails 节点测试"""

    @pytest.mark.asyncio
    async def test_nonexistent_poi_blocked(self):
        state = _make_state(
            plans=[{
                "plan_id": "g1",
                "title": "test",
                "activity": {"id": "act_fake_999", "name": "假活动", "suitable_age_min": 2, "suitable_age_max": 99},
                "restaurant": {"id": "rest_fake_999", "name": "假餐厅"},
                "deals": [],
                "risk_tips": [],
            }],
        )
        result = await guardrails_node(state)
        assert result["guardrail_result"]["blocked"] is True
        assert len(result["guardrail_result"]["issues"]) >= 1

    @pytest.mark.asyncio
    async def test_valid_poi_passes(self):
        valid_act = read_json("activities.json")[0]
        valid_rest = read_json("restaurants.json")[0]
        state = _make_state(
            plans=[{
                "plan_id": "g2",
                "title": "test",
                "activity": {"id": valid_act["id"], "name": valid_act["name"],
                             "suitable_age_min": 2, "suitable_age_max": 12},
                "restaurant": {"id": valid_rest["id"], "name": valid_rest["name"]},
                "deals": [],
                "risk_tips": [],
            }],
        )
        result = await guardrails_node(state)
        assert result["guardrail_result"]["passed"] is True

    @pytest.mark.asyncio
    async def test_planning_phase_blocks_booking_id(self):
        state = _make_state(
            phase="planning",
            plans=[{
                "plan_id": "g3",
                "title": "test",
                "activity": {},
                "restaurant": {},
                "deals": [],
                "booking_id": "should_not_exist",
                "risk_tips": [],
            }],
        )
        result = await guardrails_node(state)
        assert result["guardrail_result"]["blocked"] is True

    @pytest.mark.asyncio
    async def test_share_message_forbidden_content(self):
        state = _make_state(
            share_message="已真实支付成功，订单确认完毕",
            plans=[{"plan_id": "g4", "activity": {}, "restaurant": {}, "deals": [], "risk_tips": []}],
        )
        result = await guardrails_node(state)
        assert result["guardrail_result"]["blocked"] is True

    @pytest.mark.asyncio
    async def test_family_child_age_blocked(self):
        state = _make_state(
            intent={"scene": "family", "child_age": 3},
            plans=[{
                "plan_id": "g5",
                "title": "test",
                "activity": {
                    "id": "act_003", "name": "梵高展",
                    "suitable_age_min": 12, "suitable_age_max": 99,
                },
                "restaurant": {"id": "rest_001", "name": "轻食"},
                "deals": [],
                "risk_tips": [],
            }],
        )
        result = await guardrails_node(state)
        assert result["guardrail_result"]["blocked"] is True

    @pytest.mark.asyncio
    async def test_valid_drink_passes(self):
        valid_act = read_json("activities.json")[0]
        valid_rest = read_json("restaurants.json")[0]
        state = _make_state(
            plans=[{
                "plan_id": "g_drink_1",
                "title": "test",
                "activity": {"id": valid_act["id"], "name": valid_act["name"],
                             "suitable_age_min": 2, "suitable_age_max": 12},
                "restaurant": {"id": valid_rest["id"], "name": valid_rest["name"]},
                "drink": {"id": "drink_004", "name": "京A精酿啤酒"},
                "deals": [],
                "risk_tips": [],
            }],
        )
        result = await guardrails_node(state)
        assert result["guardrail_result"]["passed"] is True

    @pytest.mark.asyncio
    async def test_invalid_drink_id_blocked(self):
        valid_act = read_json("activities.json")[0]
        valid_rest = read_json("restaurants.json")[0]
        state = _make_state(
            plans=[{
                "plan_id": "g_drink_2",
                "title": "test",
                "activity": {"id": valid_act["id"], "name": valid_act["name"],
                             "suitable_age_min": 2, "suitable_age_max": 12},
                "restaurant": {"id": valid_rest["id"], "name": valid_rest["name"]},
                "drink": {"id": "drink_fake_999", "name": "假饮品"},
                "deals": [],
                "risk_tips": [],
            }],
        )
        result = await guardrails_node(state)
        assert result["guardrail_result"]["blocked"] is True
        assert any("drink" in i.lower() for i in result["guardrail_result"]["issues"])
