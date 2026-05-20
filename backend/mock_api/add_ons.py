"""附加服务 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json

router = APIRouter(prefix="/api/mock", tags=["add_ons"])


def _matches_scene(item: dict, scene: str) -> bool:
    if item.get("scene") == scene:
        return True
    suitable = item.get("suitable_scenes", [])
    return scene in suitable


@router.get("/add-ons")
async def list_add_ons(
    scene: Optional[str] = Query(None, description="场景过滤: family / friends / general"),
    area: Optional[str] = Query(None, description="配送区域"),
    tag: Optional[str] = Query(None, description="标签过滤"),
):
    """查询附加服务列表，支持按场景、区域和标签过滤"""
    data = read_json("add_ons.json")
    results = data

    if scene:
        results = [a for a in results if _matches_scene(a, scene)]

    if area:
        results = [a for a in results if area in a.get("available_areas", [])]

    if tag:
        results = [a for a in results if tag in a.get("tags", [])]

    return {"count": len(results), "results": results}
