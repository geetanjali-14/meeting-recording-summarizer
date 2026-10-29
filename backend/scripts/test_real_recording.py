# ruff: noqa: E402, E501
#!/usr/bin/env python3
"""CLI utility to safely test the complete audio processing pipeline on real recordings.

Features:
1. Safe database isolation: Defaults to your local docker Postgres container
   (postgresql+psycopg://postgres:postgres@localhost:5432/meeting_summarizer)
   so your remote Supabase database remains completely untouched.
2. Supports processing either a full recording or a custom-duration snippet.
3. Automatically cleans up test records unless `--preserve-db` is specified.
4. Uses real Groq Whisper Large V3 Turbo and real Groq LLM intelligence extraction.
5. Displays audio format, chunk counts, payload byte sizes, duration, transcripts, and analysis.

Usage:
    # Test a 2-minute snippet of the 42-minute meeting:
    ./.venv/bin/python scripts/test_real_recording.py \
        --input "/home/rails/Downloads/Product Team Meeting - 2019-07-09.mp4" \
        --duration 120

    # Test the complete full recording:
    ./.venv/bin/python scripts/test_real_recording.py \
        --input "/home/rails/Downloads/Product Team Meeting - 2019-07-09.mp4"
"""

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.meeting_analysis_agent import MeetingAnalysisAgent
from app.agents.verification_agent import VerificationAgent
from app.core.config import get_settings
from app.models.meeting import Meeting, MeetingStatus
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.recording import Recording, RecordingStatus
from app.models.user import User
from app.providers.diarization.mock_diarization_provider import MockDiarizationProvider
from app.providers.llm.groq_provider import GroqProvider
from app.providers.storage.base import StorageProvider
from app.providers.transcription.groq_whisper_provider import GroqWhisperProvider
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.job_repository import JobRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.recording_repository import RecordingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.alignment_service import AlignmentService
from app.services.analysis_service import AnalysisService
from app.services.audio_service import AudioService
from app.services.diarization_service import DiarizationService
from app.services.processing_service import ProcessingService
from app.workers.job_lease import JobLeaseTracker


