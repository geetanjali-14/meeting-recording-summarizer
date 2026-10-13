import datetime
import uuid

from fastapi import Request

from app.schemas.envelope import (
    ErrorDetail,
    ErrorEnvelope,
    ErrorPayload,
    ListResponseMeta,
    ResponseMeta,
)


def get_request_id(request: Request) -> str:
    """Extracts or generates request_id for response envelope and tracing."""
    req_id = request.headers.get("X-Request-ID")
    if not req_id:
        req_id = str(uuid.uuid4())
    return req_id


def current_iso_timestamp() -> str:
    """Returns current UTC ISO-8601 formatted timestamp."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=get_request_id(request),
        timestamp=current_iso_timestamp(),
    )


def create_list_meta(
    request: Request,
    total_count: int,
    page: int,
    per_page: int,
) -> ListResponseMeta:
    has_next_page = (page * per_page) < total_count
    return ListResponseMeta(
        request_id=get_request_id(request),
        timestamp=current_iso_timestamp(),
        total_count=total_count,
        page=page,
        per_page=per_page,
        has_next_page=has_next_page,
    )


def create_error_envelope(
    code: str,
    message: str,
    request: Request,
    details: list[ErrorDetail] | None = None,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        error=ErrorPayload(
            code=code,
            message=message,
            details=details or [],
            request_id=get_request_id(request),
        )
    )
