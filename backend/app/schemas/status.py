import uuid

from pydantic import BaseModel, Field

from app.models.processing_job import JobStage, JobStatus


class JobStatusResponse(BaseModel):
    """Schema for GET /api/v1/meetings/{id}/status response data."""

    meeting_id: uuid.UUID
    job_id: uuid.UUID
    celery_task_id: str | None = None
    status: JobStatus
    stage: JobStage
    attempt: int = 0
    error_code: str | None = None
    error_message: str | None = None


class TranscriptSegmentResponse(BaseModel):
    """Schema for individual transcript utterance segment."""

    segment_id: uuid.UUID
    sequence_index: int
    start_time: float
    end_time: float
    speaker_label: str | None = None
    speaker: str | None = None
    text: str


class TranscriptResponse(BaseModel):
    """Schema for GET /api/v1/meetings/{id}/transcript response data."""

    transcript_id: uuid.UUID
    language: str | None = "en"
    total_duration_seconds: float | None = None
    segment_count: int = 0
    segments: list[TranscriptSegmentResponse] = Field(default_factory=list)
