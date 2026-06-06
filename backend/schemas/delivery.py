"""外卖 / 闪送 Schema"""

from typing import Optional, Any
from pydantic import BaseModel


class DeliveryQuoteRequest(BaseModel):
    item_id: str
    quantity: int = 1
    target_area: Optional[str] = None
    target_poi_id: Optional[str] = None
    desired_arrival_time: Optional[str] = None


class DeliveryQuoteResponse(BaseModel):
    success: bool
    message: str
    item_id: str | None = None
    total_price: int | None = None
    estimated_delivery_min: int | None = None
    earliest_arrival_time: str | None = None
    detail: Optional[dict[str, Any]] = None


class DeliveryOrderRequest(BaseModel):
    user_id: str
    item_id: str
    quantity: int = 1
    target_area: Optional[str] = None
    target_poi_id: Optional[str] = None
    desired_arrival_time: Optional[str] = None
    note: Optional[str] = None


class DeliveryOrderResponse(BaseModel):
    success: bool
    order_id: Optional[str] = None
    message: str
    detail: Optional[dict[str, Any]] = None
