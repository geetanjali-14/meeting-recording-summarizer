import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.api.v1.utils import create_error_envelope
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.schemas.envelope import ErrorDetail

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan handler for FastAPI application startup and shutdown."""
    settings = get_settings()
    setup_logging(log_level=settings.LOG_LEVEL)
    logger.info("Application starting up...", extra={"environment": settings.APP_ENV})
    yield
    logger.info("Application shutting down...")


def create_app() -> FastAPI:
    """Application factory for FastAPI HTTP server."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global Exception Handlers ensuring standard envelope compliance
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for error in exc.errors():
            field_loc = ".".join(str(loc) for loc in error.get("loc", []))
            details.append(
                ErrorDetail(
                    field=field_loc if field_loc else None,
                    issue=error.get("msg", "Invalid value"),
                )
            )
        envelope = create_error_envelope(
            code="VALIDATION_ERROR",
            message="Request payload failed validation.",
            request=request,
            details=details,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=envelope.model_dump(mode="json"),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        # If request is not under /api, preserve default detail response
        if not request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=getattr(exc, "headers", None),
            )

        code_map = {
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_409_CONFLICT: "CONFLICT",
            status.HTTP_422_UNPROCESSABLE_ENTITY: "VALIDATION_ERROR",
            status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
            status.HTTP_502_BAD_GATEWAY: "STORAGE_ERROR",
        }
        code = code_map.get(exc.status_code, "INTERNAL_ERROR")
        headers = getattr(exc, "headers", None)
        envelope = create_error_envelope(
            code=code,
            message=str(exc.detail),
            request=request,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope.model_dump(mode="json"),
            headers=headers,
        )

    # Mount API v1 router
    app.include_router(api_v1_router, prefix="/api/v1")

    return app


app = create_app()
