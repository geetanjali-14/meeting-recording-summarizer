import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_analysis_repository,
    get_chat_repository,
    get_meeting_service,
    get_optional_current_user,
    get_transcript_repository,
)
from app.core.security import UserContext
from app.main import create_app
from app.models.meeting import Meeting, MeetingStatus
from app.models.meeting_analysis import Decision, MeetingAnalysis
from app.models.processing_job import JobStage, JobStatus, ProcessingJob
from app.models.transcript import Transcript, TranscriptSegment
from app.services.meeting_service import MeetingService


@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_user_context(test_user_id: uuid.UUID) -> UserContext:
    return UserContext(
        user_id=test_user_id,
        email="developer@example.com",
        claims={"sub": str(test_user_id)},
    )


def test_home_page_renders_unauthenticated() -> None:
    """Verifies that the home page renders public marketing content when unauthenticated."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    assert "Turn Meeting Recordings into" in response.text
    assert "Sign in to Get Started" in response.text


def test_home_page_renders_authenticated(mock_user_context: UserContext) -> None:
    """Verifies home page displays user email and dashboard links when authenticated."""
    app = create_app()
    app.dependency_overrides[get_optional_current_user] = lambda: mock_user_context
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "developer@example.com" in response.text
    assert "View Dashboard" in response.text


def test_login_page_renders_unauthenticated() -> None:
    """Verifies login page renders OTP form when unauthenticated."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in to your account" in response.text
    assert "Send verification code" in response.text


def test_login_page_redirects_if_authenticated(mock_user_context: UserContext) -> None:
    """Verifies login page redirects directly to dashboard if already authenticated."""
    app = create_app()
    app.dependency_overrides[get_optional_current_user] = lambda: mock_user_context
    client = TestClient(app)

    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"] == "/dashboard"


def test_dashboard_redirects_unauthenticated() -> None:
    """Verifies that accessing dashboard without auth redirects to /login."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_dashboard_renders_with_meetings(
    mock_user_context: UserContext, test_user_id: uuid.UUID
) -> None:
    """Verifies dashboard renders meetings table for authenticated owner."""
    app = create_app()
    app.dependency_overrides[get_optional_current_user] = lambda: mock_user_context

    mock_service = MagicMock(spec=MeetingService)
    meeting_id = uuid.uuid4()
    mock_meeting = Meeting(
        id=meeting_id,
        user_id=test_user_id,
        title="Weekly Sprint Planning",
        meeting_date=datetime.date(2026, 10, 28),
        status=MeetingStatus.ACTIVE,
    )
    mock_service.list_meetings = AsyncMock(return_value=([mock_meeting], 1))
    app.dependency_overrides[get_meeting_service] = lambda: mock_service

    client = TestClient(app)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Weekly Sprint Planning" in response.text
    assert f"/meetings/{meeting_id}" in response.text


def test_new_meeting_page_redirects_unauthenticated() -> None:
    """Verifies /meetings/new redirects to login when unauthenticated."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/meetings/new", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_new_meeting_page_renders_dropzone(mock_user_context: UserContext) -> None:
    """Verifies /meetings/new renders upload form and dropzone when authenticated."""
    app = create_app()
    app.dependency_overrides[get_optional_current_user] = lambda: mock_user_context
    client = TestClient(app)

    response = client.get("/meetings/new")
    assert response.status_code == 200
    assert "Upload New Meeting" in response.text
    assert "Start Processing Meeting" in response.text


