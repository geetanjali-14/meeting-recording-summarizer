import logging
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from pydantic import BaseModel

from app.api.deps import (
    get_analysis_repository,
    get_chat_repository,
    get_meeting_service,
    get_optional_current_user,
    get_storage_provider,
    get_transcript_repository,
)
from app.core.config import get_settings
from app.core.security import SecurityError, UserContext, verify_jwt_token
from app.models.chat import ChatMessage
from app.models.meeting_analysis import MeetingAnalysis
from app.models.processing_job import JobStatus
from app.models.transcript import TranscriptSegment
from app.providers.storage.base import StorageProvider
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.meeting_service import MeetingNotFoundError, MeetingService

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Markdown renderer configured for Github Flavored Markdown (tables, lists, strikethrough)
_md_renderer = MarkdownIt("gfm-like", {"linkify": False, "html": False})


def render_markdown_filter(text: str | None) -> str:
    """Jinja filter to safely convert Markdown into clean HTML."""
    if not text:
        return ""
    return _md_renderer.render(text)


templates.env.filters["markdown"] = render_markdown_filter

web_router = APIRouter(include_in_schema=False)


class SessionRequest(BaseModel):
    access_token: str


@web_router.post("/auth/session")
async def create_auth_session(
    payload: SessionRequest,
    response: Response,
) -> JSONResponse:
    """Stores verified Supabase access token in an HttpOnly, SameSite cookie."""
    settings = get_settings()
    try:
        # Validate token first before setting session cookie
        user_ctx = await verify_jwt_token(token=payload.access_token, settings=settings)
    except SecurityError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {err.message}",
        ) from err

    is_production = settings.APP_ENV.lower() == "production"

    response = JSONResponse({"status": "session_created", "user_id": str(user_ctx.user_id)})
    response.set_cookie(
        key="access_token",
        value=payload.access_token,
        httponly=True,
        samesite="lax",
        secure=is_production,
        max_age=3600 * 24 * 7,  # 7 days
        path="/",
    )
    return response


@web_router.post("/auth/logout")
async def logout(response: Response) -> RedirectResponse:
    """Clears session cookie and redirects user to landing page."""
    redirect_resp = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    redirect_resp.delete_cookie(key="access_token", path="/")
    return redirect_resp


@web_router.get("/", response_class=HTMLResponse)
async def home_page(
    request: Request,
    current_user: Annotated[UserContext | None, Depends(get_optional_current_user)],
) -> Response:
    """Renders product landing page."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current_user": current_user,
            "active_page": "home",
        },
    )


@web_router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    current_user: Annotated[UserContext | None, Depends(get_optional_current_user)],
) -> Response:
    """Renders passwordless OTP sign-in page."""
    if current_user is not None:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "current_user": None,
            "active_page": "login",
            "supabase_url": settings.SUPABASE_URL,
            "supabase_anon_key": settings.SUPABASE_ANON_KEY,
        },
    )


@web_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    current_user: Annotated[UserContext | None, Depends(get_optional_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
) -> Response:
    """Renders authenticated user dashboard."""
    if current_user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    meetings, _ = await meeting_service.list_meetings(
        user_id=current_user.user_id,
        page=1,
        per_page=50,
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "current_user": current_user,
            "active_page": "dashboard",
            "meetings": meetings,
        },
    )


@web_router.get("/meetings/new", response_class=HTMLResponse)
async def new_meeting_page(
    request: Request,
    current_user: Annotated[UserContext | None, Depends(get_optional_current_user)],
) -> Response:
    """Renders meeting upload dropzone screen."""
    if current_user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request=request,
        name="meetings_new.html",
        context={
            "current_user": current_user,
            "active_page": "new_meeting",
        },
    )


@web_router.get("/meetings/{meeting_id}", response_class=HTMLResponse)
async def meeting_detail_page(
    meeting_id: uuid.UUID,
    request: Request,
    current_user: Annotated[UserContext | None, Depends(get_optional_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
    transcript_repo: Annotated[TranscriptRepository, Depends(get_transcript_repository)],
    analysis_repo: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    chat_repo: Annotated[ChatRepository, Depends(get_chat_repository)],
    storage_provider: Annotated[StorageProvider, Depends(get_storage_provider)],
) -> Response:
    """Renders meeting detail view with processing state, transcript, and intelligence."""
    if current_user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    try:
        meeting = await meeting_service.get_meeting_details(
            meeting_id=meeting_id,
            user_id=current_user.user_id,
        )
    except MeetingNotFoundError:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    is_completed = bool(meeting.job and meeting.job.status == JobStatus.COMPLETED)
    is_failed = bool(meeting.job and meeting.job.status in (JobStatus.FAILED, JobStatus.CANCELLED))

    segments: Sequence[TranscriptSegment] = []
    analysis: MeetingAnalysis | None = None
    chat_messages: Sequence[ChatMessage] = []
    recording_stream_url: str | None = None
    is_video_recording: bool = False

    if meeting.recording and meeting.recording.storage_key:
        try:
            recording_stream_url = storage_provider.generate_presigned_download_url(
                storage_key=meeting.recording.storage_key,
                expires_in_seconds=3600,
            )
            content_type = (meeting.recording.content_type or "").lower()
            filename = (meeting.recording.original_filename or "").lower()
            is_video_recording = content_type.startswith("video/") or filename.endswith(
                (".mp4", ".mov", ".webm", ".mkv", ".avi")
            )
        except Exception:
            logger.warning("Failed to generate presigned media URL for meeting %s", meeting_id)

    if is_completed:
        transcript = await transcript_repo.get_by_meeting_id(
            meeting_id=meeting_id, user_id=current_user.user_id
        )
        if transcript:
            segments = await transcript_repo.get_segments_by_transcript(transcript_id=transcript.id)

        analysis = await analysis_repo.get_by_meeting_id(
            meeting_id=meeting_id,
            user_id=current_user.user_id,
            include_children=True,
        )

        chat_messages = await chat_repo.get_messages_by_meeting(
            meeting_id=meeting_id, user_id=current_user.user_id
        )

    return templates.TemplateResponse(
        request=request,
        name="meeting_detail.html",
        context={
            "current_user": current_user,
            "meeting": meeting,
            "is_completed": is_completed,
            "is_failed": is_failed,
            "segments": segments,
            "analysis": analysis,
            "chat_messages": chat_messages,
            "recording_stream_url": recording_stream_url,
            "is_video_recording": is_video_recording,
        },
    )
