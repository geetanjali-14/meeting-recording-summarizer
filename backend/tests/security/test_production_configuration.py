import json
import logging
import pytest
from app.core.config import Settings
from app.core.logging import JSONFormatter


def test_production_settings_validation_blocks_insecure_defaults() -> None:
    # 1. DEBUG must not be True in production
    with pytest.raises(ValueError, match="DEBUG must be False in production"):
        Settings(
            APP_ENV="production",
            DEBUG=True,
            DATABASE_URL="postgresql+psycopg://user:pass@remote-host:5432/dbname",
            REDIS_URL="redis://remote-host:6379/0",
            STORAGE_ACCESS_KEY_ID="valid_r2_key",
            STORAGE_SECRET_ACCESS_KEY="valid_r2_secret",
            LLM_API_KEY="valid_llm_key",
            JWT_SIGNING_KEY_OR_JWKS="secure_production_jwt_signing_key_secret_value",
        )

    # 2. Localhost database blocked in production
    with pytest.raises(ValueError, match="DATABASE_URL cannot use localhost"):
        Settings(
            APP_ENV="production",
            DEBUG=False,
            DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/dbname",
            REDIS_URL="redis://remote-host:6379/0",
            STORAGE_ACCESS_KEY_ID="valid_r2_key",
            STORAGE_SECRET_ACCESS_KEY="valid_r2_secret",
            LLM_API_KEY="valid_llm_key",
            JWT_SIGNING_KEY_OR_JWKS="secure_production_jwt_signing_key_secret_value",
        )

    # 3. Localhost redis blocked in production
    with pytest.raises(ValueError, match="REDIS_URL cannot use localhost"):
        Settings(
            APP_ENV="production",
            DEBUG=False,
            DATABASE_URL="postgresql+psycopg://user:pass@remote-host:5432/dbname",
            REDIS_URL="redis://localhost:6379/0",
            STORAGE_ACCESS_KEY_ID="valid_r2_key",
            STORAGE_SECRET_ACCESS_KEY="valid_r2_secret",
            LLM_API_KEY="valid_llm_key",
            JWT_SIGNING_KEY_OR_JWKS="secure_production_jwt_signing_key_secret_value",
        )

    # 4. Insecure JWT secret blocked in production
    with pytest.raises(ValueError, match="Insecure default JWT key cannot be used"):
        Settings(
            APP_ENV="production",
            DEBUG=False,
            DATABASE_URL="postgresql+psycopg://user:pass@remote-host:5432/dbname",
            REDIS_URL="redis://remote-host:6379/0",
            STORAGE_ACCESS_KEY_ID="valid_r2_key",
            STORAGE_SECRET_ACCESS_KEY="valid_r2_secret",
            LLM_API_KEY="valid_llm_key",
            JWT_SIGNING_KEY_OR_JWKS="dev-insecure-secret-key-change-in-production",
        )

    # 5. Placeholder storage secret blocked in production
    with pytest.raises(ValueError, match="Valid STORAGE_SECRET_ACCESS_KEY is required"):
        Settings(
            APP_ENV="production",
            DEBUG=False,
            DATABASE_URL="postgresql+psycopg://user:pass@remote-host:5432/dbname",
            REDIS_URL="redis://remote-host:6379/0",
            STORAGE_ACCESS_KEY_ID="valid_r2_key",
            STORAGE_SECRET_ACCESS_KEY="placeholder-secret",
            LLM_API_KEY="valid_llm_key",
            JWT_SIGNING_KEY_OR_JWKS="secure_production_jwt_signing_key_secret_value",
        )

    # 6. Valid production configuration passes smoothly
    valid_settings = Settings(
        APP_ENV="production",
        DEBUG=False,
        DATABASE_URL="postgresql+psycopg://user:pass@aws-0.supabase.com:6543/postgres",
        REDIS_URL="rediss://default:token@aws-0.upstash.io:6379/0",
        STORAGE_ACCESS_KEY_ID="actual_prod_r2_key_id",
        STORAGE_SECRET_ACCESS_KEY="actual_prod_r2_secret_key",
        LLM_API_KEY="gsk_actual_live_groq_key",
        JWT_SIGNING_KEY_OR_JWKS="https://project.supabase.co/auth/v1/.well-known/jwks.json",
    )
    assert valid_settings.APP_ENV == "production"
    assert valid_settings.DEBUG is False


def test_json_formatter_comprehensive_log_sanitization() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_prod_logger",
        level=logging.ERROR,
        pathname="production.py",
        lineno=42,
        msg="Database reconnection failed with credential details",
        args=(),
        exc_info=None,
    )
    record.api_key = "gsk_sensitive_key_value"
    record.secret_key = "secret_storage_key"
    record.authorization = "Bearer eyJhbGciOi..."
    record.custom_secret_token = "confidential_token"
    record.request_id = "req-9999"

    output = formatter.format(record)
    log_data = json.loads(output)

    assert log_data["request_id"] == "req-9999"
    assert "api_key" not in log_data
    assert "secret_key" not in log_data
    assert "authorization" not in log_data
    assert "custom_secret_token" not in log_data
    assert "gsk_sensitive_key_value" not in output
    assert "confidential_token" not in output

