"""团购券 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json

router = APIRouter(prefix="/api/mock", tags=["deals"])


@router.get("/deals")
async def list_deals(
    poi_id: Optional[str] = Query(None, description="关联的 POI ID"),
):
    """查询团购券列表，支持按 POI ID 过滤"""
    data = read_json("deals.json")
    results = data

    if poi_id:
        results = [d for d in results if d.get("poi_id") == poi_id]

    return {"count": len(results), "results": results}
