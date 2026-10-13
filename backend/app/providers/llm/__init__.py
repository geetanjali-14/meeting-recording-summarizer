from app.core.config import Settings
from app.providers.llm.base import LLMProvider
from app.providers.llm.groq_provider import GroqProvider
from app.providers.llm.mock_provider import MockLLMProvider


def get_llm_provider(settings: Settings) -> LLMProvider:
    """Factory creating the configured LLMProvider."""
    if settings.LLM_PROVIDER == "mock":
        return MockLLMProvider(settings)
    return GroqProvider(settings)
