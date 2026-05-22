"""附加服务 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json
from backend.mock_api.filters import matches_any_tag, matches_party_type, matches_scene

router = APIRouter(prefix="/api/mock", tags=["add_ons"])


@router.get("/add-ons")
async def list_add_ons(
    scene: Optional[str] = Query(None, description="旧场景兼容过滤"),
    party_type: Optional[str] = Query(None, description="同行人画像过滤"),
    area: Optional[str] = Query(None, description="配送区域"),
    tag: Optional[str] = Query(None, description="标签过滤"),
    tags_any: Optional[list[str]] = Query(None, description="任一标签匹配"),
):
    """查询附加服务列表，支持按 party_type、区域和标签过滤"""
    data = read_json("add_ons.json")
    results = data

    if scene:
        results = [a for a in results if matches_scene(a, scene)]
    if party_type:
        results = [a for a in results if matches_party_type(a, party_type)]

    if area:
        results = [a for a in results if area in a.get("available_areas", [])]

    if tag:
        results = [a for a in results if tag in a.get("tags", [])]
    if tags_any:
        results = [a for a in results if matches_any_tag(a, tags_any)]

    return {"count": len(results), "results": results}
