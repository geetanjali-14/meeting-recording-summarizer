import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_settings_instantiation() -> None:
    settings = Settings(_env_file=None)
    assert settings.APP_NAME == "Meeting Intelligence Summarizer"
    assert settings.PORT == 8000
    assert settings.HOST == "0.0.0.0"
    assert settings.APP_ENV == "development"
    assert settings.CELERY_TASK_ACKS_LATE is True
    assert settings.CELERY_TASK_REJECT_ON_WORKER_LOST is True


def test_database_url_validation_rejects_non_postgres() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="sqlite:///./test.db")


def test_database_url_validation_accepts_postgres() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/dbname",
    )
    assert "postgresql+psycopg://" in settings.DATABASE_URL


def test_production_mode_rejects_localhost_db() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL cannot use localhost in production"):
        Settings(
            APP_ENV="production",
            DEBUG=False,
            DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/dbname",
            STORAGE_ACCESS_KEY_ID="valid_key",
            STORAGE_SECRET_ACCESS_KEY="valid_secret",
            LLM_API_KEY="valid_key",
        )


def test_repr_masks_secrets() -> None:
    settings = Settings(
        STORAGE_SECRET_ACCESS_KEY="super_secret_value",
        LLM_API_KEY="secret_llm_key",
    )
    settings_repr = repr(settings)
    assert "super_secret_value" not in settings_repr
    assert "secret_llm_key" not in settings_repr
