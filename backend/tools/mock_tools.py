"""具体工具实现：直接读取 Mock Data 或复用存储层逻辑"""

from typing import Optional

from backend.tools.base import BaseTool, ToolResult
from backend.mock_api.storage import read_json
from backend.mock_api.filters import (
    FAMILY_PARTY_TYPES,
    matches_all_tags,
    matches_any_tag,
    matches_party_type,
    matches_scene,
)


class SearchActivitiesTool(BaseTool):
    name = "search_activities"
    description = "搜索活动，可按同行人画像、距离、儿童年龄、室内外、标签等过滤"

    async def run(
        self,
        scene: Optional[str] = None,
        party_type: Optional[str] = None,
        radius_km: Optional[float] = None,
        child_age: Optional[int] = None,
        indoor: Optional[bool] = None,
        tag: Optional[str] = None,
        tags_any: Optional[list[str]] = None,
        tags_all: Optional[list[str]] = None,
    ) -> ToolResult:
        try:
            data = read_json("activities.json")
            results = data

            if scene:
                results = [a for a in results if matches_scene(a, scene)]

            if party_type:
                results = [a for a in results if matches_party_type(a, party_type)]

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
            if tags_any:
                results = [a for a in results if matches_any_tag(a, tags_any)]
            if tags_all:
                results = [a for a in results if matches_all_tags(a, tags_all)]

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
    description = "搜索餐厅，可按同行人画像、距离、人数、标签、可用性、排队时间等过滤"

    async def run(
        self,
        scene: Optional[str] = None,
        party_type: Optional[str] = None,
        radius_km: Optional[float] = None,
        party_size: Optional[int] = None,
        tag: Optional[str] = None,
        tags_any: Optional[list[str]] = None,
        tags_all: Optional[list[str]] = None,
        available: Optional[bool] = None,
        max_queue_minutes: Optional[int] = None,
    ) -> ToolResult:
        try:
            data = read_json("restaurants.json")
            results = data

            if scene:
                results = [r for r in results if matches_scene(r, scene)]

            if party_type:
                results = [r for r in results if matches_party_type(r, party_type)]

            if radius_km is not None:
                results = [r for r in results if r.get("distance_km", float("inf")) <= radius_km]

            if party_size is not None:
                results = [
                    r for r in results
                    if r.get("party_size_min", 0) <= party_size <= r.get("party_size_max", 99)
                ]

            if tag:
                results = [r for r in results if tag in r.get("tags", [])]
            if tags_any:
                results = [r for r in results if matches_any_tag(r, tags_any)]
            if tags_all:
                results = [r for r in results if matches_all_tags(r, tags_all)]

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


class SearchDrinksTool(BaseTool):
    name = "search_drinks"
    description = "搜索饮品店，可按同行人画像、距离、品类（奶茶/咖啡/酒吧/茶饮）、标签等过滤"

    async def run(
        self,
        scene: Optional[str] = None,
        party_type: Optional[str] = None,
        radius_km: Optional[float] = None,
        tag: Optional[str] = None,
        tags_any: Optional[list[str]] = None,
        tags_all: Optional[list[str]] = None,
        sub_category: Optional[str] = None,
        max_queue_minutes: Optional[int] = None,
    ) -> ToolResult:
        try:
            data = read_json("drinks.json")
            results = data

            if scene:
                # 家庭场景自动排除酒吧
                if scene == "family":
                    results = [d for d in results if d.get("sub_category") != "bar"]
                results = [d for d in results if matches_scene(d, scene)]

            if party_type:
                if party_type in FAMILY_PARTY_TYPES:
                    results = [d for d in results if d.get("sub_category") != "bar"]
                results = [d for d in results if matches_party_type(d, party_type)]

            if radius_km is not None:
                results = [d for d in results if d.get("distance_km", float("inf")) <= radius_km]

            if tag:
                results = [d for d in results if tag in d.get("tags", [])]
            if tags_any:
                results = [d for d in results if matches_any_tag(d, tags_any)]
            if tags_all:
                results = [d for d in results if matches_all_tags(d, tags_all)]

            if sub_category:
                results = [d for d in results if d.get("sub_category") == sub_category]

            if max_queue_minutes is not None:
                results = [d for d in results if d.get("queue_minutes", 0) <= max_queue_minutes]

            return ToolResult(
                tool=self.name,
                status="ok",
                message=f"找到 {len(results)} 个饮品店",
                data=results,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="查询饮品失败", error=str(e)
            )


