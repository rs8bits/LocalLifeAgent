"""餐厅 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json
from backend.mock_api.filters import matches_all_tags, matches_any_tag, matches_party_type, matches_scene

router = APIRouter(prefix="/api/mock", tags=["restaurants"])


@router.get("/restaurants")
async def list_restaurants(
    scene: Optional[str] = Query(None, description="旧场景兼容过滤"),
    party_type: Optional[str] = Query(None, description="同行人画像过滤"),
    radius_km: Optional[float] = Query(None, description="最大距离 km"),
    party_size: Optional[int] = Query(None, description="用餐人数"),
    tag: Optional[str] = Query(None, description="标签过滤"),
    tags_any: Optional[list[str]] = Query(None, description="任一标签匹配"),
    tags_all: Optional[list[str]] = Query(None, description="全部标签匹配"),
    available: Optional[bool] = Query(None, description="是否仅可预订/有位"),
    max_queue_minutes: Optional[int] = Query(None, description="最大排队分钟数"),
):
    """查询餐厅列表，支持按 party_type、距离、人数、标签、可用性和排队时间过滤"""
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

    return {"count": len(results), "results": results}
