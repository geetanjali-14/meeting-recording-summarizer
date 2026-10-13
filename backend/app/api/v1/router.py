from fastapi import APIRouter

from app.api.v1 import health, meetings, uploads

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(meetings.router)
api_v1_router.include_router(uploads.router)
