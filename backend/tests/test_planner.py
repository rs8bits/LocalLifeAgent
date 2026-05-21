"""Planner 测试"""

import pytest
from backend.agent.planner import plan_for_message
from backend.llm.deepseek_client import LLMResult


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
    async def test_sing_and_drink_only_searches_needed_domains(self, monkeypatch):
        """唱歌+喝酒应只搜索 play/drink，不应顺手查 eat/delivery。"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="今晚想唱歌，然后去喝酒",
        )
        search_logs = [
            log for log in result["tool_logs"]
            if log["tool"] in ("search_places", "search_delivery_items")
        ]
        messages = [log["message"] for log in search_logs]
        assert any("(play)" in msg for msg in messages)
        assert any("(drink)" in msg for msg in messages)
        assert not any("(eat)" in msg for msg in messages), messages
        assert not any(log["tool"] == "search_delivery_items" for log in search_logs), search_logs
        assert result["plans"][0]["restaurant"] is None
        assert result["plans"][0]["activity"]["category"] == "KTV"
        assert result["plans"][0]["drink"]["sub_category"] == "bar"

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


class TestDeliveryPlanner:
    """外卖/闪送规划"""

    @pytest.mark.asyncio
    async def test_delivery_domain_generates_actions_without_llm(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="今天下午和朋友唱歌吃饭，帮我闪送一束鲜花到餐厅",
        )
        plans = result["plans"]
        assert len(plans) >= 1
        assert result["intent"]["delivery_preferences"], "应识别外卖/闪送偏好"
        assert any(p.get("delivery_items") for p in plans), "方案应包含配送商品"
        assert any(
            action.get("type") == "order_delivery"
            for plan in plans
            for action in plan.get("actions", [])
        ), "确认阶段应有配送下单 action"

    @pytest.mark.asyncio
    async def test_delivery_only_generates_plan(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="帮我闪送一个生日蛋糕到餐厅",
        )
        plans = result["plans"]
        assert len(plans) >= 1
        assert plans[0].get("delivery_items")
        assert any(a["type"] == "order_delivery" for a in plans[0].get("actions", []))

    @pytest.mark.asyncio
    async def test_llm_composer_output_is_used_and_validated(self, monkeypatch):
        async def fake_llm_parse(message: str):
            return None

        async def fake_llm_resolve(message: str, intent_dict: dict, catalog: dict):
            return None

        async def fake_chat_json(messages, temperature=0.2):
            return LLMResult(json_data={
                "plans": [{
                    "plan_id": "plan_001",
                    "title": "LLM鲜花聚会方案",
                    "selected_refs": {
                        "activity_id": "act_009",
                        "restaurant_id": "rest_002",
                        "drink_id": None,
                        "delivery_item_ids": ["delivery_004"],
                    },
                    "timeline": [
                        {"time": "14:00", "type": "activity", "ref_id": "act_009", "title": "唱歌", "duration_min": 120},
                        {"time": "17:30", "type": "restaurant", "ref_id": "rest_002", "title": "吃饭", "duration_min": 75},
                        {"time": "17:30", "type": "delivery", "ref_id": "delivery_004", "title": "鲜花送达餐厅", "duration_min": 5},
                    ],
                    "actions": [
                        {"action_id": "a1", "type": "book_activity", "ref_id": "act_009", "scheduled_time": "14:00", "quantity": 4},
                        {"action_id": "a2", "type": "book_restaurant", "ref_id": "rest_002", "scheduled_time": "17:30", "quantity": 4},
                        {"action_id": "a3", "type": "order_delivery", "ref_id": "delivery_004", "scheduled_time": "17:30", "quantity": 1, "target_ref_id": "rest_002"},
                    ],
                    "recommend_reasons": ["LLM 根据候选组合了唱歌、晚餐和鲜花闪送"],
                    "risk_tips": [],
                }]
            })

        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", True)
        monkeypatch.setattr("backend.agent.intent_parser._llm_parse", fake_llm_parse)
        monkeypatch.setattr("backend.agent.tag_resolver._llm_resolve", fake_llm_resolve)
        monkeypatch.setattr("backend.agent.plan_composer.deepseek_client.chat_json", fake_chat_json)

        result = await plan_for_message(
            user_id="user_002",
            message="今天下午和4个朋友去唱歌吃饭，再闪送一束鲜花到餐厅",
        )
        plans = result["plans"]
        assert plans[0]["title"] == "LLM鲜花聚会方案"
        assert plans[0]["delivery_items"][0]["id"] == "delivery_004"
        assert any(a["type"] == "order_delivery" for a in plans[0]["actions"])

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


class TestDomainFiltering:
    """P0: 领域过滤 - 避免误召回无关领域"""

    @pytest.mark.asyncio
    async def test_light_lunch_only_searches_eat(self, monkeypatch):
        """输入「中午想吃点清淡的」应只查询 eat 领域"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        result = await plan_for_message(
            user_id="user_002",
            message="中午想吃点清淡的",
        )
        search_logs = [
            log for log in result["tool_logs"]
            if log["tool"] in ("search_places", "search_delivery_items")
        ]
        messages = [log["message"] for log in search_logs]
        # 应出现 search_places(eat)
        assert any("(eat)" in msg for msg in messages), f"应查询 eat 领域，实际日志: {messages}"
        # 不应出现 play/drink/delivery
        assert not any("(play)" in msg for msg in messages), f"不应查询 play 领域: {messages}"
        assert not any("(drink)" in msg for msg in messages), f"不应查询 drink 领域: {messages}"
        assert not any(
            log["tool"] == "search_delivery_items" for log in search_logs
        ), f"不应查询 delivery: {search_logs}"

    @pytest.mark.asyncio
    async def test_light_lunch_domains_is_only_eat(self, monkeypatch):
        """验证 tag_resolve_result.domains == ['eat']"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        from backend.agent.intent_parser import parse_intent
        from backend.agent.tag_resolver import resolve_domain_tags
        intent = await parse_intent("中午想吃点清淡的")
        intent_dict = intent.model_dump()
        tag_result = await resolve_domain_tags(
            message="中午想吃点清淡的",
            intent=intent,
            intent_dict=intent_dict,
        )
        assert tag_result["domains"] == ["eat"], \
            f"应只包含 eat，实际: {tag_result['domains']}"
        # 应包含健康/低卡相关标签
        eat_tags = tag_result.get("domain_tags", {}).get("eat", [])
        assert any(
            t in eat_tags for t in ["健康轻食", "健康", "低卡", "轻食"]
        ), f"eat 标签应对齐到健康/低卡: {eat_tags}"

    @pytest.mark.asyncio
    async def test_llm_template_all_domains_cleaned(self, monkeypatch):
        """LLM 返回模板式全领域 [play,eat,drink,delivery] 且无有效标签时应被丢弃"""
        async def fake_llm_resolve(message: str, intent_dict: dict, catalog: dict):
            return {
                "domains": ["play", "eat", "drink", "delivery"],
                "domain_categories": {"play": [], "eat": [], "drink": [], "delivery": []},
                "domain_tags": {"play": [], "eat": [], "drink": [], "delivery": []},
                "domain_sub_categories": {"play": [], "eat": [], "drink": [], "delivery": []},
                "domain_required": {
                    "play": False, "eat": False, "drink": False, "delivery": False
                },
                "domain_specs": [],
                "explanations": [],
            }

        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", True)
        monkeypatch.setattr(
            "backend.agent.tag_resolver._llm_resolve", fake_llm_resolve
        )
        # 同时禁用 LLM intent 解析，确保只用规则
        async def fake_llm_parse(message: str):
            return None
        monkeypatch.setattr(
            "backend.agent.intent_parser._llm_parse", fake_llm_parse
        )

        from backend.agent.intent_parser import parse_intent
        from backend.agent.tag_resolver import resolve_domain_tags
        intent = await parse_intent("中午想吃点清淡的")
        intent_dict = intent.model_dump()
        tag_result = await resolve_domain_tags(
            message="中午想吃点清淡的",
            intent=intent,
            intent_dict=intent_dict,
        )
        # LLM 返回了所有 4 个领域但都是空标签且 domain_required 全 false
        # 合并后应只保留规则识别出的 eat
        assert tag_result["domains"] == ["eat"], \
            f"LLM 模板全领域应被清洗到只保留 eat，实际: {tag_result['domains']}"

    @pytest.mark.asyncio
    async def test_sing_and_drink_domains_play_and_drink(self, monkeypatch):
        """唱歌+喝酒应包含 play 和 drink，且 play 对齐 KTV，drink 对齐酒吧"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        from backend.agent.intent_parser import parse_intent
        from backend.agent.tag_resolver import resolve_domain_tags
        intent = await parse_intent("今晚想唱歌，然后去喝酒")
        intent_dict = intent.model_dump()
        tag_result = await resolve_domain_tags(
            message="今晚想唱歌，然后去喝酒",
            intent=intent,
            intent_dict=intent_dict,
        )
        domains = tag_result["domains"]
        assert "play" in domains, f"应包含 play 领域: {domains}"
        assert "drink" in domains, f"应包含 drink 领域: {domains}"
        # play 应对齐 KTV/唱歌
        play_tags = tag_result.get("domain_tags", {}).get("play", [])
        assert any(t in play_tags for t in ["唱歌", "KTV"]), \
            f"play 标签应对齐 KTV: {play_tags}"
        # drink 应对齐 bar/精酿
        drink_tags = tag_result.get("domain_tags", {}).get("drink", [])
        assert any(t in drink_tags for t in ["bar", "精酿"]), \
            f"drink 标签应对齐 bar: {drink_tags}"

    @pytest.mark.asyncio
    async def test_delivery_cake_no_extra_domains(self, monkeypatch):
        """点蛋糕配送应包含 delivery，不应自动加 play"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        from backend.agent.intent_parser import parse_intent
        from backend.agent.tag_resolver import resolve_domain_tags
        intent = await parse_intent("想点个蛋糕送到餐厅")
        intent_dict = intent.model_dump()
        tag_result = await resolve_domain_tags(
            message="想点个蛋糕送到餐厅",
            intent=intent,
            intent_dict=intent_dict,
        )
        domains = tag_result["domains"]
        assert "delivery" in domains, f"应包含 delivery: {domains}"
        assert "play" not in domains, f"不应包含 play: {domains}"

    @pytest.mark.asyncio
    async def test_noon_singing_does_not_auto_add_eat(self, monkeypatch):
        """「中午」只是时间线索，不应单独触发 eat 领域"""
        monkeypatch.setattr("backend.config.settings.DEEPSEEK_API_KEY", "")
        monkeypatch.setattr("backend.llm.deepseek_client.deepseek_client.available", False)
        from backend.agent.intent_parser import parse_intent
        from backend.agent.tag_resolver import resolve_domain_tags
        intent = await parse_intent("中午想唱歌")
        tag_result = await resolve_domain_tags(
            message="中午想唱歌",
            intent=intent,
            intent_dict=intent.model_dump(),
        )
        domains = tag_result["domains"]
        assert "play" in domains, f"应包含 play: {domains}"
        assert "eat" not in domains, f"不应仅因中午自动加入 eat: {domains}"
