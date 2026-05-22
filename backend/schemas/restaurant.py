"""餐厅 Schema"""

from typing import Any, Optional
from pydantic import BaseModel, Field


class RestaurantBase(BaseModel):
    id: str
    name: str
    category: str
    area: str
    address: str
    distance_km: float
    avg_price: int
    tags: list[str]
    scene: str
    party_types: list[str] = Field(default_factory=list)
    cuisine: str
    indoor: bool
    party_size_min: int
    party_size_max: int
    child_friendly: bool
    queue_minutes: int
    available: bool
    available_slots: list[str]
    bookable: bool
    risk: Optional[str] = None
    description: str
    poi_type: Optional[str] = None
    meituan_poi_id: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    suitable_scenes: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    poi_status: Optional[str] = None
    business_hours: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    monthly_sales: Optional[int] = None
    popularity_score: Optional[float] = None
    recommended_duration_min: Optional[int] = None
    table_stock: Optional[int] = None
    queue_status: Optional[str] = None
    supports_queue_ticket: Optional[bool] = None
    reservation_notice: Optional[str] = None
    low_calorie_options: Optional[bool] = None
    platform_notice: Optional[str] = None
    facilities: Optional[dict[str, Any]] = None


class Restaurant(RestaurantBase):
    lat: Optional[float] = None
    lng: Optional[float] = None
    has_high_chair: bool = False
    has_kids_menu: bool = False
