import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ExportFormat(StrEnum):
    MARKDOWN = "markdown"
    JSON = "json"


class ExportRequest(BaseModel):
    """Request payload for exporting meeting analysis."""

    format: ExportFormat = Field(
        default=ExportFormat.MARKDOWN,
        description="Format of the export: 'markdown' or 'json'",
    )


class ExportResponse(BaseModel):
    """Response payload containing formatted export content."""

    meeting_id: uuid.UUID
    format: str
    filename: str
    content_type: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
