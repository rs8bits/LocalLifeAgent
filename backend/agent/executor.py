"""执行器 - 在确认阶段执行预约、订位和 Mock 订单"""

from backend.mock_api.bookings import book_activity, book_restaurant, book_drink
from backend.mock_api.orders import create_order
from backend.mock_api.delivery import create_delivery_order
from backend.schemas.booking import BookingRequest
from backend.schemas.order import OrderRequest
from backend.schemas.delivery import DeliveryOrderRequest


def choose_available_slot(preferred_time: str, available_slots: list[str]) -> str | None:
    """选择最接近 preferred_time 的可用时段"""
    if not available_slots:
        return None
    if preferred_time in available_slots:
        return preferred_time
    # 找 preferred_time 之后最近的
    after = [s for s in available_slots if s >= preferred_time]
    if after:
        return min(after)
    # 否则返回第一个
    return available_slots[0]


async def execute_plan(session: dict, plan_id: str) -> dict:
    """执行确认操作：活动预约 + 餐厅订位 + Mock 订单"""
    plans = session.get("plans", [])
    selected = None
    for p in plans:
        if p.get("plan_id") == plan_id:
            selected = p
            break

    if not selected:
        return {
            "status": "failed",
            "bookings": [],
            "orders": [],
            "errors": [f"计划 {plan_id} 不存在"],
        }

    bookings = []
    orders = []
    errors = []

    user_id = session.get("user_id", "user_001")
    people = session.get("intent", {}).get("people_count") or 2
    actions = selected.get("actions") or []
    if actions:
        return await _execute_actions(selected, actions, user_id, people)

    # 1. 活动预约
    activity = selected.get("activity")
    if activity and activity.get("bookable"):
        slots = activity.get("available_slots", [])
        preferred = "14:00"
        if selected.get("timeline"):
            for t in selected["timeline"]:
                if t.get("type") == "activity":
                    preferred = t.get("time", "14:00")
                    break
        chosen = choose_available_slot(preferred, slots)
        if chosen:
            req = BookingRequest(
                activity_id=activity["id"],
                user_id=user_id,
                people=people,
                time=chosen,
            )
            result = await book_activity(req)
            bookings.append({
                "type": "activity",
                "poi_name": activity.get("name", ""),
                "success": result.success,
                "booking_id": result.booking_id,
                "message": result.message,
            })
            if not result.success:
                errors.append(f"活动预约失败: {result.message}")
        else:
            errors.append(f"活动「{activity.get('name', '')}」无可用时段")
    elif activity:
        bookings.append({
            "type": "activity",
            "poi_name": activity.get("name", ""),
            "success": False,
            "message": "该活动不支持在线预约，已跳过",
            "skipped": True,
        })

    # 2. 餐厅订位
    restaurant = selected.get("restaurant")
    if restaurant and restaurant.get("bookable") and restaurant.get("available"):
        slots = restaurant.get("available_slots", [])
        preferred = "17:30"
        if selected.get("timeline"):
            for t in selected["timeline"]:
                if t.get("type") == "restaurant":
                    preferred = t.get("time", "17:30")
                    break
        chosen = choose_available_slot(preferred, slots)
        if chosen:
            req = BookingRequest(
                restaurant_id=restaurant["id"],
                user_id=user_id,
                people=people,
                time=chosen,
            )
            result = await book_restaurant(req)
            bookings.append({
                "type": "restaurant",
                "poi_name": restaurant.get("name", ""),
                "success": result.success,
                "booking_id": result.booking_id,
                "message": result.message,
            })
            if not result.success:
                errors.append(f"餐厅订位失败: {result.message}")
        else:
            errors.append(f"餐厅「{restaurant.get('name', '')}」无可用时段")
    elif restaurant:
        bookings.append({
            "type": "restaurant",
            "poi_name": restaurant.get("name", ""),
            "success": False,
            "message": "该餐厅当前不可订位",
            "skipped": True,
        })

    # 3. 饮品预约
    drink = selected.get("drink")
    if drink and drink.get("bookable"):
        slots = drink.get("available_slots", [])
        preferred = "16:00"
        for t in (selected.get("timeline") or []):
            if t.get("type") == "drink":
                preferred = t.get("time", "16:00")
                break
        chosen = choose_available_slot(preferred, slots)
        if chosen:
            req = BookingRequest(
                drink_id=drink["id"],
                user_id=user_id,
                people=people,
                time=chosen,
            )
            result = await book_drink(req)
            bookings.append({
                "type": "drink",
                "poi_name": drink.get("name", ""),
                "success": result.success,
                "booking_id": result.booking_id,
                "message": result.message,
            })
            if not result.success:
                errors.append(f"饮品预约失败: {result.message}")
        else:
            bookings.append({
                "type": "drink",
                "poi_name": drink.get("name", ""),
                "success": False,
                "message": "该饮品店不支持在线预约，已跳过",
                "skipped": True,
            })
    elif drink:
        bookings.append({
            "type": "drink",
            "poi_name": drink.get("name", ""),
            "success": False,
            "message": "该饮品店不支持在线预约，已跳过",
            "skipped": True,
        })

    # 4. Mock 团购券订单
    deals = selected.get("deals", [])
    for deal in deals:
        req = OrderRequest(
            user_id=user_id,
            order_type="deal",
            payload={
                "poi_id": deal.get("poi_id", ""),
                "deal_id": deal.get("id", ""),
                "quantity": 1,
            },
        )
        result = await create_order(req)
        orders.append({
            "order_id": result.order_id,
            "deal_title": deal.get("title", ""),
            "success": result.success,
        })

    # 汇总状态
    if not errors:
        status = "success"
    elif bookings or orders:
        status = "partial_success"
    else:
        status = "failed"

    return {
        "status": status,
        "bookings": bookings,
        "orders": orders,
        "errors": errors,
    }


