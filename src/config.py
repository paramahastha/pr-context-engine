"""Provider factory — reads LLM_PROVIDER env var and returns the right LLMProvider."""
import logging
import os

from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_PROVIDER_ENV = "LLM_PROVIDER"
_DEFAULT = "groq"
_VALID = {"groq", "gemini", "ollama", "anthropic"}


def get_provider() -> LLMProvider:
    """Instantiate and return the LLMProvider named by LLM_PROVIDER (default: groq).

    Reads provider-specific keys from env vars — nothing provider-specific leaks
    into callers. Raises RuntimeError for a missing required key, ValueError for an
    unknown provider name.
    """
    name = (os.getenv(_PROVIDER_ENV) or _DEFAULT).lower()
    logger.info("LLM provider: %s", name)

    if name == "groq":
        from src.llm.groq_provider import GroqProvider

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        return GroqProvider(api_key=api_key)

    if name == "gemini":
        from src.llm.gemini_provider import GeminiProvider

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        return GeminiProvider(api_key=api_key)

    if name == "ollama":
        from src.llm.ollama_provider import OllamaProvider

        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
        return OllamaProvider(base_url=base_url, model=model)

    if name == "anthropic":
        from src.llm.anthropic_provider import AnthropicProvider

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        return AnthropicProvider(api_key=api_key)

    raise ValueError(
        f"Unknown LLM provider: {name!r}. Valid choices: {', '.join(sorted(_VALID))}"
    )
