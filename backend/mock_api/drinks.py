"""饮品 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json

router = APIRouter(prefix="/api/mock", tags=["drinks"])


def _matches_scene(item: dict, scene: str) -> bool:
    if item.get("scene") == scene:
        return True
    suitable = item.get("suitable_scenes", [])
    return scene in suitable


@router.get("/drinks")
async def list_drinks(
    scene: Optional[str] = Query(None, description="场景过滤: family / friends / general"),
    radius_km: Optional[float] = Query(None, description="最大距离 km"),
    tag: Optional[str] = Query(None, description="标签过滤"),
    sub_category: Optional[str] = Query(None, description="子品类: coffee / milk_tea / tea / bar"),
    max_queue_minutes: Optional[int] = Query(None, description="最大排队分钟数"),
):
    """查询饮品列表，支持按场景、距离、品类、标签和排队时间过滤"""
    data = read_json("drinks.json")
    results = data

    if scene:
        if scene == "family":
            results = [d for d in results if d.get("sub_category") != "bar"]
        results = [d for d in results if _matches_scene(d, scene)]

    if radius_km is not None:
        results = [d for d in results if d.get("distance_km", float("inf")) <= radius_km]

    if tag:
        results = [d for d in results if tag in d.get("tags", [])]

    if sub_category:
        results = [d for d in results if d.get("sub_category") == sub_category]

    if max_queue_minutes is not None:
        results = [d for d in results if d.get("queue_minutes", 0) <= max_queue_minutes]

    return {"count": len(results), "results": results}
