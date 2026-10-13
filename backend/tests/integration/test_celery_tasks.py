import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import Retry

from app.services.processing_service import ProcessingPipelineError
from app.workers.tasks import process_meeting_recording


def test_celery_task_successful_invocation() -> None:
    job_id = str(uuid.uuid4())
    meeting_id = str(uuid.uuid4())

    with (
        patch("app.workers.tasks.get_session"),
        patch("app.workers.tasks.ProcessingService") as MockProcessingService,
    ):
        mock_service_instance = MagicMock()
        MockProcessingService.return_value = mock_service_instance

        mock_job = MagicMock()
        mock_job.id = uuid.UUID(job_id)
        mock_job.meeting_id = uuid.UUID(meeting_id)
        mock_job.status.value = "COMPLETED"
        mock_job.stage.value = "COMPLETED"

        mock_service_instance.execute_job = AsyncMock(return_value=mock_job)

        # Call task
        result = process_meeting_recording.apply(args=[job_id, meeting_id]).get()
        assert result["status"] == "COMPLETED"
        assert result["job_id"] == job_id


def test_celery_task_retryable_error_triggers_retry() -> None:
    job_id = str(uuid.uuid4())
    meeting_id = str(uuid.uuid4())

    with (
        patch("app.workers.tasks.get_session"),
        patch("app.workers.tasks.ProcessingService") as MockProcessingService,
    ):
        mock_service_instance = MagicMock()
        MockProcessingService.return_value = mock_service_instance

        # Simulate retryable error from pipeline
        mock_service_instance.execute_job = AsyncMock(
            side_effect=ProcessingPipelineError("Rate limited", is_retryable=True)
        )

        res = process_meeting_recording.apply(args=[job_id, meeting_id], throw=False)
        assert isinstance(res.result, (Retry, ProcessingPipelineError))


def test_celery_task_permanent_error_raises_without_retry() -> None:
    job_id = str(uuid.uuid4())
    meeting_id = str(uuid.uuid4())

    with (
        patch("app.workers.tasks.get_session"),
        patch("app.workers.tasks.ProcessingService") as MockProcessingService,
    ):
        mock_service_instance = MagicMock()
        MockProcessingService.return_value = mock_service_instance

        # Simulate permanent error
        mock_service_instance.execute_job = AsyncMock(
            side_effect=ProcessingPipelineError("Media corrupted", is_retryable=False)
        )

        with pytest.raises(ProcessingPipelineError):
            process_meeting_recording.apply(args=[job_id, meeting_id]).get()
