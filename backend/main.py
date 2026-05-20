"""LocalLife Agent 后端入口"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings

app = FastAPI(title=settings.APP_TITLE, version=settings.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "service": "LocalLife Agent Mock API"}


# 注册 Mock API 路由
from backend.mock_api.activities import router as activities_router
from backend.mock_api.restaurants import router as restaurants_router
from backend.mock_api.routes import router as routes_router
from backend.mock_api.weather import router as weather_router
from backend.mock_api.deals import router as deals_router
from backend.mock_api.bookings import router as bookings_router
from backend.mock_api.orders import router as orders_router

app.include_router(activities_router)
app.include_router(restaurants_router)
app.include_router(routes_router)
app.include_router(weather_router)
app.include_router(deals_router)
app.include_router(bookings_router)
app.include_router(orders_router)
