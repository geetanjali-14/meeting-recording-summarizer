import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/ogg",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-matroska",
}

MAX_FILE_SIZE_BYTES = 524_288_000  # 500 MB


class MeetingCreateRequest(BaseModel):
    """Payload for POST /api/v1/meetings requesting creation and presigned upload URL."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    meeting_date: date | None = None
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(...)
    file_size_bytes: int = Field(..., gt=0, le=MAX_FILE_SIZE_BYTES)


class MeetingCreateResponseData(BaseModel):
    """Response data on 201 Created from POST /api/v1/meetings."""

    meeting_id: uuid.UUID
    recording_id: uuid.UUID
    status: str
    upload_url: str
    upload_token: str
    expires_in_seconds: int


class MeetingListItem(BaseModel):
    """Summary item for GET /api/v1/meetings."""

    model_config = ConfigDict(from_attributes=True)

    meeting_id: uuid.UUID
    title: str
    meeting_date: date
    status: str
    created_at: datetime


class MeetingRecordingDetail(BaseModel):
    """Recording metadata in meeting detail response."""

    model_config = ConfigDict(from_attributes=True)

    recording_id: uuid.UUID
    filename: str
    content_type: str
    file_size_bytes: int
    status: str


class MeetingJobDetail(BaseModel):
    """Processing job metadata in meeting detail response."""

    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    status: str
    attempt: int


class MeetingDetailResponseData(BaseModel):
    """Response data for GET /api/v1/meetings/{id}."""

    model_config = ConfigDict(from_attributes=True)

    meeting_id: uuid.UUID
    title: str
    description: str | None = None
    meeting_date: date
    status: str
    created_at: datetime
    recording: MeetingRecordingDetail | None = None
    job: MeetingJobDetail | None = None
