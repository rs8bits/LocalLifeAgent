"""路线 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json

router = APIRouter(prefix="/api/mock", tags=["routes"])


@router.get("/routes")
async def list_routes(
    origin: Optional[str] = Query(None, description="起点名称"),
    destination: Optional[str] = Query(None, description="终点名称"),
    transport: Optional[str] = Query(None, description="交通方式: 开车 / 地铁 / 打车"),
):
    """查询路线列表，支持按起终点和交通方式过滤"""
    data = read_json("routes.json")
    results = data

    if origin:
        results = [r for r in results if origin in r.get("origin", "")]

    if destination:
        results = [r for r in results if destination in r.get("destination", "")]

    if transport:
        results = [r for r in results if r.get("transport") == transport]

    return {"count": len(results), "results": results}
