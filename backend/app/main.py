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
        debug=False,  # Always False at FastAPI layer to prevent leaking tracebacks to HTTP clients
        lifespan=lifespan,
    )

    # Security Headers Middleware
    from app.core.middleware import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)

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
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Sanitizes unexpected internal exceptions, preventing stack trace/credential leaks."""
        from app.api.v1.utils import get_request_id

        req_id = get_request_id(request)
        logger.error(
            "Unhandled server exception on %s: %s",
            request.url.path,
            exc,
            exc_info=True,
            extra={
                "path": request.url.path,
                "request_id": req_id,
                "endpoint": request.url.path,
            },
        )
        envelope = create_error_envelope(
            code="INTERNAL_ERROR",
            message="An unexpected internal server error occurred.",
            request=request,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=envelope.model_dump(mode="json"),
        )

    # Mount API v1 router
    app.include_router(api_v1_router, prefix="/api/v1")

    # Mount static assets and web UI router
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    from app.api.web import web_router

    static_path = Path(__file__).resolve().parent / "static"
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon() -> FileResponse:
            ico_file = static_path / "favicon.ico"
            if ico_file.exists():
                return FileResponse(ico_file, media_type="image/x-icon")
            svg_file = static_path / "favicon.svg"
            return FileResponse(svg_file, media_type="image/svg+xml")

    app.include_router(web_router)

    return app


app = create_app()