def test_meeting_detail_page_completed_flow(
    mock_user_context: UserContext, test_user_id: uuid.UUID
) -> None:
    """Verifies completed meeting detail view renders transcript segments and intelligence."""
    app = create_app()
    app.dependency_overrides[get_optional_current_user] = lambda: mock_user_context

    meeting_id = uuid.uuid4()
    job_id = uuid.uuid4()
    transcript_id = uuid.uuid4()

    mock_job = ProcessingJob(
        id=job_id,
        meeting_id=meeting_id,
        status=JobStatus.COMPLETED,
        stage=JobStage.SAVING,
    )
    mock_meeting = Meeting(
        id=meeting_id,
        user_id=test_user_id,
        title="Architectural Review",
        meeting_date=datetime.date(2026, 10, 28),
        status=MeetingStatus.ACTIVE,
        job=mock_job,
    )

    mock_service = MagicMock(spec=MeetingService)
    mock_service.get_meeting_details = AsyncMock(return_value=mock_meeting)
    app.dependency_overrides[get_meeting_service] = lambda: mock_service

    mock_transcript_repo = MagicMock()
    mock_transcript = Transcript(
        id=transcript_id,
        meeting_id=meeting_id,
        user_id=test_user_id,
        language="en",
    )
    mock_transcript_repo.get_by_meeting_id = AsyncMock(return_value=mock_transcript)
    mock_seg = TranscriptSegment(
        id=uuid.uuid4(),
        transcript_id=transcript_id,
        sequence_index=0,
        start_time=0.0,
        end_time=12.5,
        speaker_label="SPEAKER_00",
        speaker="Lead Engineer",
        text="We are migrating the Next.js frontend to Python Jinja2 templates.",
    )
    mock_transcript_repo.get_segments_by_transcript = AsyncMock(return_value=[mock_seg])
    app.dependency_overrides[get_transcript_repository] = lambda: mock_transcript_repo

    mock_analysis_repo = MagicMock()
    mock_analysis = MeetingAnalysis(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=test_user_id,
        executive_summary="The team successfully designed and implemented the migration.",
        model="llama-3.3-70b-versatile",
    )
    mock_decision = Decision(
        id=uuid.uuid4(),
        sequence_index=0,
        decision_text="Migrate frontend to server-rendered Jinja2 templates",
        evidence_segment_ids=[str(mock_seg.id)],
    )
    mock_analysis.decisions = [mock_decision]
    mock_analysis.action_items = []
    mock_analysis.topics = []
    mock_analysis.risks = []
    mock_analysis.open_questions = []
    mock_analysis_repo.get_by_meeting_id = AsyncMock(return_value=mock_analysis)
    app.dependency_overrides[get_analysis_repository] = lambda: mock_analysis_repo

    mock_chat_repo = MagicMock()
    mock_chat_repo.get_messages_by_meeting = AsyncMock(return_value=[])
    app.dependency_overrides[get_chat_repository] = lambda: mock_chat_repo

    client = TestClient(app)
    response = client.get(f"/meetings/{meeting_id}")
    assert response.status_code == 200
    assert "Architectural Review" in response.text
    assert "We are migrating the Next.js frontend to Python Jinja2 templates." in response.text
    assert "The team successfully designed and implemented the migration." in response.text
    assert "Summary" in response.text


