"""预约 Mock API"""

from fastapi import APIRouter, HTTPException

from backend.schemas.booking import BookingRequest, BookingResponse
from backend.mock_api.storage import read_json, append_to_json, generate_booking_id

router = APIRouter(prefix="/api/mock/bookings", tags=["bookings"])

ACTIVITIES_FILE = "activities.json"
RESTAURANTS_FILE = "restaurants.json"
BOOKINGS_FILE = "bookings.json"


def _check_time_slot(available_slots: list[str], requested_time: str) -> bool:
    """检查请求时间是否在可用时段内"""
    return requested_time in available_slots


@router.post("/activity", response_model=BookingResponse)
async def book_activity(req: BookingRequest):
    """预约活动"""
    if not req.activity_id:
        raise HTTPException(status_code=400, detail="缺少 activity_id")

    activities = read_json(ACTIVITIES_FILE)
    target = None
    for a in activities:
        if a.get("id") == req.activity_id:
            target = a
            break

    if target is None:
        raise HTTPException(status_code=404, detail=f"活动不存在: {req.activity_id}")

    if not target.get("bookable", False):
        return BookingResponse(
            success=False,
            message=f"活动「{target['name']}」不可预约",
            detail={"reason": "该活动不支持在线预约", "activity_id": req.activity_id},
        )

    if not _check_time_slot(target.get("available_slots", []), req.time):
        return BookingResponse(
            success=False,
            message=f"活动「{target['name']}」在 {req.time} 无可用时段",
            detail={
                "reason": "请求时段不可用",
                "activity_id": req.activity_id,
                "requested_time": req.time,
                "available_slots": target.get("available_slots", []),
            },
        )

    booking_id = generate_booking_id("act")
    record = {
        "booking_id": booking_id,
        "type": "activity",
        "poi_id": req.activity_id,
        "poi_name": target["name"],
        "user_id": req.user_id,
        "people": req.people,
        "time": req.time,
        "status": "confirmed",
    }
    append_to_json(BOOKINGS_FILE, record)

    return BookingResponse(
        success=True,
        booking_id=booking_id,
        message=f"已成功预约「{target['name']}」{req.people}人，时间 {req.time}",
        detail=record,
    )


@router.post("/restaurant", response_model=BookingResponse)
async def book_restaurant(req: BookingRequest):
    """预约餐厅订位"""
    if not req.restaurant_id:
        raise HTTPException(status_code=400, detail="缺少 restaurant_id")

    restaurants = read_json(RESTAURANTS_FILE)
    target = None
    for r in restaurants:
        if r.get("id") == req.restaurant_id:
            target = r
            break

    if target is None:
        raise HTTPException(status_code=404, detail=f"餐厅不存在: {req.restaurant_id}")

    if not target.get("bookable", False):
        return BookingResponse(
            success=False,
            message=f"餐厅「{target['name']}」不可在线订位",
            detail={"reason": "该餐厅不支持在线订位", "restaurant_id": req.restaurant_id},
        )

    if not target.get("available", False):
        return BookingResponse(
            success=False,
            message=f"餐厅「{target['name']}」当前已约满，无可用位",
            detail={
                "reason": "餐厅无位",
                "restaurant_id": req.restaurant_id,
                "risk": target.get("risk"),
            },
        )

    if req.people > target.get("party_size_max", 99):
        return BookingResponse(
            success=False,
            message=f"餐厅「{target['name']}」最多容纳 {target['party_size_max']} 人",
            detail={
                "reason": "人数超限",
                "restaurant_id": req.restaurant_id,
                "max_party_size": target["party_size_max"],
                "requested_people": req.people,
            },
        )

    if not _check_time_slot(target.get("available_slots", []), req.time):
        return BookingResponse(
            success=False,
            message=f"餐厅「{target['name']}」在 {req.time} 无可用时段",
            detail={
                "reason": "请求时段不可用",
                "restaurant_id": req.restaurant_id,
                "requested_time": req.time,
                "available_slots": target.get("available_slots", []),
            },
        )

    booking_id = generate_booking_id("rest")
    record = {
        "booking_id": booking_id,
        "type": "restaurant",
        "poi_id": req.restaurant_id,
        "poi_name": target["name"],
        "user_id": req.user_id,
        "people": req.people,
        "time": req.time,
        "status": "confirmed",
    }
    append_to_json(BOOKINGS_FILE, record)

    return BookingResponse(
        success=True,
        booking_id=booking_id,
        message=f"已成功订位「{target['name']}」{req.people}人，时间 {req.time}",
        detail=record,
    )