class LocalDiskStorageProvider(StorageProvider):
    """Storage provider reading directly from local filesystem for isolated tests."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def generate_presigned_upload_url(
        self, storage_key: str, content_type: str, expires_in_seconds: int = 900
    ) -> str:
        return "https://mock"

    def generate_presigned_download_url(
        self, storage_key: str, expires_in_seconds: int = 3600
    ) -> str:
        return "https://mock"

    def delete_object(self, storage_key: str) -> None:
        pass

    def object_exists(self, storage_key: str) -> bool:
        return True

    def download_file(self, storage_key: str, destination_path: str) -> None:
        import shutil

        shutil.copyfile(self.file_path, destination_path)


async def main():
    parser = argparse.ArgumentParser(
        description="Test processing pipeline on real audio/video recordings."
    )
    parser.add_argument(
        "--input", required=True, help="Path to real recording file (MP4, MP3, WAV, etc.)"
    )
    parser.add_argument(
        "--start", type=float, default=0.0, help="Start offset in seconds (default: 0)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Snippet duration in seconds (default: full file)",
    )
    parser.add_argument(
        "--db-url",
        default="postgresql+psycopg://postgres:postgrespassword@localhost:5432/meeting_summarizer",
        help="Database URL to use (default: isolated local Docker Postgres)",
    )
    parser.add_argument(
        "--preserve-db",
        action="store_true",
        help="Preserve test records in DB instead of deleting them",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=float,
        default=300.0,
        help="Target chunk duration in seconds (default: 300)",
    )

    args = parser.parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Error: File does not exist: {input_path}")
        sys.exit(1)

    print("=" * 70)
    print("REAL RECORDING PIPELINE TESTER")
    print("=" * 70)
    print(
        f"📁 Input File:   {input_path.name} ({input_path.stat().st_size / (1024 * 1024):.2f} MB)"
    )
    print(f"🗄️ Database:     {args.db_url}")

    audio_service = AudioService()
    media_info = audio_service.validate_media_file(input_path)
    total_file_duration = media_info.get("duration") or 0.0
    print(f"⏱️ Total Duration: {total_file_duration:.1f}s ({total_file_duration / 60:.1f} minutes)")

    # Prepare temporary test source (either snippet or full file)
    with audio_service.temporary_scratch_dir(prefix="real_test_source_") as scratch_dir:
        if args.duration is not None and args.duration < total_file_duration:
            print(f"✂️ Extracting {args.duration}s snippet starting at {args.start}s...")
            test_source = scratch_dir / f"snippet_{input_path.name}"
            audio_service.extract_audio_segment(
                input_path=input_path,
                output_path=test_source,
                start_seconds=args.start,
                duration_seconds=args.duration,
            )
        else:
            test_source = input_path

        test_size = test_source.stat().st_size
        print(f"🎯 Target Media: {test_source.name} ({test_size / (1024 * 1024):.2f} MB)")

        # Create isolated database engine
        engine = create_async_engine(args.db_url, echo=False)
        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        async with session_factory() as session:
            user_id = uuid.uuid4()
            user = User(
                id=user_id,
                email=f"realtest_{uuid.uuid4().hex[:6]}@example.com",
                display_name="Pipeline Tester",
            )
            session.add(user)
            await session.flush()

            meeting_id = uuid.uuid4()
            meeting = Meeting(
                id=meeting_id,
                user_id=user_id,
                title=f"Test: {input_path.name}",
                status=MeetingStatus.ACTIVE,
            )
            session.add(meeting)
            await session.flush()

            recording_id = uuid.uuid4()
            recording = Recording(
                id=recording_id,
                meeting_id=meeting_id,
                user_id=user_id,
                storage_key=f"recordings/{test_source.name}",
                original_filename=test_source.name,
                content_type="video/mp4" if test_source.suffix.lower() == ".mp4" else "audio/mpeg",
                file_size_bytes=test_size,
                status=RecordingStatus.UPLOADED,
            )
            session.add(recording)
            await session.flush()

            job_id = uuid.uuid4()
            job = ProcessingJob(
                id=job_id,
                meeting_id=meeting_id,
                user_id=user_id,
                status=JobStatus.PENDING,
                stage=JobStage.CREATED,
            )
            session.add(job)
            await session.commit()
            print(f"✅ Created isolated test job: {job_id}")

        settings = get_settings()
        whisper_provider = GroqWhisperProvider(settings, audio_service=audio_service)
        whisper_provider.CHUNK_DURATION_SECONDS = args.chunk_seconds
        whisper_provider.CHUNK_OVERLAP_SECONDS = 2.0

        diarization_provider = MockDiarizationProvider()
        diarization_service = DiarizationService(diarization_provider, settings)
        alignment_service = AlignmentService()

        llm_provider = GroqProvider(settings)
        analysis_agent = MeetingAnalysisAgent(llm_provider, settings)
        verification_agent = VerificationAgent(llm_provider, settings)

        storage_provider = LocalDiskStorageProvider(str(test_source))

        async with session_factory() as session:
            job_repo = JobRepository(session)
            meeting_repo = MeetingRepository(session)
            recording_repo = RecordingRepository(session)
            transcript_repo = TranscriptRepository(session)
            analysis_repo = AnalysisRepository(session)

            analysis_service = AnalysisService(
                analysis_repo=analysis_repo,
                analysis_agent=analysis_agent,
                verification_agent=verification_agent,
                settings=settings,
            )

            lease_tracker = JobLeaseTracker(session, lease_duration_seconds=300)

            service = ProcessingService(
                job_repo=job_repo,
                meeting_repo=meeting_repo,
                recording_repo=recording_repo,
                transcript_repo=transcript_repo,
                storage_provider=storage_provider,
                audio_service=audio_service,
                transcription_provider=whisper_provider,
                settings=settings,
                diarization_service=diarization_service,
                alignment_service=alignment_service,
                analysis_service=analysis_service,
            )

            print("\n🚀 Executing complete pipeline stages...")
            t0 = time.time()
            completed_job = await service.execute_job(
                job_id=job_id,
                meeting_id=meeting_id,
                worker_id="cli_real_tester",
                lease_tracker=lease_tracker,
            )
            elapsed = time.time() - t0
            print(
                f"🎉 Pipeline finished in {elapsed:.2f}s! Status: {completed_job.status}, Stage: {completed_job.stage}\n"
            )

            # Inspect persisted transcript
            transcript = await transcript_repo.get_by_meeting_id(
                meeting_id=meeting_id, user_id=user_id
            )
            segments = await transcript_repo.get_segments_by_transcript(transcript.id)
            print(f"📝 Transcript: {len(segments)} segments, Language: {transcript.language}")
            print("-" * 50)
            for seg in segments[:8]:
                print(
                    f"  [{seg.start_time:6.2f}s - {seg.end_time:6.2f}s] {seg.speaker_label}: {seg.text}"
                )
            if len(segments) > 8:
                print(f"  ... ({len(segments) - 8} more segments)")

            # Inspect analysis
            analysis = await analysis_repo.get_by_meeting_id(meeting_id=meeting_id, user_id=user_id)
            print("-" * 50)
            print("🧠 Meeting Intelligence Summary:")
            print(analysis.executive_summary)

            # Cleanup
            if not args.preserve_db:
                m = await meeting_repo.get_by_id_system(meeting_id)
                if m:
                    await session.delete(m)
                u = await session.get(User, user_id)
                if u:
                    await session.delete(u)
                await session.commit()
                print("\n🧹 Cleaned up temporary test records from isolated database.")
            else:
                print(f"\n💾 Preserved test records in DB for inspection. Meeting ID: {meeting_id}")

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