def test_auth_logout_clears_cookie() -> None:
    """Verifies that POST /auth/logout clears the access_token cookie."""
    app = create_app()
    client = TestClient(app)

    response = client.post("/auth/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["Location"] == "/"
    # Check that Set-Cookie expires or deletes the access_token
    cookie_header = response.headers.get("set-cookie", "")
    assert 'access_token=""' in cookie_header or "Max-Age=0" in cookie_header


def test_static_css_assets_served() -> None:
    """Verifies that static assets (e.g. styles.css) are served correctly by FastAPI."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/static/css/styles.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["Content-Type"]
    assert "--primary" in response.text


def test_create_auth_session_with_valid_jwt() -> None:
    """Verifies POST /auth/session validates token and sets HttpOnly SameSite cookie."""
    app = create_app()
    client = TestClient(app)

    valid_token = "valid-jwt-token"
    test_user = uuid.uuid4()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.api.web.verify_jwt_token",
            AsyncMock(
                return_value=UserContext(
                    user_id=test_user, email="user@example.com", claims={"sub": str(test_user)}
                )
            ),
        )
        response = client.post("/auth/session", json={"access_token": valid_token})
        assert response.status_code == 200
        assert response.json()["status"] == "session_created"
        cookie_header = response.headers.get("set-cookie", "")
        assert "access_token=valid-jwt-token" in cookie_header
        assert "HttpOnly" in cookie_header
        assert "SameSite=lax" in cookie_header or "samesite=lax" in cookie_header


def test_create_auth_session_rejects_invalid_jwt() -> None:
    """Verifies POST /auth/session rejects unverified JWT tokens with 401."""
    from app.core.security import SecurityError

    app = create_app()
    client = TestClient(app)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.api.web.verify_jwt_token",
            AsyncMock(side_effect=SecurityError("Token signature invalid")),
        )
        response = client.post("/auth/session", json={"access_token": "malicious-tampered-token"})
        assert response.status_code == 401
        assert "set-cookie" not in response.headers


def test_xss_escaping_in_meeting_detail(
    mock_user_context: UserContext, test_user_id: uuid.UUID
) -> None:
    """Verifies that user-provided titles, transcript text, and rationales are HTML-escaped."""
    app = create_app()
    app.dependency_overrides[get_optional_current_user] = lambda: mock_user_context

    meeting_id = uuid.uuid4()
    mock_meeting = Meeting(
        id=meeting_id,
        user_id=test_user_id,
        title="<script>alert('xss-title')</script>",
        meeting_date=datetime.date(2026, 10, 28),
        status=MeetingStatus.ACTIVE,
        job=ProcessingJob(id=uuid.uuid4(), meeting_id=meeting_id, status=JobStatus.COMPLETED),
    )

    mock_service = MagicMock(spec=MeetingService)
    mock_service.get_meeting_details = AsyncMock(return_value=mock_meeting)
    app.dependency_overrides[get_meeting_service] = lambda: mock_service

    mock_transcript_repo = MagicMock()
    mock_transcript_repo.get_by_meeting_id = AsyncMock(return_value=None)
    app.dependency_overrides[get_transcript_repository] = lambda: mock_transcript_repo

    mock_analysis_repo = MagicMock()
    mock_analysis = MeetingAnalysis(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        user_id=test_user_id,
        executive_summary="<img src=x onerror=alert('xss-summary')>",
        model="groq-llama",
    )
    mock_analysis.decisions = []
    mock_analysis.action_items = []
    mock_analysis.topics = []
    mock_analysis.risks = []
    mock_analysis.open_questions = []
    mock_analysis_repo.get_by_meeting_id = AsyncMock(return_value=mock_analysis)
    app.dependency_overrides[get_analysis_repository] = lambda: mock_analysis_repo

    mock_chat_repo = MagicMock()
    mock_chat_repo.get_messages_by_meeting = AsyncMock(return_value=[])
    app.dependency_overrides[get_chat_repository] = lambda: mock_chat_repo

    client = TestClient(app)
    response = client.get(f"/meetings/{meeting_id}")
    assert response.status_code == 200
    # Must NOT contain raw unescaped script tag or onerror handler
    assert "<script>alert('xss-title')</script>" not in response.text
    assert "&lt;script&gt;alert(" in response.text
    assert "&lt;img src=x onerror=" in response.text


def test_csrf_cookie_mutation_rejected_from_cross_origin() -> None:
    """Verifies state-changing mutation with cookie auth is rejected when origin is untrusted."""
    app = create_app()
    test_user = uuid.uuid4()
    mock_ctx = UserContext(
        user_id=test_user, email="user@example.com", claims={"sub": str(test_user)}
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.api.deps.verify_jwt_token",
            AsyncMock(return_value=mock_ctx),
        )
        client = TestClient(app)
        client.cookies.set("access_token", "valid-test-cookie")

        # Untrusted cross-origin POST to state-changing API
        response = client.post(
            "/api/v1/meetings",
            headers={"Origin": "https://evil-attacker-site.com"},
            json={
                "title": "Malicious Meeting",
                "meeting_date": "2026-10-28",
                "filename": "audio.mp3",
                "content_type": "audio/mpeg",
                "file_size_bytes": 1024,
            },
        )
        assert response.status_code == 403
        assert "Cross-site request validation failed" in response.text


def test_csrf_cookie_mutation_accepted_from_same_origin() -> None:
    """Verifies state-changing mutation with cookie auth succeeds when Origin matches Host."""
    app = create_app()
    test_user = uuid.uuid4()
    mock_ctx = UserContext(
        user_id=test_user, email="user@example.com", claims={"sub": str(test_user)}
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.api.deps.verify_jwt_token",
            AsyncMock(return_value=mock_ctx),
        )
        # Mock upload service so we don't need real R2 or DB
        mock_upload = MagicMock()
        mock_upload.initiate_meeting_upload = AsyncMock(
            return_value=(
                MagicMock(id=uuid.uuid4(), status=MagicMock(value="CREATED")),
                MagicMock(id=uuid.uuid4()),
                "https://r2.example.com/put",
                "upload-token-abc",
                900,
            )
        )
        from app.api.deps import get_upload_service

        app.dependency_overrides[get_upload_service] = lambda: mock_upload

        client = TestClient(app)
        client.cookies.set("access_token", "valid-test-cookie")

        # Legitimate same-origin POST
        response = client.post(
            "/api/v1/meetings",
            headers={"Host": "localhost:8000", "Origin": "http://localhost:8000"},
            json={
                "title": "Legitimate Meeting",
                "meeting_date": "2026-10-28",
                "filename": "audio.mp3",
                "content_type": "audio/mpeg",
                "file_size_bytes": 1024,
            },
        )
        assert response.status_code == 201


def test_csrf_bearer_token_unaffected_by_cross_origin() -> None:
    """Verifies API clients using Bearer tokens are not blocked by CSRF origin checks."""
    app = create_app()
    test_user = uuid.uuid4()
    mock_ctx = UserContext(
        user_id=test_user, email="user@example.com", claims={"sub": str(test_user)}
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.api.deps.verify_jwt_token",
            AsyncMock(return_value=mock_ctx),
        )
        mock_upload = MagicMock()
        mock_upload.initiate_meeting_upload = AsyncMock(
            return_value=(
                MagicMock(id=uuid.uuid4(), status=MagicMock(value="CREATED")),
                MagicMock(id=uuid.uuid4()),
                "https://r2.example.com/put",
                "upload-token-abc",
                900,
            )
        )
        from app.api.deps import get_upload_service

        app.dependency_overrides[get_upload_service] = lambda: mock_upload

        client = TestClient(app)

        # External client with Authorization: Bearer header
        response = client.post(
            "/api/v1/meetings",
            headers={
                "Authorization": "Bearer programmatic-api-key",
                "Origin": "https://mobile-app.example.com",
            },
            json={
                "title": "Bearer API Meeting",
                "meeting_date": "2026-10-28",
                "filename": "audio.mp3",
                "content_type": "audio/mpeg",
                "file_size_bytes": 1024,
            },
        )
        assert response.status_code == 201
