"""Agent 状态与输出 Schema"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class Companion(BaseModel):
    role: str  # "spouse" | "child" | "friend"
    age: Optional[int] = None
    diet_preference: Optional[str] = None


class Intent(BaseModel):
    scene: str = "general"  # "family" | "friends" | "general"
    date: str = "today"
    time_window: str = "afternoon"  # "afternoon" | "evening" | "unknown"
    duration_hours: Optional[int] = None
    people_count: Optional[int] = None
    companions: list[dict[str, Any]] = Field(default_factory=list)
    radius_km: float = 5.0
    distance_preference: str = "nearby"  # "nearby" | "flexible"
    budget_per_person: Optional[int] = None
    food_preferences: list[str] = Field(default_factory=list)
    activity_preferences: list[str] = Field(default_factory=list)
    child_age: Optional[int] = None
    needs_low_calorie: bool = False
    needs_photo_spot: bool = False
    avoid_queue_minutes: int = 30


class TimelineItem(BaseModel):
    time: str
    type: str  # "activity" | "restaurant" | "transit"
    title: str
    poi_id: str
    duration_min: int


class Budget(BaseModel):
    total: int
    per_person: int
    currency: str = "CNY"


class Plan(BaseModel):
    plan_id: str
    title: str
    scene: str
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    activity: Optional[dict[str, Any]] = None
    restaurant: Optional[dict[str, Any]] = None
    route: Optional[dict[str, Any]] = None
    deals: list[dict[str, Any]] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    queue_minutes: int = 0
    booking_status: str = "available"  # "available" | "partial" | "unavailable"
    risk_tips: list[str] = Field(default_factory=list)
    recommend_reasons: list[str] = Field(default_factory=list)
    score: float = 0.0
    score_reasons: list[str] = Field(default_factory=list)


class PlannerOutput(BaseModel):
    intent: dict[str, Any] = Field(default_factory=dict)
    plans: list[dict[str, Any]] = Field(default_factory=list)
    tool_logs: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