# ── 统一场所搜索 ───────────────────────────────────────────────

_SOURCE_FILES = {
    "play": "activities.json",
    "eat": "restaurants.json",
    "drink": "drinks.json",
    "add_on": "add_ons.json",
    "delivery": "delivery_items.json",
}


def _searchable_tags(item: dict) -> set[str]:
    values = set(item.get("tags", []) or [])
    for key in ("category", "sub_category", "cuisine"):
        value = item.get(key)
        if value:
            values.add(value)
    return values


def _tag_match_score(item: dict, tags: list[str]) -> int:
    searchable = _searchable_tags(item)
    return sum(1 for tag in tags if tag in searchable)


class SearchPlacesTool(BaseTool):
    name = "search_places"
    description = "统一场所搜索，按领域(play/eat/drink/add_on)和同行人画像搜索，支持多标签 OR 召回和匹配数量排序"

    async def run(
        self,
        domain: str,
        scene: Optional[str] = None,
        party_type: Optional[str] = None,
        radius_km: Optional[float] = None,
        category: Optional[str] = None,
        categories_any: Optional[list[str]] = None,
        tags_any: Optional[list[str]] = None,
        tags_all: Optional[list[str]] = None,
        sub_category: Optional[str] = None,
        party_size: Optional[int] = None,
        child_age: Optional[int] = None,
        indoor: Optional[bool] = None,
        available: Optional[bool] = None,
        max_queue_minutes: Optional[int] = None,
    ) -> ToolResult:
        try:
            source = _SOURCE_FILES.get(domain)
            if not source:
                return ToolResult(
                    tool=self.name, status="error",
                    message=f"未知领域: {domain}，支持: {list(_SOURCE_FILES.keys())}",
                )
            data = read_json(source)
            results = data

            # 旧场景兼容过滤
            if scene:
                if domain == "drink" and scene == "family":
                    results = [d for d in results if d.get("sub_category") != "bar"]
                results = [d for d in results if matches_scene(d, scene)]

            # 真实同行人画像过滤
            if party_type:
                if domain == "drink" and party_type in FAMILY_PARTY_TYPES:
                    results = [d for d in results if d.get("sub_category") != "bar"]
                results = [d for d in results if matches_party_type(d, party_type)]

            # 距离
            if radius_km is not None:
                results = [r for r in results if r.get("distance_km", float("inf")) <= radius_km]

            # 类目
            if category:
                results = [r for r in results if r.get("category") == category]

            if categories_any:
                results = [r for r in results if r.get("category") in categories_any]

            # 子品类
            if sub_category:
                results = [r for r in results if r.get("sub_category") == sub_category]

            # 人数
            if party_size is not None:
                results = [
                    r for r in results
                    if r.get("party_size_min", 0) <= party_size <= r.get("party_size_max", 99)
                ]

            # 儿童年龄
            if child_age is not None:
                results = [
                    r for r in results
                    if r.get("suitable_age_min", 0) <= child_age <= r.get("suitable_age_max", 99)
                ]

            # 室内
            if indoor is not None:
                results = [r for r in results if r.get("indoor") == indoor]

            # 可用性
            if available is not None:
                results = [r for r in results if r.get("available") == available]

            # 排队
            if max_queue_minutes is not None:
                results = [r for r in results if r.get("queue_minutes", 0) <= max_queue_minutes]

            # 标签 OR 召回：命中任意 tag 即可入选，命中越多排序越靠前。
            tag_warnings: list[str] = []
            if tags_any:
                tagged = []
                for item in results:
                    match_score = _tag_match_score(item, tags_any)
                    if match_score:
                        item["_match_score"] = match_score
                        tagged.append(item)
                if tagged:
                    results = sorted(
                        tagged,
                        key=lambda r: (
                            r.get("_match_score", 0),
                            r.get("rating", 0),
                            -r.get("distance_km", 0),
                        ),
                        reverse=True,
                    )
                elif len(results) > 0 and tags_any:
                    tag_warnings.append(f"标签 {tags_any} 无匹配，已放宽标签条件")
                    # 不缩小结果

            if tags_all:
                tagged = [r for r in results if all(t in _searchable_tags(r) for t in tags_all)]
                if tagged:
                    results = tagged

            return ToolResult(
                tool=self.name,
                status="ok",
                message=f"找到 {len(results)} 个场所 ({domain})",
                data=results,
                error="; ".join(tag_warnings) if tag_warnings else None,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message=f"搜索失败 ({domain})", error=str(e),
            )


