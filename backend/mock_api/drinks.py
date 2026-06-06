"""饮品 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json
from backend.mock_api.filters import FAMILY_PARTY_TYPES, matches_all_tags, matches_any_tag, matches_party_type, matches_scene

router = APIRouter(prefix="/api/mock", tags=["drinks"])


@router.get("/drinks")
async def list_drinks(
    scene: Optional[str] = Query(None, description="旧场景兼容过滤"),
    party_type: Optional[str] = Query(None, description="同行人画像过滤"),
    radius_km: Optional[float] = Query(None, description="最大距离 km"),
    tag: Optional[str] = Query(None, description="标签过滤"),
    tags_any: Optional[list[str]] = Query(None, description="任一标签匹配"),
    tags_all: Optional[list[str]] = Query(None, description="全部标签匹配"),
    sub_category: Optional[str] = Query(None, description="子品类: coffee / milk_tea / tea / bar"),
    max_queue_minutes: Optional[int] = Query(None, description="最大排队分钟数"),
):
    """查询饮品列表，支持按 party_type、距离、品类、标签和排队时间过滤"""
    data = read_json("drinks.json")
    results = data

    if scene:
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

    return {"count": len(results), "results": results}
