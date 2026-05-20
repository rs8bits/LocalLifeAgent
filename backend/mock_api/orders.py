"""订单 Mock API"""

from fastapi import APIRouter, HTTPException

from backend.schemas.order import OrderRequest, OrderResponse
from backend.mock_api.storage import read_json, append_to_json, generate_order_id

router = APIRouter(prefix="/api/mock", tags=["orders"])


@router.post("/orders", response_model=OrderResponse)
async def create_order(req: OrderRequest):
    """创建 Mock 订单（不涉及真实支付）"""
    order_id = generate_order_id()

    record = {
        "order_id": order_id,
        "user_id": req.user_id,
        "order_type": req.order_type,
        "payload": req.payload,
        "status": "confirmed",
        "message": f"Mock 订单已创建（非真实支付），订单号: {order_id}",
    }

    append_to_json("orders.json", record)

    return OrderResponse(
        success=True,
        order_id=order_id,
        message=f"Mock 订单已创建（非真实支付），订单号: {order_id}",
        detail=record,
    )
