from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMUsage(BaseModel):
    """Token usage and timing metadata returned by LLM providers."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """Normalized response from an LLM provider structured completion call."""

    provider: str
    model: str
    content: str
    parsed_json: dict[str, Any] = Field(default_factory=dict)
    usage: LLMUsage = Field(default_factory=LLMUsage)


class LLMProviderError(Exception):
    """Exception raised by LLM providers during inference."""

    def __init__(self, message: str, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable


class LLMProvider(ABC):
    """Abstract interface for LLM completion providers."""

    @abstractmethod
    def generate_structured(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> LLMResponse:
        """Generates a structured JSON response from chat messages."""
        pass
