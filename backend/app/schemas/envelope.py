from typing import Generic, TypeVar
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ResponseMeta(BaseModel):
    """Metadata envelope for single resource responses."""

    model_config = ConfigDict(from_attributes=True)

    request_id: str
    timestamp: str


class ListResponseMeta(ResponseMeta):
    """Metadata envelope for paginated resource responses."""

    total_count: int
    page: int
    per_page: int
    has_next_page: bool


class SuccessEnvelope(BaseModel, Generic[T]):
    """Standard unified single-entity response envelope."""

    data: T
    meta: ResponseMeta


class ListEnvelope(BaseModel, Generic[T]):
    """Standard unified paginated response envelope."""

    data: list[T]
    meta: ListResponseMeta


class ErrorDetail(BaseModel):
    """Specific field-level or parameter-level error issue."""

    field: str | None = None
    issue: str


class ErrorPayload(BaseModel):
    """Unified error payload structure."""

    code: str
    message: str
    details: list[ErrorDetail] = []
    request_id: str


class ErrorEnvelope(BaseModel):
    """Standard unified error response envelope."""

    error: ErrorPayload

