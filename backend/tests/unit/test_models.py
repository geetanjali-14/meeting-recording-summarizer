import uuid

import pytest

from app.models.meeting import Meeting, MeetingStatus
from app.models.processing_job import (
    InvalidJobStateTransitionError,
    JobStage,
    JobStatus,
    ProcessingJob,
)
from app.models.recording import Recording, RecordingStatus
from app.models.user import User


def test_user_model_initialization() -> None:
    user = User(email="alex@example.com", display_name="Alex Rivera")
    assert user.email == "alex@example.com"
    assert user.display_name == "Alex Rivera"
    assert user.is_active is True


def test_meeting_model_initialization() -> None:
    user_id = uuid.uuid4()
    meeting = Meeting(user_id=user_id, title="Sprint Planning Q4")
    assert meeting.user_id == user_id
    assert meeting.title == "Sprint Planning Q4"
    assert meeting.status == MeetingStatus.CREATED
    assert meeting.speaker_mappings == {}


def test_recording_model_initialization() -> None:
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    rec = Recording(
        meeting_id=meeting_id,
        user_id=user_id,
        storage_key=f"users/{user_id}/recordings/{meeting_id}/audio.mp4",
        original_filename="audio.mp4",
        content_type="audio/mp4",
        file_size_bytes=1048576,
    )
    assert rec.status == RecordingStatus.PRESIGNED
    assert rec.file_size_bytes == 1048576


def test_processing_job_state_machine_valid_transitions() -> None:
    job = ProcessingJob(
        meeting_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=JobStatus.PENDING,
        stage=JobStage.CREATED,
    )

    # Test sequential stage progression
    stages_to_test = [
        (JobStatus.RUNNING, JobStage.VALIDATING),
        (JobStatus.RUNNING, JobStage.TRANSCRIBING),
        (JobStatus.RUNNING, JobStage.DIARIZING),
        (JobStatus.RUNNING, JobStage.ANALYZING),
        (JobStatus.COMPLETED, JobStage.COMPLETED),
    ]

    for expected_status, expected_stage in stages_to_test:
        job.transition_to(expected_status, expected_stage)
        assert job.status == expected_status
        assert job.stage == expected_stage


def test_processing_job_state_machine_invalid_transitions() -> None:
    job = ProcessingJob(
        meeting_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=JobStatus.COMPLETED,
        stage=JobStage.COMPLETED,
    )

    # Completed jobs cannot transition back to pending or running
    with pytest.raises(InvalidJobStateTransitionError):
        job.transition_to(JobStatus.PENDING)

    with pytest.raises(InvalidJobStateTransitionError):
        job.transition_to(JobStatus.RUNNING)

    # Cancelled jobs cannot transition to running or completed
    cancelled_job = ProcessingJob(
        meeting_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=JobStatus.CANCELLED,
    )
    with pytest.raises(InvalidJobStateTransitionError):
        cancelled_job.transition_to(JobStatus.RUNNING)
