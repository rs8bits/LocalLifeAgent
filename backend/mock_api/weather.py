"""天气 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query

from backend.mock_api.storage import read_json

router = APIRouter(prefix="/api/mock", tags=["weather"])


@router.get("/weather")
async def get_weather(
    date: Optional[str] = Query(None, description="日期，格式 YYYY-MM-DD"),
    location: Optional[str] = Query(None, description="区域名称，如 朝阳区"),
):
    """查询天气，支持按日期和区域过滤"""
    data = read_json("weather.json")
    results = data

    if date:
        results = [w for w in results if w.get("date") == date]

    if location:
        results = [w for w in results if location in w.get("location", "")]

    return {"count": len(results), "results": results}
