"""天气 Schema"""

from pydantic import BaseModel


class Weather(BaseModel):
    date: str
    location: str
    condition: str
    temperature_high: int
    temperature_low: int
    humidity: int
    wind_level: int
    air_quality: str
    aqi: int
    outdoor_suitable: bool
    tips: str
    source: str | None = None
    weather_risk_level: str | None = None
    recommend_indoor: bool | None = None
    platform_notice: str | None = None
