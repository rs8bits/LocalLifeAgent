"""团购券 Schema"""

from pydantic import BaseModel


class Deal(BaseModel):
    id: str
    poi_id: str
    poi_name: str
    title: str
    original_price: int
    deal_price: int
    discount: str
    description: str
    valid_until: str
    quantity_available: int
    deal_type: str | None = None
    source: str | None = None
    stock_status: str | None = None
    sales_count: int | None = None
    requires_booking: bool | None = None
    purchase_limit: int | None = None
    usable_weekends: bool | None = None
    valid_time: str | None = None
    refund_rule: str | None = None
    verification_method: str | None = None
    platform_notice: str | None = None
