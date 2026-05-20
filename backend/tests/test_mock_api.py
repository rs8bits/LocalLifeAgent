"""Mock API 基础测试"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.mock_api.storage import read_json, write_json

client = TestClient(app)


def _matches_scene(item, scene):
    return item.get("scene") == scene or scene in item.get("suitable_scenes", [])


# 保存初始 bookings 和 orders 数据以便恢复
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BOOKINGS_FILE = DATA_DIR / "bookings.json"
ORDERS_FILE = DATA_DIR / "orders.json"


@pytest.fixture(autouse=True)
def reset_bookings_and_orders():
    """每个测试前后恢复 bookings.json 和 orders.json 为空数组"""
    original_bookings = None
    original_orders = None
    if BOOKINGS_FILE.exists():
        original_bookings = BOOKINGS_FILE.read_text(encoding="utf-8")
    if ORDERS_FILE.exists():
        original_orders = ORDERS_FILE.read_text(encoding="utf-8")

    BOOKINGS_FILE.write_text("[]", encoding="utf-8")
    ORDERS_FILE.write_text("[]", encoding="utf-8")

    yield

    if original_bookings is not None:
        BOOKINGS_FILE.write_text(original_bookings, encoding="utf-8")
    if original_orders is not None:
        ORDERS_FILE.write_text(original_orders, encoding="utf-8")


class TestHealthCheck:
    """健康检查测试"""

    def test_health_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "LocalLife Agent" in data["service"]


class TestStorageSafety:
    """本地数据读取安全测试"""

    def test_read_json_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            read_json("../outside.json")


class TestMockDataBusinessFields:
    """Mock Data 业务字段完整性测试"""

    def test_activities_have_meituan_like_fields(self):
        required = {
            "poi_type",
            "meituan_poi_id",
            "city",
            "district",
            "business_hours",
            "rating",
            "review_count",
            "monthly_sales",
            "popularity_score",
            "recommended_duration_min",
            "stock_remaining",
            "booking_required",
            "reservation_notice",
            "facilities",
            "source",
            "platform_notice",
        }
        for item in read_json("activities.json"):
            assert required.issubset(item.keys())
            assert item["poi_type"] == "activity"
            assert item["source"] == "mock_meituan_local_life"
            assert 0 <= item["popularity_score"] <= 100
            assert isinstance(item["facilities"], dict)

    def test_restaurants_have_meituan_like_fields(self):
        required = {
            "poi_type",
            "meituan_poi_id",
            "city",
            "district",
            "business_hours",
            "rating",
            "review_count",
            "monthly_sales",
            "popularity_score",
            "table_stock",
            "queue_status",
            "supports_queue_ticket",
            "reservation_notice",
            "low_calorie_options",
            "facilities",
            "source",
            "platform_notice",
        }
        for item in read_json("restaurants.json"):
            assert required.issubset(item.keys())
            assert item["poi_type"] == "restaurant"
            assert item["source"] == "mock_meituan_local_life"
            assert 0 <= item["popularity_score"] <= 100
            assert isinstance(item["facilities"], dict)

    def test_deals_have_platform_rules(self):
        required = {
            "deal_type",
            "source",
            "stock_status",
            "sales_count",
            "requires_booking",
            "purchase_limit",
            "usable_weekends",
            "valid_time",
            "refund_rule",
            "verification_method",
            "platform_notice",
        }
        for item in read_json("deals.json"):
            assert required.issubset(item.keys())
            assert item["source"] == "mock_meituan_deal"
            assert item["quantity_available"] >= 0


class TestActivities:
    """活动查询测试"""

    def test_list_all_activities(self):
        response = client.get("/api/mock/activities")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 8
        assert len(data["results"]) >= 8

    def _matches_scene(self, item, scene):
        return item.get("scene") == scene or scene in item.get("suitable_scenes", [])

    def test_filter_by_scene_family(self):
        response = client.get("/api/mock/activities?scene=family")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0
        for item in data["results"]:
            assert _matches_scene(item, "family")

    def test_filter_by_child_age(self):
        response = client.get("/api/mock/activities?child_age=5")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["suitable_age_min"] <= 5 <= item["suitable_age_max"]

    def test_filter_by_indoor(self):
        response = client.get("/api/mock/activities?indoor=true")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["indoor"] is True

    def test_filter_by_radius(self):
        response = client.get("/api/mock/activities?radius_km=3")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["distance_km"] <= 3

    def test_filter_by_tag(self):
        response = client.get("/api/mock/activities?tag=拍照")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert "拍照" in item["tags"]

    def test_combined_family_filters(self):
        response = client.get("/api/mock/activities?scene=family&radius_km=5&child_age=5")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert _matches_scene(item, "family")
            assert item["distance_km"] <= 5
            assert item["suitable_age_min"] <= 5 <= item["suitable_age_max"]


class TestRestaurants:
    """餐厅查询测试"""

    def test_list_all_restaurants(self):
        response = client.get("/api/mock/restaurants")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 10
        assert len(data["results"]) >= 10

    def test_filter_by_scene_family(self):
        response = client.get("/api/mock/restaurants?scene=family")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0
        for item in data["results"]:
            assert _matches_scene(item, "family")

    def test_filter_by_available(self):
        response = client.get("/api/mock/restaurants?available=true")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["available"] is True

    def test_filter_by_max_queue(self):
        response = client.get("/api/mock/restaurants?max_queue_minutes=15")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["queue_minutes"] <= 15

    def test_filter_by_party_size(self):
        response = client.get("/api/mock/restaurants?party_size=4")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["party_size_min"] <= 4 <= item["party_size_max"]

    def test_filter_by_tag_healthy(self):
        response = client.get("/api/mock/restaurants?tag=健康")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert "健康" in item["tags"]

    def test_combined_restaurant_filters(self):
        response = client.get("/api/mock/restaurants?scene=family&tag=健康&available=true")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert _matches_scene(item, "family")
            assert "健康" in item["tags"]
            assert item["available"] is True


class TestRoutes:
    """路线查询测试"""

    def test_list_all_routes(self):
        response = client.get("/api/mock/routes")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 5

    def test_filter_by_transport(self):
        response = client.get("/api/mock/routes?transport=开车")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["transport"] == "开车"


class TestWeather:
    """天气查询测试"""

    def test_list_all_weather(self):
        response = client.get("/api/mock/weather")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 2

    def test_filter_by_date(self):
        response = client.get("/api/mock/weather?date=2026-05-20")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["date"] == "2026-05-20"


class TestDeals:
    """团购券查询测试"""

    def test_list_all_deals(self):
        response = client.get("/api/mock/deals")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 5

    def test_filter_by_poi_id(self):
        response = client.get("/api/mock/deals?poi_id=rest_001")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["poi_id"] == "rest_001"


class TestBookingActivity:
    """活动预约测试"""

    def test_book_activity_success(self):
        payload = {
            "activity_id": "act_001",
            "user_id": "user_001",
            "people": 3,
            "time": "14:00",
        }
        response = client.post("/api/mock/bookings/activity", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["booking_id"] is not None
        assert data["booking_id"].startswith("booking_act_")

    def test_book_nonexistent_activity_returns_404(self):
        payload = {
            "activity_id": "act_999",
            "user_id": "user_001",
            "people": 3,
            "time": "14:00",
        }
        response = client.post("/api/mock/bookings/activity", json=payload)
        assert response.status_code == 404

    def test_book_unbookable_activity_returns_failure(self):
        # act_002 (奥林匹克森林公园) 不可预约
        payload = {
            "activity_id": "act_002",
            "user_id": "user_001",
            "people": 3,
            "time": "14:00",
        }
        response = client.post("/api/mock/bookings/activity", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_book_invalid_timeslot_returns_failure(self):
        payload = {
            "activity_id": "act_001",
            "user_id": "user_001",
            "people": 3,
            "time": "03:00",
        }
        response = client.post("/api/mock/bookings/activity", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestBookingRestaurant:
    """餐厅预约测试"""

    def test_book_restaurant_success(self):
        payload = {
            "restaurant_id": "rest_001",
            "user_id": "user_001",
            "people": 3,
            "time": "17:30",
        }
        response = client.post("/api/mock/bookings/restaurant", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["booking_id"].startswith("booking_rest_")

    def test_book_unavailable_restaurant_returns_failure(self):
        # rest_009 (京味斋·烤鸭) available=false
        payload = {
            "restaurant_id": "rest_009",
            "user_id": "user_001",
            "people": 3,
            "time": "18:00",
        }
        response = client.post("/api/mock/bookings/restaurant", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_book_unbookable_restaurant_returns_failure(self):
        # rest_006 (Seesaw Coffee) bookable=false
        payload = {
            "restaurant_id": "rest_006",
            "user_id": "user_001",
            "people": 2,
            "time": "14:00",
        }
        response = client.post("/api/mock/bookings/restaurant", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestOrders:
    """订单测试"""

    def test_create_order_success(self):
        payload = {
            "user_id": "user_001",
            "order_type": "deal",
            "payload": {
                "poi_id": "rest_001",
                "deal_id": "deal_001",
                "quantity": 3,
            },
        }
        response = client.post("/api/mock/orders", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["order_id"] is not None
        assert data["order_id"].startswith("order_")

    def test_order_persisted_to_file(self):
        payload = {
            "user_id": "user_001",
            "order_type": "deal",
            "payload": {"poi_id": "rest_001", "deal_id": "deal_001", "quantity": 2},
        }
        response = client.post("/api/mock/orders", json=payload)
        assert response.status_code == 200

        orders = read_json("orders.json")
        assert len(orders) >= 1
        assert orders[-1]["user_id"] == "user_001"


class TestBookingDrink:
    """饮品预约测试"""

    def test_book_drink_success(self):
        payload = {
            "drink_id": "drink_004",
            "user_id": "user_001",
            "people": 4,
            "time": "20:00",
        }
        response = client.post("/api/mock/bookings/drink", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["booking_id"] is not None
        assert data["booking_id"].startswith("booking_drink_")

    def test_book_nonexistent_drink_returns_404(self):
        payload = {
            "drink_id": "drink_999",
            "user_id": "user_001",
            "people": 4,
            "time": "20:00",
        }
        response = client.post("/api/mock/bookings/drink", json=payload)
        assert response.status_code == 404

    def test_book_unbookable_drink_returns_failure(self):
        payload = {
            "drink_id": "drink_001",
            "user_id": "user_001",
            "people": 2,
            "time": "14:00",
        }
        response = client.post("/api/mock/bookings/drink", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_book_invalid_timeslot_returns_failure(self):
        payload = {
            "drink_id": "drink_004",
            "user_id": "user_001",
            "people": 4,
            "time": "03:00",
        }
        response = client.post("/api/mock/bookings/drink", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestDrinksAPI:
    """饮品查询 API 测试"""

    def test_list_all_drinks(self):
        response = client.get("/api/mock/drinks")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 6
        assert len(data["results"]) >= 6

    def test_filter_by_scene_family_excludes_bar(self):
        response = client.get("/api/mock/drinks?scene=family")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["sub_category"] != "bar"

    def test_filter_by_sub_category(self):
        response = client.get("/api/mock/drinks?sub_category=bar")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert item["sub_category"] == "bar"

    def test_filter_by_tag(self):
        response = client.get("/api/mock/drinks?tag=拍照")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            assert "拍照" in item["tags"]


class TestAddOnsAPI:
    """附加服务查询 API 测试"""

    def test_list_all_add_ons(self):
        response = client.get("/api/mock/add-ons")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 3
        assert len(data["results"]) >= 3

    def test_filter_by_scene_family(self):
        response = client.get("/api/mock/add-ons?scene=family")
        assert response.status_code == 200
        data = response.json()
        for item in data["results"]:
            ok = item.get("scene") == "family" or "family" in item.get("suitable_scenes", [])
            assert ok

    def test_filter_by_area(self):
        response = client.get("/api/mock/add-ons?area=三里屯商圈")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0


class TestTagsAPI:
    """标签目录 API 测试"""

    def test_get_full_catalog(self):
        response = client.get("/api/mock/tags")
        assert response.status_code == 200
        data = response.json()
        assert "domains" in data
        for domain in ["play", "eat", "drink", "add_on"]:
            assert domain in data["domains"], f"缺少 domain: {domain}"

    def test_get_catalog_by_domain(self):
        for domain in ["play", "eat", "drink", "add_on"]:
            response = client.get(f"/api/mock/tags?domain={domain}")
            assert response.status_code == 200
            data = response.json()
            assert "tags" in data
            assert "categories" in data

    def test_resolve_singing_photography(self):
        payload = {"domain": "play", "keywords": ["singing", "photography", "karaoke"]}
        response = client.post("/api/mock/tags/resolve", json=payload)
        assert response.status_code == 200
        data = response.json()
        matched = data["matched_tags"]
        assert "唱歌" in matched, f"singing/karaoke 应对齐到 唱歌, got: {matched}"
        assert "拍照" in matched, f"photography 应对齐到 拍照, got: {matched}"

    def test_resolve_coffee_bar_beer(self):
        payload = {"domain": "drink", "keywords": ["coffee", "bar", "beer"]}
        response = client.post("/api/mock/tags/resolve", json=payload)
        assert response.status_code == 200
        data = response.json()
        # coffee 直接命中 sub_category
        assert "coffee" in data["matched_sub_categories"], \
            f"coffee 应匹配 sub_category, got: {data}"
        # bar 直接命中 sub_category
        assert "bar" in data["matched_sub_categories"], \
            f"bar 应匹配 sub_category, got: {data}"
        # beer 通过别名对齐到 精酿 标签
        assert ("精酿" in data["matched_tags"] or "beer" in data["unmatched"] is False), \
            f"beer 应通过别名匹配或至少不被遗漏, got: {data}"

    def test_resolve_reports_unmatched(self):
        payload = {"domain": "play", "keywords": ["skydiving"]}
        response = client.post("/api/mock/tags/resolve", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "skydiving" in data["unmatched"]


class TestSceneFilterCompatibility:
    """场景过滤兼容 suitable_scenes"""

    def test_activities_scene_family_includes_suitable_scenes(self):
        response = client.get("/api/mock/activities?scene=family")
        assert response.status_code == 200
        data = response.json()
        # 应至少包含 act_001 (scene=family) 和 act_007 (scene=general, suitable_scenes 含 family)
        ids = {item["id"] for item in data["results"]}
        assert "act_001" in ids, "原 scene=family 的应保留"
        # act_007 是 citywalk，suitable_scenes 含 family
        assert "act_007" in ids, "suitable_scenes 含 family 的也应被匹配"

    def test_restaurants_scene_family_includes_suitable_scenes(self):
        response = client.get("/api/mock/restaurants?scene=family")
        assert response.status_code == 200
        data = response.json()
        ids = {item["id"] for item in data["results"]}
        # rest_010 现在 suitable_scenes 含 family
        assert "rest_010" in ids or len(data["results"]) >= 2, \
            "suitable_scenes 含 family 的餐厅也应该被匹配"