async def _execute_actions(
    selected: dict,
    actions: list[dict],
    user_id: str,
    people: int,
) -> dict:
    """按规划阶段生成的 action JSON 执行操作。"""
    bookings: list[dict] = []
    orders: list[dict] = []
    errors: list[str] = []

    poi_map = _build_plan_item_map(selected)
    deal_map = {d.get("id"): d for d in selected.get("deals", [])}

    for action in actions:
        action_type = action.get("type")
        ref_id = action.get("ref_id")
        scheduled_time = action.get("scheduled_time") or ""
        quantity = int(action.get("quantity") or 1)

        if action_type == "book_activity":
            activity = poi_map.get(ref_id)
            if not activity:
                errors.append(f"活动预约失败: 未找到 {ref_id}")
                continue
            result = await _book_activity_from_action(activity, user_id, people, scheduled_time)
            bookings.append(result)
            if not result.get("success") and not result.get("skipped"):
                errors.append(f"活动预约失败: {result.get('message', '')}")

        elif action_type == "book_restaurant":
            restaurant = poi_map.get(ref_id)
            if not restaurant:
                errors.append(f"餐厅订位失败: 未找到 {ref_id}")
                continue
            result = await _book_restaurant_from_action(restaurant, user_id, people, scheduled_time)
            bookings.append(result)
            if not result.get("success") and not result.get("skipped"):
                errors.append(f"餐厅订位失败: {result.get('message', '')}")

        elif action_type == "book_drink":
            drink = poi_map.get(ref_id)
            if not drink:
                errors.append(f"饮品预约失败: 未找到 {ref_id}")
                continue
            result = await _book_drink_from_action(drink, user_id, people, scheduled_time)
            bookings.append(result)
            if not result.get("success") and not result.get("skipped"):
                errors.append(f"饮品预约失败: {result.get('message', '')}")

        elif action_type == "order_deal":
            deal = deal_map.get(ref_id)
            if not deal:
                errors.append(f"团购券下单失败: 未找到 {ref_id}")
                continue
            result = await _order_deal(deal, user_id, quantity)
            orders.append(result)
            if not result.get("success"):
                errors.append(f"团购券下单失败: {deal.get('title', '')}")

        elif action_type == "order_delivery":
            item = poi_map.get(ref_id)
            if not item:
                errors.append(f"配送下单失败: 未找到 {ref_id}")
                continue
            target = poi_map.get(action.get("target_ref_id")) or {}
            result = await _order_delivery(item, user_id, quantity, scheduled_time, target)
            orders.append(result)
            if not result.get("success"):
                errors.append(f"配送下单失败: {result.get('message', '')}")

    if not errors:
        status = "success"
    elif bookings or orders:
        status = "partial_success"
    else:
        status = "failed"

    return {
        "status": status,
        "bookings": bookings,
        "orders": orders,
        "errors": errors,
    }


