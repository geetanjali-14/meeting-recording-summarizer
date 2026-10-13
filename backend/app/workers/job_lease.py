import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.processing_job import JobStage, JobStatus, ProcessingJob

logger = logging.getLogger(__name__)


class LeaseError(Exception):
    """Base exception for worker lease errors."""

    pass


class LeaseAcquisitionError(LeaseError):
    """Raised when a worker fails to acquire a job lease."""

    pass


class JobLeaseTracker:
    """Manages PostgreSQL durable worker leases, heartbeats, and stale job recovery."""

    def __init__(
        self,
        session: AsyncSession,
        lease_duration_seconds: int = 120,
    ) -> None:
        self.session = session
        self.lease_duration = timedelta(seconds=lease_duration_seconds)

    async def claim_job(
        self,
        job_id: uuid.UUID,
        worker_id: str,
    ) -> ProcessingJob | None:
        """Claims an available or stale job for the worker.

        A job is eligible for claim if:
        1. status == PENDING
        OR
        2. status == RUNNING and lease_expires_at < now (stale/crashed worker lease)
        """
        now = datetime.now(UTC)
        stmt = (
            select(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                or_(
                    ProcessingJob.status == JobStatus.PENDING,
                    (ProcessingJob.status == JobStatus.RUNNING)
                    & (ProcessingJob.lease_expires_at < now),
                ),
            )
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            return None

        # Update lease fields
        job.status = JobStatus.RUNNING
        job.stage = JobStage.VALIDATING
        job.worker_id = worker_id
        job.claimed_at = now
        job.heartbeat_at = now
        job.lease_expires_at = now + self.lease_duration
        job.attempt += 1
        if job.started_at is None:
            job.started_at = now

        await self.session.flush()
        return job

    async def renew_heartbeat(
        self,
        job_id: uuid.UUID,
        worker_id: str,
    ) -> bool:
        """Extends lease expiration and updates heartbeat_at timestamp."""
        now = datetime.now(UTC)
        stmt = (
            select(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.worker_id == worker_id,
                ProcessingJob.status == JobStatus.RUNNING,
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            return False

        job.heartbeat_at = now
        job.lease_expires_at = now + self.lease_duration
        await self.session.flush()
        return True

    async def release_lease(
        self,
        job_id: uuid.UUID,
        worker_id: str,
        target_status: JobStatus = JobStatus.COMPLETED,
        target_stage: JobStage = JobStage.COMPLETED,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ProcessingJob | None:
        """Releases the worker lease and marks final terminal or retry status."""
        stmt = (
            select(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.worker_id == worker_id,
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            return None

        now = datetime.now(UTC)
        job.status = target_status
        job.stage = target_stage
        job.lease_expires_at = None
        if target_status == JobStatus.COMPLETED:
            job.completed_at = now
            job.error_code = None
            job.error_message = None
        elif target_status == JobStatus.FAILED:
            job.error_code = error_code
            job.error_message = error_message

        await self.session.flush()
        return job
