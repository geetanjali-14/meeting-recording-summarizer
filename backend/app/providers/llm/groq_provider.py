import json
import logging
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

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self.GROQ_CHAT_URL,
                    headers=headers,
                    json=payload,
                )

            if response.status_code == 429 or response.status_code >= 500:
                raise LLMProviderError(
                    f"Groq transient HTTP error {response.status_code}: {response.text}",
                    is_retryable=True,
                )
            if response.status_code != 200:
                raise LLMProviderError(
                    f"Groq permanent HTTP error {response.status_code}: {response.text}",
                    is_retryable=False,
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