class SearchDeliveryItemsTool(BaseTool):
    name = "search_delivery_items"
    description = "搜索可外卖/闪送商品，支持同行人画像、配送商圈、标签、子品类和预计配送时间过滤"

    async def run(
        self,
        scene: Optional[str] = None,
        party_type: Optional[str] = None,
        area: Optional[str] = None,
        tag: Optional[str] = None,
        tags_any: Optional[list[str]] = None,
        category: Optional[str] = None,
        categories_any: Optional[list[str]] = None,
        sub_category: Optional[str] = None,
        max_eta_min: Optional[int] = None,
    ) -> ToolResult:
        try:
            results = read_json("delivery_items.json")

            if scene:
                results = [item for item in results if matches_scene(item, scene)]
            if party_type:
                results = [item for item in results if matches_party_type(item, party_type)]
            if area:
                results = [item for item in results if area in item.get("available_areas", [])]
            if category:
                results = [item for item in results if item.get("category") == category]
            if categories_any:
                results = [item for item in results if item.get("category") in categories_any]
            if tag:
                results = [item for item in results if tag in item.get("tags", [])]
            if sub_category:
                results = [item for item in results if item.get("sub_category") == sub_category]
            if max_eta_min is not None:
                results = [
                    item for item in results
                    if item.get("estimated_delivery_min", 999) <= max_eta_min
                ]

            tag_warnings: list[str] = []
            if tags_any:
                tagged = []
                for item in results:
                    match_score = _tag_match_score(item, tags_any)
                    if match_score:
                        item["_match_score"] = match_score
                        tagged.append(item)
                if tagged:
                    results = sorted(
                        tagged,
                        key=lambda r: (
                            r.get("_match_score", 0),
                            -r.get("estimated_delivery_min", 999),
                            r.get("stock_remaining", 0),
                        ),
                        reverse=True,
                    )
                elif results:
                    tag_warnings.append(f"标签 {tags_any} 无匹配，已放宽标签条件")

            results = [
                item for item in results
                if item.get("available") and item.get("stock_remaining", 0) > 0
            ]
            return ToolResult(
                tool=self.name,
                status="ok",
                message=f"找到 {len(results)} 个配送商品",
                data=results,
                error="; ".join(tag_warnings) if tag_warnings else None,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="查询配送商品失败", error=str(e)
            )


class EstimateDeliveryTool(BaseTool):
    name = "estimate_delivery"
    description = "估算外卖/闪送商品配送费用和时效"

    async def run(
        self,
        item_id: str,
        quantity: int = 1,
        target_area: Optional[str] = None,
    ) -> ToolResult:
        try:
            items = read_json("delivery_items.json")
            item = next((i for i in items if i.get("id") == item_id), None)
            if item is None:
                return ToolResult(
                    tool=self.name,
                    status="error",
                    message=f"配送商品不存在: {item_id}",
                )
            if target_area and target_area not in item.get("available_areas", []):
                return ToolResult(
                    tool=self.name,
                    status="error",
                    message=f"商品暂不支持配送到 {target_area}",
                    data={"available_areas": item.get("available_areas", [])},
                )
            total_price = item.get("avg_price", 0) * max(quantity, 1) + item.get("delivery_fee", 0)
            data = {
                "item_id": item_id,
                "item_name": item.get("name"),
                "merchant_name": item.get("merchant_name"),
                "quantity": quantity,
                "target_area": target_area,
                "total_price": total_price,
                "estimated_delivery_min": item.get("estimated_delivery_min", 0),
                "prep_time_min": item.get("prep_time_min", 0),
                "delivery_fee": item.get("delivery_fee", 0),
            }
            return ToolResult(
                tool=self.name,
                status="ok",
                message=f"预计 {data['estimated_delivery_min']} 分钟送达，费用 {total_price} 元",
                data=data,
            )
        except Exception as e:
            return ToolResult(
                tool=self.name, status="error", message="估算配送失败", error=str(e)
            )
