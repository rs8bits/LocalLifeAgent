"""订单 Schema"""

from typing import Optional, Any
from pydantic import BaseModel


class OrderRequest(BaseModel):
    user_id: str
    order_type: str
    payload: dict[str, Any]


class OrderResponse(BaseModel):
    success: bool
    order_id: Optional[str] = None
    message: str
    detail: Optional[dict[str, Any]] = None
