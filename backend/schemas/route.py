"""路线 Schema"""

from typing import Optional
from pydantic import BaseModel


class Route(BaseModel):
    id: str
    origin: str
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    destination: str
    dest_lat: Optional[float] = None
    dest_lng: Optional[float] = None
    distance_km: float
    duration_min: int
    transport: str
    cost: int
    description: str
    source: Optional[str] = None
    time_window: Optional[str] = None
    traffic_level: Optional[str] = None
    parking_tip: Optional[str] = None
    platform_notice: Optional[str] = None
