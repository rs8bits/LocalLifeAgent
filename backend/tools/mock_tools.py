"""具体工具实现：直接读取 Mock Data 或复用存储层逻辑"""

from typing import Optional

from backend.tools.base import BaseTool, ToolResult
from backend.mock_api.storage import read_json


def _matches_scene(item: dict, scene: str) -> bool:
    """兼容 scene 和 suitable_scenes 的场景匹配"""
    if item.get("scene") == scene:
        return True
    suitable = item.get("suitable_scenes", [])
    return scene in suitable


class SearchActivitiesTool(BaseTool):
    name = "search_activities"
    description = "搜索活动，可按场景、距离、儿童年龄、室内外、标签等过滤"

    async def run(
        self,
        scene: Optional[str] = None,
        radius_km: Optional[float] = None,
        child_age: Optional[int] = None,
        indoor: Optional[bool] = None,
        tag: Optional[str] = None,
    ) -> ToolResult:
        try:
            data = read_json("activities.json")
            results = data

            if scene:
                results = [a for a in results if _matches_scene(a, scene)]

            if radius_km is not None:
                results = [a for a in results if a.get("distance_km", float("inf")) <= radius_km]

            if child_age is not None:
                results = [
                    a for a in results
                    if a.get("suitable_age_min", 0) <= child_age <= a.get("suitable_age_max", 99)
                ]

            if indoor is not None:
                results = [a for a in results if a.get("indoor") == indoor]

            if tag:
                results = [a for a in results if tag in a.get("tags", [])]

            return ToolResult(
                tool=self.name,
                status="ok",
                message=f"找到 {len(results)} 个活动",
                data=results,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="查询活动失败", error=str(e)
            )


class SearchRestaurantsTool(BaseTool):
    name = "search_restaurants"
    description = "搜索餐厅，可按场景、距离、人数、标签、可用性、排队时间等过滤"

    async def run(
        self,
        scene: Optional[str] = None,
        radius_km: Optional[float] = None,
        party_size: Optional[int] = None,
        tag: Optional[str] = None,
        available: Optional[bool] = None,
        max_queue_minutes: Optional[int] = None,
    ) -> ToolResult:
        try:
            data = read_json("restaurants.json")
            results = data

            if scene:
                results = [r for r in results if _matches_scene(r, scene)]

            if radius_km is not None:
                results = [r for r in results if r.get("distance_km", float("inf")) <= radius_km]

            if party_size is not None:
                results = [
                    r for r in results
                    if r.get("party_size_min", 0) <= party_size <= r.get("party_size_max", 99)
                ]

            if tag:
                results = [r for r in results if tag in r.get("tags", [])]

            if available is not None:
                results = [r for r in results if r.get("available") == available]

            if max_queue_minutes is not None:
                results = [r for r in results if r.get("queue_minutes", 0) <= max_queue_minutes]

            return ToolResult(
                tool=self.name,
                status="ok",
                message=f"找到 {len(results)} 个餐厅",
                data=results,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="查询餐厅失败", error=str(e)
            )


class EstimateRouteTool(BaseTool):
    name = "estimate_route"
    description = "估算从起点到终点的路线和交通方式"

    async def run(
        self,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        transport: Optional[str] = None,
    ) -> ToolResult:
        try:
            data = read_json("routes.json")
            results = data

            if origin:
                results = [r for r in results if origin in r.get("origin", "")]
            if destination:
                results = [r for r in results if destination in r.get("destination", "")]
            if transport:
                results = [r for r in results if r.get("transport") == transport]

            if not results:
                # fallback：返回全部路线供参考
                return ToolResult(
                    tool=self.name,
                    status="ok",
                    message="未找到精确匹配路线，返回可用路线供参考",
                    data=data,
                )

            return ToolResult(
                tool=self.name,
                status="ok",
                message=f"找到 {len(results)} 条路线",
                data=results,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="查询路线失败", error=str(e)
            )


class GetWeatherTool(BaseTool):
    name = "get_weather"
    description = "获取指定日期和区域的天气信息"

    async def run(
        self,
        date: Optional[str] = None,
        location: Optional[str] = None,
    ) -> ToolResult:
        try:
            data = read_json("weather.json")
            results = data

            if date:
                results = [w for w in results if w.get("date") == date]
            if location:
                results = [w for w in results if location in w.get("location", "")]

            return ToolResult(
                tool=self.name,
                status="ok",
                message=f"找到 {len(results)} 条天气信息",
                data=results,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="查询天气失败", error=str(e)
            )


class GetDealsTool(BaseTool):
    name = "get_deals"
    description = "获取指定 POI 的团购券信息"

    async def run(self, poi_id: str) -> ToolResult:
        try:
            data = read_json("deals.json")
            results = [d for d in data if d.get("poi_id") == poi_id]

            return ToolResult(
                tool=self.name,
                status="ok",
                message=f"找到 {len(results)} 个团购券",
                data=results,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="查询团购券失败", error=str(e)
            )
