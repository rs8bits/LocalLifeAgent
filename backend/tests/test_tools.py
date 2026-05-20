"""工具测试"""

import pytest
from backend.tools.mock_tools import (
    SearchActivitiesTool,
    SearchRestaurantsTool,
    EstimateRouteTool,
    GetWeatherTool,
    GetDealsTool,
    SearchDrinksTool,
    SearchDeliveryItemsTool,
    EstimateDeliveryTool,
)
from backend.tools.tag_tools import GetTagCatalogTool, ResolveTagsTool
from backend.tools.registry import get_tool, list_tools


class TestSearchActivities:
    """活动搜索工具"""

    @pytest.mark.asyncio
    async def test_search_all(self):
        tool = SearchActivitiesTool()
        result = await tool.run()
        assert result.status == "ok"
        assert len(result.data) >= 8

    @pytest.mark.asyncio
    async def test_search_family(self):
        tool = SearchActivitiesTool()
        result = await tool.run(scene="family")
        assert result.status == "ok"
        for item in result.data:
            assert item["scene"] == "family" or "family" in item.get("suitable_scenes", [])

    @pytest.mark.asyncio
    async def test_search_child_age_filters_inappropriate(self):
        tool = SearchActivitiesTool()
        result = await tool.run(child_age=5)
        assert result.status == "ok"
        for item in result.data:
            age_min = item.get("suitable_age_min", 0)
            age_max = item.get("suitable_age_max", 99)
            assert age_min <= 5 <= age_max

    @pytest.mark.asyncio
    async def test_search_child_age_excludes_adult_only(self):
        # 梵高展 (act_003, 8-99岁) 应该被排除
        tool = SearchActivitiesTool()
        result = await tool.run(child_age=3)
        ids = [a["id"] for a in result.data]
        assert "act_003" not in ids

    @pytest.mark.asyncio
    async def test_search_indoor(self):
        tool = SearchActivitiesTool()
        result = await tool.run(indoor=True)
        for item in result.data:
            assert item["indoor"] is True

    @pytest.mark.asyncio
    async def test_combined_filters(self):
        tool = SearchActivitiesTool()
        result = await tool.run(scene="family", radius_km=5.0, child_age=5, indoor=True)
        for item in result.data:
            assert item.get("indoor") is True
            assert item.get("distance_km", 0) <= 5.0
            assert item.get("suitable_age_min", 0) <= 5 <= item.get("suitable_age_max", 99)


class TestSearchRestaurants:
    """餐厅搜索工具"""

    @pytest.mark.asyncio
    async def test_search_all(self):
        tool = SearchRestaurantsTool()
        result = await tool.run()
        assert result.status == "ok"
        assert len(result.data) >= 10

    @pytest.mark.asyncio
    async def test_search_healthy(self):
        tool = SearchRestaurantsTool()
        result = await tool.run(tag="健康")
        for item in result.data:
            assert "健康" in item.get("tags", [])

    @pytest.mark.asyncio
    async def test_search_available(self):
        tool = SearchRestaurantsTool()
        result = await tool.run(available=True)
        for item in result.data:
            assert item["available"] is True

    @pytest.mark.asyncio
    async def test_search_short_queue(self):
        tool = SearchRestaurantsTool()
        result = await tool.run(max_queue_minutes=15)
        for item in result.data:
            assert item["queue_minutes"] <= 15

    @pytest.mark.asyncio
    async def test_search_party_size(self):
        tool = SearchRestaurantsTool()
        result = await tool.run(party_size=4)
        for item in result.data:
            assert item["party_size_min"] <= 4 <= item["party_size_max"]

    @pytest.mark.asyncio
    async def test_search_family_scene(self):
        tool = SearchRestaurantsTool()
        result = await tool.run(scene="family")
        for item in result.data:
            assert item["scene"] == "family" or "family" in item.get("suitable_scenes", [])


class TestEstimateRoute:
    """路线估算工具"""

    @pytest.mark.asyncio
    async def test_search_all(self):
        tool = EstimateRouteTool()
        result = await tool.run()
        assert result.status == "ok"
        assert len(result.data) >= 5

    @pytest.mark.asyncio
    async def test_search_by_transport(self):
        tool = EstimateRouteTool()
        result = await tool.run(transport="开车")
        for item in result.data:
            assert item["transport"] == "开车"


class TestGetWeather:
    """天气查询工具"""

    @pytest.mark.asyncio
    async def test_search_all(self):
        tool = GetWeatherTool()
        result = await tool.run()
        assert result.status == "ok"
        assert len(result.data) >= 2

    @pytest.mark.asyncio
    async def test_search_by_date(self):
        tool = GetWeatherTool()
        result = await tool.run(date="2026-05-20")
        for item in result.data:
            assert item["date"] == "2026-05-20"

    @pytest.mark.asyncio
    async def test_search_by_location(self):
        tool = GetWeatherTool()
        result = await tool.run(location="朝阳区")
        assert len(result.data) >= 1


