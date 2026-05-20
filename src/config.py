"""Provider factory — reads LLM_PROVIDER env var and returns the right LLMProvider.

Also exposes is_fixes_enabled() for the ENABLE_FIXES kill switch (Milestone 8).
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from src.llm.base import LLMProvider

if TYPE_CHECKING:
    from src.llm import FailoverProvider

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
    if name not in _VALID:
        raise ValueError(
            f"Unknown LLM provider: {name!r}. Valid choices: {', '.join(sorted(_VALID))}"
        )
    logger.info("LLM provider: %s", name)
    return _build_single_provider(name)


def get_failover_provider() -> FailoverProvider:
    """Build a FailoverProvider with automatic Gemini fallback when key is present.

    Primary provider is determined by LLM_PROVIDER (default: groq). If GEMINI_API_KEY
    is set and the primary provider is not Gemini, Gemini is added as a fallback.
    This is the runtime payoff for ADR-0.

    The returned provider's .attribution() gives a footer-friendly string such as
    "groq" or "gemini (groq rate-limited)".

    Raises:
        RuntimeError: If the primary provider's required API key is missing.
        ValueError: If LLM_PROVIDER names an unrecognised provider.
    """
    from src.llm import FailoverProvider

    name = (os.getenv(_PROVIDER_ENV) or _DEFAULT).lower()
    if name not in _VALID:
        raise ValueError(
            f"Unknown LLM provider: {name!r}. Valid choices: {', '.join(sorted(_VALID))}"
        )

    providers: list[tuple[str, LLMProvider]] = [(name, _build_single_provider(name))]

    # Auto-add Gemini fallback when the key is present and the primary is not Gemini.
    gemini_key = os.getenv("GEMINI_API_KEY")
    if name != "gemini" and gemini_key:
        from src.llm.gemini_provider import GeminiProvider

        providers.append(("gemini", GeminiProvider(api_key=gemini_key)))
        logger.info("Gemini failover enabled (GEMINI_API_KEY present)")
    else:
        logger.info("LLM provider: %s (no failover configured)", name)

    return FailoverProvider(providers=providers)


def _build_single_provider(name: str) -> LLMProvider:
    """Instantiate the named provider. Caller is responsible for name validation."""
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

    raise AssertionError(f"unreachable: unhandled provider {name!r}")


def is_fixes_enabled() -> bool:
    """Return True when ENABLE_FIXES env var is set to a truthy value.

    Fix suggestions are opt-in per repo. Default is False so the M4 briefing
    behaviour is unchanged unless the caller explicitly enables the feature.
    """
    return os.getenv("ENABLE_FIXES", "false").strip().lower() in ("true", "1", "yes")
