"""活动 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json
from backend.mock_api.filters import matches_all_tags, matches_any_tag, matches_party_type, matches_scene

router = APIRouter(prefix="/api/mock", tags=["activities"])


@router.get("/activities")
async def list_activities(
    scene: Optional[str] = Query(None, description="旧场景兼容过滤"),
    party_type: Optional[str] = Query(None, description="同行人画像过滤"),
    radius_km: Optional[float] = Query(None, description="最大距离 km"),
    child_age: Optional[int] = Query(None, description="儿童年龄，用于过滤适合年龄的活动"),
    indoor: Optional[bool] = Query(None, description="是否仅室内"),
    tag: Optional[str] = Query(None, description="标签过滤"),
    tags_any: Optional[list[str]] = Query(None, description="任一标签匹配"),
    tags_all: Optional[list[str]] = Query(None, description="全部标签匹配"),
):
    """查询活动列表，支持按 party_type、距离、儿童年龄、室内外和标签过滤"""
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

    return {"count": len(results), "results": results}
