import json
import logging
import sys
from typing import Any


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production observability.

    Automatically redacts sensitive keys (passwords, tokens, keys) and formats
    log records into JSON with standard metadata attributes.
    """

    REDACTED_KEYS = {
        "password",
        "secret",
        "token",
        "key",
        "authorization",
        "access_key",
        "secret_key",
        "api_key",
        "hf_token",
    }

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include custom context attributes if present on record
        for attr in (
            "request_id",
            "path",
            "endpoint",
            "status_code",
            "meeting_id",
            "job_id",
            "celery_task_id",
            "provider",
            "step",
            "duration_ms",
        ):
            val = getattr(record, attr, None)
            if val is not None and attr.lower() not in self.REDACTED_KEYS:
                log_payload[attr] = val

        # Also redact any record __dict__ sensitive items
        for k in record.__dict__:
            if any(secret_term in k.lower() for secret_term in self.REDACTED_KEYS):
                # Ensure it is never leaked even if added dynamically
                log_payload.pop(k, None)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload, default=str)


def setup_logging(log_level: str = "INFO") -> None:
    """Configures structured JSON logging on the root logger."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    # Clear existing handlers to prevent duplicate output
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)
