import asyncio
import logging
from datetime import UTC, datetime
from typing import Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    version: str = "1.1.0"
    timestamp: str


class DependencyStatus(BaseModel):
    database: Literal["ready", "unreachable"]
    redis: Literal["ready", "unreachable"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "unready"]
    dependencies: DependencyStatus
    timestamp: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Minimal liveness health check probe."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        version="1.1.0",
        timestamp=datetime.now(UTC).isoformat(),
    )


async def check_database() -> bool:
    """Probes the primary PostgreSQL database with a bounded timeout."""
    try:
        async with asyncio.timeout(5.0):
            async with engine.connect() as conn:
                res = await conn.execute(text("SELECT 1"))
                return bool(res.scalar() == 1)
    except Exception as exc:
        logger.warning("Readiness probe database check failed: %s (%s)", exc.__class__.__name__, exc)
        return False


async def check_redis(redis_url: str) -> bool:
    """Probes the Redis task broker with a bounded timeout."""
    try:
        r = aioredis.from_url(redis_url, socket_timeout=2.0)
        try:
            async with asyncio.timeout(2.0):
                return bool(await r.ping())
        finally:
            close_method = getattr(r, "aclose", getattr(r, "close", None))
            if close_method is not None:
                await close_method()
    except Exception as exc:
        logger.warning("Readiness probe Redis check failed: %s", exc.__class__.__name__)
        return False


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={
        200: {"model": ReadinessResponse},
        503: {"model": ReadinessResponse},
    },
)
async def readiness_check() -> JSONResponse:
    """Dependency-aware readiness health check probe."""
    settings = get_settings()
    db_ready = await check_database()
    redis_ready = await check_redis(settings.REDIS_URL)

    is_ready = db_ready and redis_ready
    response_data = ReadinessResponse(
        status="ready" if is_ready else "unready",
        dependencies=DependencyStatus(
            database="ready" if db_ready else "unreachable",
            redis="ready" if redis_ready else "unreachable",
        ),
        timestamp=datetime.now(UTC).isoformat(),
    )

    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content=response_data.model_dump(mode="json"),
    )
