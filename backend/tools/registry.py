"""工具注册表"""

from backend.tools.base import BaseTool
from backend.tools.mock_tools import (
    SearchActivitiesTool,
    SearchRestaurantsTool,
    EstimateRouteTool,
    GetWeatherTool,
    GetDealsTool,
)

# 全局工具实例
_search_activities = SearchActivitiesTool()
_search_restaurants = SearchRestaurantsTool()
_estimate_route = EstimateRouteTool()
_get_weather = GetWeatherTool()
_get_deals = GetDealsTool()

# 工具名 → 实例映射
TOOLS: dict[str, BaseTool] = {
    _search_activities.name: _search_activities,
    _search_restaurants.name: _search_restaurants,
    _estimate_route.name: _estimate_route,
    _get_weather.name: _get_weather,
    _get_deals.name: _get_deals,
}


def get_tool(name: str) -> BaseTool | None:
    """根据名称获取工具实例"""
    return TOOLS.get(name)


def list_tools() -> list[dict[str, str]]:
    """列出所有已注册工具的名称和描述"""
    return [
        {"name": t.name, "description": t.description} for t in TOOLS.values()
    ]
