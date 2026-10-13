from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized, typed application configuration.

    Enforces validation on all settings loaded from environment variables
    or .env files. Sensitive credentials are obfuscated in string representations.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Core Application
    APP_NAME: str = "Meeting Intelligence Summarizer"
    APP_ENV: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = False
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # 2. Database (PostgreSQL - Mandatory from Day One)
    DATABASE_URL: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/meeting_summarizer",
        description="PostgreSQL connection string with psycopg driver",
    )
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT_SECONDS: int = 30
    DATABASE_POOL_RECYCLE_SECONDS: int = 1800

    # 3. Authentication (Supabase Auth / JWT Verification)
    SUPABASE_URL: str = "https://example-project.supabase.co"
    SUPABASE_ANON_KEY: str = "placeholder-anon-key"
    JWT_ISSUER: str = "https://example-project.supabase.co/auth/v1"
    JWT_AUDIENCE: str = "authenticated"
    JWT_ALGORITHMS: list[str] = ["HS256", "RS256"]
    JWT_SIGNING_KEY_OR_JWKS: str = "dev-insecure-secret-key-change-in-production"
    JWKS_CACHE_TTL_SECONDS: int = 300

    # 4. Object Storage (Cloudflare R2 / S3 Compatible)
    STORAGE_PROVIDER: Literal["r2", "s3", "mock"] = "r2"
    STORAGE_ACCESS_KEY_ID: str = "placeholder-r2-access-key-id"
    STORAGE_SECRET_ACCESS_KEY: str = "placeholder-r2-secret-access-key"
    STORAGE_BUCKET_NAME: str = "meeting-recordings-dev"
    STORAGE_ENDPOINT_URL: str = "https://placeholder-account-id.r2.cloudflarestorage.com"
    STORAGE_REGION: str = "auto"
    STORAGE_PRESIGNED_UPLOAD_EXPIRY_SECONDS: int = 900
    STORAGE_PRESIGNED_DOWNLOAD_EXPIRY_SECONDS: int = 3600

    # 5. LLM Provider Configuration
    LLM_PROVIDER: Literal["groq", "openai", "mock"] = "groq"
    LLM_API_KEY: str = "gsk_placeholder_groq_api_key"
    LLM_MODEL: str = "gpt-oss-120b"
    LLM_LOW_COST_MODEL: str = "gpt-oss-20b"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 2

    # 6. Transcription & Diarization Providers
    TRANSCRIPTION_PROVIDER: Literal["groq_whisper_turbo", "faster_whisper", "mock"] = (
        "groq_whisper_turbo"
    )
    TRANSCRIPTION_API_KEY: str = "gsk_placeholder_groq_api_key"
    TRANSCRIPTION_MODEL: str = "whisper-large-v3-turbo"
    TRANSCRIPTION_TIMEOUT_SECONDS: int = 300
    DIARIZATION_PROVIDER: Literal["pyannote_community_1", "mock"] = "pyannote_community_1"
    HF_TOKEN: str = "hf_placeholder_token"

    # 7. Celery & Redis Task Broker
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "rpc://"
    CELERY_TASK_ACKS_LATE: bool = True
    CELERY_TASK_REJECT_ON_WORKER_LOST: bool = True
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
    CELERY_WORKER_CONCURRENCY: int = 2
    WORKER_LEASE_DURATION_SECONDS: int = 120
    WORKER_HEARTBEAT_INTERVAL_SECONDS: int = 30
    WORKER_MAX_ATTEMPTS: int = 3

    # 8. Frontend / CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL connection string "
                "(Rule 23: PostgreSQL from Day One)."
            )
        return v

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Enforces stricter requirements in production environment."""
        if self.APP_ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production.")
            if "localhost" in self.DATABASE_URL or "127.0.0.1" in self.DATABASE_URL:
                raise ValueError("DATABASE_URL cannot use localhost in production.")
            if "localhost" in self.REDIS_URL or "127.0.0.1" in self.REDIS_URL:
                raise ValueError("REDIS_URL cannot use localhost in production.")
            if "placeholder" in self.STORAGE_ACCESS_KEY_ID:
                raise ValueError("Valid STORAGE_ACCESS_KEY_ID is required in production.")
            if "placeholder" in self.STORAGE_SECRET_ACCESS_KEY:
                raise ValueError("Valid STORAGE_SECRET_ACCESS_KEY is required in production.")
            if "placeholder" in self.LLM_API_KEY and self.LLM_PROVIDER != "mock":
                raise ValueError("Valid LLM_API_KEY is required in production.")
            if "dev-insecure-secret-key" in self.JWT_SIGNING_KEY_OR_JWKS:
                raise ValueError("Insecure default JWT key cannot be used in production.")
        return self

    def __repr__(self) -> str:
        """Prevent accidental leakage of secrets when printing settings object."""
        return (
            f"Settings(APP_NAME={self.APP_NAME!r}, APP_ENV={self.APP_ENV!r}, "
            f"DEBUG={self.DEBUG!r}, LLM_PROVIDER={self.LLM_PROVIDER!r}, "
            f"STORAGE_PROVIDER={self.STORAGE_PROVIDER!r})"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton provider for application settings."""
    return Settings()
