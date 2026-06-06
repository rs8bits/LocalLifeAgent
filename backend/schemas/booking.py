"""预约 Schema"""

from typing import Optional, Any
from pydantic import BaseModel


class BookingRequest(BaseModel):
    activity_id: Optional[str] = None
    restaurant_id: Optional[str] = None
    drink_id: Optional[str] = None
    user_id: str
    people: int
    time: str


class BookingResponse(BaseModel):
    success: bool
    booking_id: Optional[str] = None
    message: str
    detail: Optional[dict[str, Any]] = None
