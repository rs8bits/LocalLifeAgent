"""餐厅 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json

router = APIRouter(prefix="/api/mock", tags=["restaurants"])


def _matches_scene(item: dict, scene: str) -> bool:
    if item.get("scene") == scene:
        return True
    suitable = item.get("suitable_scenes", [])
    return scene in suitable


@router.get("/restaurants")
async def list_restaurants(
    scene: Optional[str] = Query(None, description="场景过滤: family / friends"),
    radius_km: Optional[float] = Query(None, description="最大距离 km"),
    party_size: Optional[int] = Query(None, description="用餐人数"),
    tag: Optional[str] = Query(None, description="标签过滤"),
    available: Optional[bool] = Query(None, description="是否仅可预订/有位"),
    max_queue_minutes: Optional[int] = Query(None, description="最大排队分钟数"),
):
    """查询餐厅列表，支持按场景、距离、人数、标签、可用性和排队时间过滤"""
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

    return {"count": len(results), "results": results}
