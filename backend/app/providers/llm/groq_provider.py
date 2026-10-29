import email.utils
import json
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.llm.base import (
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    LLMUsage,
)

logger = logging.getLogger(__name__)


def parse_groq_reset_duration(val: str) -> float | None:
    """Parses Groq reset string format (e.g. '2m59.56s', '7.66s', '1h2m3s') into seconds."""
    val = val.strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        pass

    pattern = re.compile(r"((?P<hours>\d+)h)?((?P<minutes>\d+)m)?((?P<seconds>[\d\.]+)s)?")
    match = pattern.fullmatch(val)
    if not match:
        return None

    groups = match.groupdict()
    hours = float(groups.get("hours") or 0.0)
    minutes = float(groups.get("minutes") or 0.0)
    seconds = float(groups.get("seconds") or 0.0)
    total = (hours * 3600.0) + (minutes * 60.0) + seconds
    return total if total > 0.0 else None


def parse_retry_after_header(headers: httpx.Headers) -> float | None:
    """Extracts wait duration in seconds from Retry-After or Groq rate limit reset headers.

    Priority:
    1. Standard 'Retry-After' (integer/float seconds or HTTP-date).
    2. 'x-ratelimit-reset-tokens' or 'x-ratelimit-reset-requests' (e.g., '7.66s', '2m59.56s').
    """
    raw_retry = headers.get("retry-after")
    if raw_retry:
        raw_retry = raw_retry.strip()
        try:
            return max(0.0, float(raw_retry))
        except ValueError:
            # Check for HTTP-date format (RFC 7231 / RFC 2616)
            try:
                date_tuple = email.utils.parsedate_to_datetime(raw_retry)
                diff = date_tuple.timestamp() - time.time()
                return max(0.0, diff)
            except Exception:
                pass

    # Fallback to Groq duration reset headers
    for reset_key in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        reset_val = headers.get(reset_key)
        if reset_val:
            duration = parse_groq_reset_duration(reset_val)
            if duration is not None:
                return duration

    return None


class GroqProvider(LLMProvider):
    """Groq-hosted LLM provider supporting GPT-OSS models via OpenAI-compatible API."""

    GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.LLM_API_KEY
        self.default_model = settings.LLM_MODEL
        self.low_cost_model = settings.LLM_LOW_COST_MODEL
        self.timeout_seconds = settings.LLM_TIMEOUT_SECONDS
        self.max_retries = settings.LLM_MAX_RETRIES

    def _resolve_model(self, model: str | None) -> str:
        chosen = model or self.default_model
        # Map short name to full Groq model identifier if needed
        if chosen in ("gpt-oss-120b", "openai/gpt-oss-120b"):
            return "openai/gpt-oss-120b"
        if chosen in ("gpt-oss-20b", "openai/gpt-oss-20b"):
            return "openai/gpt-oss-20b"
        return chosen

    def generate_structured(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> LLMResponse:
        if not self.api_key or "placeholder" in self.api_key.lower():
            raise LLMProviderError(
                "Missing or invalid Groq LLM API key. Configure LLM_API_KEY in environment.",
                is_retryable=False,
            )

        resolved_model = self._resolve_model(model)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        # Groq OpenAI API requires the word 'json' in messages when response_format is json_object
        has_json_word = any("json" in m.get("content", "").lower() for m in messages)
        if not has_json_word and messages:
            # Append prompt hint to last user message or add system hint
            messages[-1]["content"] += "\n(Return response in valid JSON format)"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self.GROQ_CHAT_URL,
                    headers=headers,
                    json=payload,
                )

            if response.status_code == 429 or response.status_code >= 500:
                retry_after_val = parse_retry_after_header(response.headers)
                raise LLMProviderError(
                    f"Groq transient HTTP error {response.status_code}: {response.text}",
                    is_retryable=True,
                    retry_after=retry_after_val,
                    status_code=response.status_code,
                )
            if response.status_code != 200:
                raise LLMProviderError(
                    f"Groq permanent HTTP error {response.status_code}: {response.text}",
                    is_retryable=False,
                    status_code=response.status_code,
                )

            data = response.json()
        except httpx.TimeoutException as exc:
            raise LLMProviderError(f"Groq LLM request timed out: {exc}", is_retryable=True) from exc
        except httpx.NetworkError as exc:
            raise LLMProviderError(f"Groq LLM network error: {exc}", is_retryable=True) from exc
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"Groq LLM unexpected error: {exc}", is_retryable=False) from exc

        choices = data.get("choices", [])
        if not choices:
            raise LLMProviderError("Groq returned empty choices list", is_retryable=False)

        message_obj = choices[0].get("message", {})
        raw_content = message_obj.get("content", "")

        try:
            parsed_json = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"Groq returned malformed JSON content: {raw_content[:200]}",
                is_retryable=False,
            ) from exc

        usage_data = data.get("usage", {})
        usage = LLMUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return LLMResponse(
            provider="groq",
            model=resolved_model,
            content=raw_content,
            parsed_json=parsed_json,
            usage=usage,
        )
