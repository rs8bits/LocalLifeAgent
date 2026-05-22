"""外卖 / 闪送 Mock API"""

from typing import Optional
from fastapi import APIRouter, Query, HTTPException

from backend.mock_api.storage import read_json, append_to_json, generate_order_id
from backend.mock_api.filters import matches_any_tag, matches_party_type, matches_scene
from backend.schemas.delivery import (
    DeliveryQuoteRequest,
    DeliveryQuoteResponse,
    DeliveryOrderRequest,
    DeliveryOrderResponse,
)

router = APIRouter(prefix="/api/mock/delivery", tags=["delivery"])

DELIVERY_ITEMS_FILE = "delivery_items.json"
DELIVERY_ORDERS_FILE = "delivery_orders.json"
ORDERS_FILE = "orders.json"


def _find_item(item_id: str) -> dict | None:
    for item in read_json(DELIVERY_ITEMS_FILE):
        if item.get("id") == item_id:
            return item
    return None


def _area_supported(item: dict, target_area: str | None) -> bool:
    if not target_area:
        return True
    return target_area in item.get("available_areas", [])


def _build_quote(item: dict, quantity: int, target_area: str | None) -> dict:
    delivery_fee = item.get("delivery_fee", 0)
    total_price = item.get("avg_price", 0) * max(quantity, 1) + delivery_fee
    estimated_delivery_min = item.get("estimated_delivery_min", 0)
    return {
        "item_id": item.get("id"),
        "item_name": item.get("name"),
        "merchant_name": item.get("merchant_name"),
        "quantity": quantity,
        "target_area": target_area,
        "total_price": total_price,
        "estimated_delivery_min": estimated_delivery_min,
        "prep_time_min": item.get("prep_time_min", 0),
        "delivery_fee": delivery_fee,
        "platform_notice": item.get("platform_notice"),
    }


@router.get("/items")
async def list_delivery_items(
    scene: Optional[str] = Query(None, description="旧场景兼容过滤"),
    party_type: Optional[str] = Query(None, description="同行人画像过滤"),
    area: Optional[str] = Query(None, description="可配送商圈"),
    tag: Optional[str] = Query(None, description="标签过滤"),
    tags_any: Optional[list[str]] = Query(None, description="任一标签匹配"),
    sub_category: Optional[str] = Query(None, description="子品类: food / drink / cake / flower / gift"),
    max_eta_min: Optional[int] = Query(None, description="最大预计配送分钟数"),
):
    """查询可外卖 / 闪送的商品列表"""
    results = read_json(DELIVERY_ITEMS_FILE)

    if scene:
        results = [item for item in results if matches_scene(item, scene)]
    if party_type:
        results = [item for item in results if matches_party_type(item, party_type)]
    if area:
        results = [item for item in results if area in item.get("available_areas", [])]
    if tag:
        results = [item for item in results if tag in item.get("tags", [])]
    if tags_any:
        results = [item for item in results if matches_any_tag(item, tags_any)]
    if sub_category:
        results = [item for item in results if item.get("sub_category") == sub_category]
    if max_eta_min is not None:
        results = [item for item in results if item.get("estimated_delivery_min", 999) <= max_eta_min]

    results = [item for item in results if item.get("available") and item.get("stock_remaining", 0) > 0]
    return {"count": len(results), "results": results}


@router.post("/quote", response_model=DeliveryQuoteResponse)
async def quote_delivery(req: DeliveryQuoteRequest):
    """估算外卖 / 闪送配送费用和时效"""
    item = _find_item(req.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"配送商品不存在: {req.item_id}")
    if not item.get("available", False):
        return DeliveryQuoteResponse(success=False, message=f"商品「{item['name']}」当前不可下单")
    if not _area_supported(item, req.target_area):
        return DeliveryQuoteResponse(
            success=False,
            item_id=req.item_id,
            message=f"商品「{item['name']}」暂不支持配送到 {req.target_area}",
            detail={"available_areas": item.get("available_areas", [])},
        )

    detail = _build_quote(item, req.quantity, req.target_area)
    return DeliveryQuoteResponse(
        success=True,
        message=f"预计 {detail['estimated_delivery_min']} 分钟送达，Mock 费用 {detail['total_price']} 元",
        item_id=req.item_id,
        total_price=detail["total_price"],
        estimated_delivery_min=detail["estimated_delivery_min"],
        earliest_arrival_time=req.desired_arrival_time,
        detail=detail,
    )


@router.post("/orders", response_model=DeliveryOrderResponse)
async def create_delivery_order(req: DeliveryOrderRequest):
    """创建 Mock 外卖 / 闪送订单（不涉及真实支付和真实配送）"""
    item = _find_item(req.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"配送商品不存在: {req.item_id}")
    if not item.get("available", False):
        return DeliveryOrderResponse(success=False, message=f"商品「{item['name']}」当前不可下单")
    if not _area_supported(item, req.target_area):
        return DeliveryOrderResponse(
            success=False,
            message=f"商品「{item['name']}」暂不支持配送到 {req.target_area}",
            detail={"available_areas": item.get("available_areas", [])},
        )

    order_id = generate_order_id()
    quote = _build_quote(item, req.quantity, req.target_area)
    record = {
        "order_id": order_id,
        "user_id": req.user_id,
        "order_type": "delivery",
        "item_id": req.item_id,
        "item_name": item.get("name"),
        "merchant_name": item.get("merchant_name"),
        "quantity": req.quantity,
        "target_area": req.target_area,
        "target_poi_id": req.target_poi_id,
        "desired_arrival_time": req.desired_arrival_time,
        "status": "confirmed",
        "message": f"Mock 外卖/闪送订单已创建（非真实支付/配送），订单号: {order_id}",
        "quote": quote,
        "note": req.note,
    }
    append_to_json(DELIVERY_ORDERS_FILE, record)
    append_to_json(ORDERS_FILE, {
        "order_id": order_id,
        "user_id": req.user_id,
        "order_type": "delivery",
        "payload": record,
        "status": "confirmed",
        "message": record["message"],
    })

    return DeliveryOrderResponse(
        success=True,
        order_id=order_id,
        message=record["message"],
        detail=record,
    )
