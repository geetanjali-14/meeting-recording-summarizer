import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.workers.job_lease import JobLeaseTracker


@pytest.mark.asyncio
async def test_job_lease_claim_and_release() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.PENDING,
        stage=JobStage.CREATED,
        attempt=0,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = job
    session.execute.return_value = mock_result

    tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    worker_id = "test-worker-1"

    # 1. Claim job
    claimed = await tracker.claim_job(job_id=job_id, worker_id=worker_id)
    assert claimed is not None
    assert claimed.status == JobStatus.RUNNING
    assert claimed.stage == JobStage.VALIDATING
    assert claimed.worker_id == worker_id
    assert claimed.attempt == 1
    assert claimed.lease_expires_at is not None
    session.flush.assert_awaited()

    # 2. Renew heartbeat
    renewed = await tracker.renew_heartbeat(job_id=job_id, worker_id=worker_id)
    assert renewed is True

    # 3. Release lease
    released = await tracker.release_lease(
        job_id=job_id,
        worker_id=worker_id,
        target_status=JobStatus.COMPLETED,
        target_stage=JobStage.COMPLETED,
    )
    assert released is not None
    assert released.status == JobStatus.COMPLETED
    assert released.stage == JobStage.COMPLETED
    assert released.lease_expires_at is None
    assert released.completed_at is not None


@pytest.mark.asyncio
async def test_job_lease_stale_recovery() -> None:
    session = AsyncMock()
    user_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # Expired lease
    expired_time = datetime.now(UTC) - timedelta(minutes=5)
    stale_job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        user_id=user_id,
        status=JobStatus.RUNNING,
        stage=JobStage.TRANSCRIBING,
        worker_id="crashed-worker",
        lease_expires_at=expired_time,
        attempt=1,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stale_job
    session.execute.return_value = mock_result

    tracker = JobLeaseTracker(session, lease_duration_seconds=120)
    new_worker = "healthy-worker-2"

    claimed = await tracker.claim_job(job_id=job_id, worker_id=new_worker)
    assert claimed is not None
    assert claimed.worker_id == new_worker
    assert claimed.status == JobStatus.RUNNING
    assert claimed.attempt == 2
    assert claimed.lease_expires_at is not None
    assert claimed.lease_expires_at > datetime.now(UTC)