class TestGetDeals:
    """团购券查询工具"""

    @pytest.mark.asyncio
    async def test_search_by_poi(self):
        tool = GetDealsTool()
        result = await tool.run(poi_id="rest_001")
        assert result.status == "ok"
        assert len(result.data) >= 1
        for item in result.data:
            assert item["poi_id"] == "rest_001"

    @pytest.mark.asyncio
    async def test_search_no_match(self):
        tool = GetDealsTool()
        result = await tool.run(poi_id="nonexistent")
        assert result.status == "ok"
        assert len(result.data) == 0


class TestSearchDrinks:
    """饮品搜索工具"""

    @pytest.mark.asyncio
    async def test_search_all(self):
        tool = SearchDrinksTool()
        result = await tool.run()
        assert result.status == "ok"
        assert len(result.data) >= 6

    @pytest.mark.asyncio
    async def test_search_bar(self):
        tool = SearchDrinksTool()
        result = await tool.run(sub_category="bar")
        assert result.status == "ok"
        for item in result.data:
            assert item["sub_category"] == "bar"

    @pytest.mark.asyncio
    async def test_search_family_excludes_bar(self):
        tool = SearchDrinksTool()
        result = await tool.run(scene="family")
        for item in result.data:
            assert item["sub_category"] != "bar"


class TestDeliveryTools:
    """外卖/闪送工具测试"""

    @pytest.mark.asyncio
    async def test_search_delivery_items_by_tag(self):
        tool = SearchDeliveryItemsTool()
        result = await tool.run(tags_any=["鲜花"])
        assert result.status == "ok"
        assert len(result.data) >= 1
        assert any("鲜花" in item.get("tags", []) for item in result.data)

    @pytest.mark.asyncio
    async def test_estimate_delivery(self):
        tool = EstimateDeliveryTool()
        result = await tool.run(item_id="delivery_003", quantity=1, target_area="三里屯商圈")
        assert result.status == "ok"
        assert result.data["estimated_delivery_min"] >= 1
        assert result.data["total_price"] > 0


class TestTagCatalogTool:
    """标签目录工具测试"""

    @pytest.mark.asyncio
    async def test_get_full_catalog(self):
        tool = GetTagCatalogTool()
        result = await tool.run()
        assert result.status == "ok"
        domains = result.data.get("domains", {})
        for d in ["play", "eat", "drink", "add_on"]:
            assert d in domains

    @pytest.mark.asyncio
    async def test_get_catalog_by_domain(self):
        tool = GetTagCatalogTool()
        result = await tool.run(domain="play")
        assert result.status == "ok"
        assert "tags" in result.data
        assert "categories" in result.data

    @pytest.mark.asyncio
    async def test_get_catalog_unknown_domain(self):
        tool = GetTagCatalogTool()
        result = await tool.run(domain="unknown")
        assert result.status == "error"


class TestResolveTagsTool:
    """标签解析工具测试"""

    @pytest.mark.asyncio
    async def test_resolve_singing_photography(self):
        tool = ResolveTagsTool()
        result = await tool.run(domain="play", keywords=["singing", "photography", "karaoke"])
        assert result.status == "ok"
        assert "唱歌" in result.data["matched_tags"]
        assert "拍照" in result.data["matched_tags"]

    @pytest.mark.asyncio
    async def test_resolve_coffee_bar_beer(self):
        tool = ResolveTagsTool()
        result = await tool.run(domain="drink", keywords=["coffee", "bar", "beer"])
        assert result.status == "ok"
        # coffee 直接命中 sub_category
        assert "coffee" in result.data["matched_sub_categories"]
        # bar 直接命中 sub_category
        assert "bar" in result.data["matched_sub_categories"]

    @pytest.mark.asyncio
    async def test_resolve_reports_unmatched(self):
        tool = ResolveTagsTool()
        result = await tool.run(domain="play", keywords=["skydiving"])
        assert result.status == "ok"
        assert "skydiving" in result.data["unmatched"]

    @pytest.mark.asyncio
    async def test_resolve_unknown_domain(self):
        tool = ResolveTagsTool()
        result = await tool.run(domain="unknown", keywords=["test"])
        assert result.status == "error"


class TestRegistry:
    """工具注册表测试"""

    def test_list_tools(self):
        tools = list_tools()
        assert len(tools) >= 8

    def test_get_tool(self):
        tool = get_tool("search_activities")
        assert tool is not None
        assert tool.name == "search_activities"

    def test_get_tag_catalog_tool(self):
        tool = get_tool("get_tag_catalog")
        assert tool is not None
        assert tool.name == "get_tag_catalog"

    def test_get_resolve_tags_tool(self):
        tool = get_tool("resolve_tags")
        assert tool is not None
        assert tool.name == "resolve_tags"

    def test_get_nonexistent_tool(self):
        tool = get_tool("nonexistent")
        assert tool is None
