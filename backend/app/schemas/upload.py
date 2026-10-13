import uuid
from pydantic import BaseModel, ConfigDict


class ConfirmUploadRequest(BaseModel):
    """Payload for POST /api/v1/meetings/{id}/confirm-upload."""

    recording_id: uuid.UUID
    upload_token: str


class ConfirmUploadResponseData(BaseModel):
    """Response data on 202 Accepted for upload confirmation."""

    model_config = ConfigDict(from_attributes=True)

    meeting_id: uuid.UUID
    job_id: uuid.UUID
    status: str
    job_status: str

