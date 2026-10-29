import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.processing_job import JobStage, JobStatus, ProcessingJob


class JobRepository:
    """Repository for ProcessingJob operations, strictly scoped by user_id."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ProcessingJob:
        job = ProcessingJob(
            meeting_id=meeting_id,
            user_id=user_id,
            status=JobStatus.PENDING,
            stage=JobStage.CREATED,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_by_meeting_id(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        for_update: bool = False,
    ) -> ProcessingJob | None:
        stmt = select(ProcessingJob).where(
            ProcessingJob.meeting_id == meeting_id,
            ProcessingJob.user_id == user_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(
        self,
        job_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ProcessingJob | None:
        stmt = select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_system(
        self,
        job_id: uuid.UUID,
    ) -> ProcessingJob | None:
        """Fetches job by ID without user scope, for worker process."""
        stmt = select(ProcessingJob).where(ProcessingJob.id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_stage(
        self,
        job: ProcessingJob,
        stage: JobStage,
    ) -> ProcessingJob:
        job.stage = stage
        await self.session.flush()
        await self.session.commit()
        return job

    async def set_celery_task_id(
        self,
        job: ProcessingJob,
        celery_task_id: str,
    ) -> ProcessingJob:
        job.celery_task_id = celery_task_id
        await self.session.flush()
        return job
