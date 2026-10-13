import pytest

from app.models.processing_job import InvalidJobStateTransitionError, JobStage, JobStatus
from app.workers.job_state_machine import JobStateMachine


def test_job_state_machine_valid_status_transitions() -> None:
    # PENDING -> RUNNING
    JobStateMachine.validate_status_transition(JobStatus.PENDING, JobStatus.RUNNING)
    # PENDING -> CANCELLED
    JobStateMachine.validate_status_transition(JobStatus.PENDING, JobStatus.CANCELLED)
    # RUNNING -> COMPLETED
    JobStateMachine.validate_status_transition(JobStatus.RUNNING, JobStatus.COMPLETED)
    # RUNNING -> FAILED
    JobStateMachine.validate_status_transition(JobStatus.RUNNING, JobStatus.FAILED)
    # FAILED -> PENDING (Retry)
    JobStateMachine.validate_status_transition(JobStatus.FAILED, JobStatus.PENDING)


def test_job_state_machine_invalid_status_transitions() -> None:
    # COMPLETED is terminal
    with pytest.raises(InvalidJobStateTransitionError):
        JobStateMachine.validate_status_transition(JobStatus.COMPLETED, JobStatus.PENDING)

    with pytest.raises(InvalidJobStateTransitionError):
        JobStateMachine.validate_status_transition(JobStatus.COMPLETED, JobStatus.RUNNING)

    # CANCELLED is terminal
    with pytest.raises(InvalidJobStateTransitionError):
        JobStateMachine.validate_status_transition(JobStatus.CANCELLED, JobStatus.RUNNING)


def test_job_state_machine_stage_transitions() -> None:
    JobStateMachine.validate_stage_transition(JobStage.CREATED, JobStage.VALIDATING)
    JobStateMachine.validate_stage_transition(JobStage.VALIDATING, JobStage.EXTRACTING_AUDIO)
    JobStateMachine.validate_stage_transition(JobStage.EXTRACTING_AUDIO, JobStage.TRANSCRIBING)
    # Any stage can transition to FAILED
    JobStateMachine.validate_stage_transition(JobStage.TRANSCRIBING, JobStage.FAILED)

    with pytest.raises(InvalidJobStateTransitionError):
        JobStateMachine.validate_stage_transition(JobStage.COMPLETED, JobStage.VALIDATING)
