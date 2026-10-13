import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from app.services.audio_service import AudioProcessingError, AudioService
from tests.security.test_tenant_isolation import create_token


def test_oversized_upload_payload_rejected() -> None:
    app = create_app()
    test_settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS="test-secret",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    client = TestClient(app)

    token = create_token(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}"}

    # 524,288,001 bytes (> 500 MB limit)
    res = client.post(
        "/api/v1/meetings",
        json={
            "title": "Huge File Attack",
            "filename": "huge.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 524_288_001,
        },
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_disallowed_content_types_rejected() -> None:
    app = create_app()
    test_settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS="test-secret",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    client = TestClient(app)

    token = create_token(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}"}

    disallowed_types = [
        "application/zip",
        "application/x-sh",
        "text/html",
        "image/png",
        "application/octet-stream",
    ]

    for mime in disallowed_types:
        res = client.post(
            "/api/v1/meetings",
            json={
                "title": f"Disallowed {mime}",
                "filename": "payload.bin",
                "content_type": mime,
                "file_size_bytes": 1024,
            },
            headers=headers,
        )
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_audio_service_polyglot_and_corrupted_file_validation(tmp_path: Path) -> None:
    audio_service = AudioService()

    # 1. Zero-byte file
    empty_file = tmp_path / "empty.wav"
    empty_file.write_bytes(b"")
    with pytest.raises(AudioProcessingError, match="empty"):
        audio_service.validate_media_file(empty_file)

    # 2. Corrupted file / non-media polyglot (text disguised as mp3)
    fake_audio = tmp_path / "fake.mp3"
    fake_audio.write_bytes(b"MZ\x90\x00This is not valid audio data.")
    with pytest.raises(AudioProcessingError):
        audio_service.validate_media_file(fake_audio)