def _build_plan_item_map(plan: dict) -> dict[str, dict]:
    mapping = {}
    for key in ["activity", "restaurant", "drink"]:
        item = plan.get(key)
        if item and item.get("id"):
            mapping[item["id"]] = item
    for entry in plan.get("meal_restaurants") or []:
        restaurant = entry.get("restaurant") if isinstance(entry, dict) else None
        if restaurant and restaurant.get("id"):
            mapping[restaurant["id"]] = restaurant
    for item in plan.get("delivery_items") or []:
        if item.get("id"):
            mapping[item["id"]] = item
    return mapping


async def _book_activity_from_action(
    activity: dict,
    user_id: str,
    people: int,
    preferred_time: str,
) -> dict:
    if not activity.get("bookable"):
        return {
            "type": "activity",
            "poi_name": activity.get("name", ""),
            "success": False,
            "message": "该活动不支持在线预约，已跳过",
            "skipped": True,
        }
    chosen = choose_available_slot(preferred_time or "14:00", activity.get("available_slots", []))
    if not chosen:
        return {
            "type": "activity",
            "poi_name": activity.get("name", ""),
            "success": False,
            "message": "无可用时段",
        }
    result = await book_activity(BookingRequest(
        activity_id=activity["id"], user_id=user_id, people=people, time=chosen,
    ))
    return {
        "type": "activity",
        "poi_name": activity.get("name", ""),
        "success": result.success,
        "booking_id": result.booking_id,
        "message": result.message,
    }


async def _book_restaurant_from_action(
    restaurant: dict,
    user_id: str,
    people: int,
    preferred_time: str,
) -> dict:
    if not restaurant.get("bookable") or not restaurant.get("available"):
        return {
            "type": "restaurant",
            "poi_name": restaurant.get("name", ""),
            "success": False,
            "message": "该餐厅当前不可订位",
            "skipped": True,
        }
    chosen = choose_available_slot(preferred_time or "17:30", restaurant.get("available_slots", []))
    if not chosen:
        return {
            "type": "restaurant",
            "poi_name": restaurant.get("name", ""),
            "success": False,
            "message": "无可用时段",
        }
    result = await book_restaurant(BookingRequest(
        restaurant_id=restaurant["id"], user_id=user_id, people=people, time=chosen,
    ))
    return {
        "type": "restaurant",
        "poi_name": restaurant.get("name", ""),
        "success": result.success,
        "booking_id": result.booking_id,
        "message": result.message,
    }


async def _book_drink_from_action(
    drink: dict,
    user_id: str,
    people: int,
    preferred_time: str,
) -> dict:
    if not drink.get("bookable"):
        return {
            "type": "drink",
            "poi_name": drink.get("name", ""),
            "success": False,
            "message": "该饮品店不支持在线预约，已跳过",
            "skipped": True,
        }
    chosen = choose_available_slot(preferred_time or "16:00", drink.get("available_slots", []))
    if not chosen:
        return {
            "type": "drink",
            "poi_name": drink.get("name", ""),
            "success": False,
            "message": "无可用时段",
        }
    result = await book_drink(BookingRequest(
        drink_id=drink["id"], user_id=user_id, people=people, time=chosen,
    ))
    return {
        "type": "drink",
        "poi_name": drink.get("name", ""),
        "success": result.success,
        "booking_id": result.booking_id,
        "message": result.message,
    }


async def _order_deal(deal: dict, user_id: str, quantity: int) -> dict:
    req = OrderRequest(
        user_id=user_id,
        order_type="deal",
        payload={
            "poi_id": deal.get("poi_id", ""),
            "deal_id": deal.get("id", ""),
            "quantity": quantity,
        },
    )
    result = await create_order(req)
    return {
        "order_id": result.order_id,
        "order_type": "deal",
        "deal_title": deal.get("title", ""),
        "success": result.success,
    }


async def _order_delivery(
    item: dict,
    user_id: str,
    quantity: int,
    desired_arrival_time: str,
    target: dict,
) -> dict:
    req = DeliveryOrderRequest(
        user_id=user_id,
        item_id=item["id"],
        quantity=quantity,
        target_area=target.get("area") or item.get("area"),
        target_poi_id=target.get("id"),
        desired_arrival_time=desired_arrival_time or None,
        note="由 LocalLife Agent 规划确认后创建的 Mock 配送订单",
    )
    result = await create_delivery_order(req)
    return {
        "order_id": result.order_id,
        "order_type": "delivery",
        "item_name": item.get("name", ""),
        "success": result.success,
        "message": result.message,
        "detail": result.detail,
    }
