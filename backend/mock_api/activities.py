"""活动 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json

router = APIRouter(prefix="/api/mock", tags=["activities"])


def _matches_scene(item: dict, scene: str) -> bool:
    if item.get("scene") == scene:
        return True
    suitable = item.get("suitable_scenes", [])
    return scene in suitable


@router.get("/activities")
async def list_activities(
    scene: Optional[str] = Query(None, description="场景过滤: family / friends / general"),
    radius_km: Optional[float] = Query(None, description="最大距离 km"),
    child_age: Optional[int] = Query(None, description="儿童年龄，用于过滤适合年龄的活动"),
    indoor: Optional[bool] = Query(None, description="是否仅室内"),
    tag: Optional[str] = Query(None, description="标签过滤"),
):
    """查询活动列表，支持按场景、距离、儿童年龄、室内外和标签过滤"""
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

    return {"count": len(results), "results": results}
