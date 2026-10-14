import uuid
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.deps import get_export_service
from app.core.config import Settings, get_settings
from app.main import create_app
from app.schemas.export import ExportFormat, ExportResponse
from app.services.export_service import ExportService
from tests.security.test_tenant_isolation import create_token


def test_exports_api_end_to_end_and_tenant_isolation() -> None:
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    meeting_id = uuid.uuid4()

    app = create_app()
    test_settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS="test-secret",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings

    mock_export_service = AsyncMock(spec=ExportService)

    async def mock_export(*args, **kwargs):
        user_id_arg = kwargs.get("user_id")
        export_format = kwargs.get("export_format")
        if user_id_arg != user_a_id:
            raise ValueError("Meeting not found")
        if export_format == ExportFormat.MARKDOWN:
            return ExportResponse(
                meeting_id=meeting_id,
                format="markdown",
                filename="Production_Readiness_Sync_analysis.md",
                content_type="text/markdown; charset=utf-8",
                content=(
                    "# Production Readiness Sync\n\n"
                    "- Enable Gzip compression on static assets\n"
                    "- Owner: DevOps Lead"
                ),
            )
        else:
            return ExportResponse(
                meeting_id=meeting_id,
                format="json",
                filename="Production_Readiness_Sync_analysis.json",
                content_type="application/json; charset=utf-8",
                content=(
                    '{"decisions": ["Enable Gzip compression"], '
                    '"action_items": [{"action": "Cloudflare edge cache rules"}]}'
                ),
            )

    mock_export_service.export_meeting.side_effect = mock_export
    app.dependency_overrides[get_export_service] = lambda: mock_export_service

    client = TestClient(app)

    token_a = create_token(user_a_id)
    token_b = create_token(user_b_id)

    # 1. User B cannot export User A's meeting -> 404 Not Found (Tenant Isolation)
    res_b = client.post(
        f"/api/v1/meetings/{meeting_id}/exports",
        json={"format": "markdown"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 404
    assert res_b.json()["error"]["code"] == "NOT_FOUND"

    # 2. User A exports as Markdown -> 200 OK
    res_a_md = client.post(
        f"/api/v1/meetings/{meeting_id}/exports",
        json={"format": "markdown"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a_md.status_code == 200
    md_data = res_a_md.json()["data"]
    assert md_data["format"] == "markdown"
    assert "Production_Readiness_Sync_analysis.md" in md_data["filename"]
    assert "text/markdown" in md_data["content_type"]
    assert "# Production Readiness Sync" in md_data["content"]
    assert "Enable Gzip compression on static assets" in md_data["content"]
    assert "DevOps Lead" in md_data["content"]

    # 3. User A exports as JSON -> 200 OK
    res_a_json = client.post(
        f"/api/v1/meetings/{meeting_id}/exports",
        json={"format": "json"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a_json.status_code == 200
    json_data = res_a_json.json()["data"]
    assert json_data["format"] == "json"
    assert "application/json" in json_data["content_type"]
    assert "Production_Readiness_Sync_analysis.json" in json_data["filename"]
    assert "Cloudflare edge cache rules" in json_data["content"]
