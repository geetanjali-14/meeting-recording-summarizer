from app.models.processing_job import (
    InvalidJobStateTransitionError,
    JobStage,
    JobStatus,
)


class JobStateMachine:
    """Enforces state machine invariants for ProcessingJob statuses and stages."""

    VALID_STATUS_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
        JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED},
        JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PENDING},
        JobStatus.COMPLETED: {JobStatus.PENDING},  # Can restart from beginning
        JobStatus.FAILED: {JobStatus.PENDING},  # Retry re-enqueues to PENDING
        JobStatus.CANCELLED: {JobStatus.PENDING},  # Can retry or restart
    }

    # Sequential progression of stages
    STAGE_ORDER: list[JobStage] = [
        JobStage.CREATED,
        JobStage.VALIDATING,
        JobStage.EXTRACTING_AUDIO,
        JobStage.TRANSCRIBING,
        JobStage.DIARIZING,
        JobStage.ANALYZING,
        JobStage.VERIFYING,
        JobStage.SAVING,
        JobStage.COMPLETED,
    ]

    @classmethod
    def validate_status_transition(cls, current_status: JobStatus, new_status: JobStatus) -> None:
        """Validates that a status transition is permitted."""
        if current_status == new_status:
            return

        allowed = cls.VALID_STATUS_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise InvalidJobStateTransitionError(
                f"Illegal job status transition from '{current_status}' to '{new_status}'."
            )

    @classmethod
    def validate_stage_transition(
        cls, current_stage: JobStage, new_stage: JobStage, is_terminal: bool = False
    ) -> None:
        """Validates that a stage transition is valid."""
        if current_stage == new_stage:
            return

        if new_stage == JobStage.FAILED:
            return  # Can fail from any stage

        if current_stage == JobStage.COMPLETED or current_stage == JobStage.FAILED:
            raise InvalidJobStateTransitionError(
                f"Cannot transition from terminal stage '{current_stage}' to '{new_stage}'."
            )
