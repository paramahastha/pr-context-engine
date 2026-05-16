"""LLM provider abstraction: a provider-agnostic interface and its implementations.

Exports FailoverProvider — wraps an ordered list of providers and tries each in
sequence, recording which one succeeded and why others were skipped. This is the
runtime payoff for the ADR-0 provider abstraction built in Milestone 2.
"""
import logging
from dataclasses import dataclass

from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class _ProviderAttempt:
    name: str
    was_rate_limited: bool


class FailoverProvider(LLMProvider):
    """Try providers in order; fall back on rate-limit or any error.

    After a successful generate() call:
      - provider_used: name of the provider that responded
      - skipped: records of providers that were tried and failed

    Call attribution() after generate() to get a footer-friendly string such as
    "groq" or "gemini (groq rate-limited)".
    """

    def __init__(self, providers: list[tuple[str, LLMProvider]]) -> None:
        """
        Args:
            providers: Ordered list of (name, provider) pairs. First is tried first.
        """
        if not providers:
            raise ValueError("FailoverProvider requires at least one provider")
        self._providers = providers
        self.provider_used: str | None = None
        self.skipped: list[_ProviderAttempt] = []

    def generate(self, prompt: str) -> str:
        """Try each provider in order; return the first successful response."""
        self.provider_used = None
        self.skipped = []
        last_exc: Exception | None = None

        for name, provider in self._providers:
            try:
                result = provider.generate(prompt)
                self.provider_used = name
                logger.info("Provider %s succeeded", name)
                return result
            except (TypeError, AttributeError):
                raise
            except Exception as exc:
                is_rate_limited = _is_rate_limit_error(exc)
                self.skipped.append(_ProviderAttempt(name=name, was_rate_limited=is_rate_limited))
                if is_rate_limited:
                    logger.warning("Provider %s rate-limited; trying next", name)
                else:
                    logger.warning("Provider %s failed (%s); trying next", name, exc)
                last_exc = exc

        assert last_exc is not None  # guaranteed: providers is non-empty
        raise RuntimeError(
            f"All {len(self._providers)} provider(s) failed. Last error: {last_exc}"
        ) from last_exc

    def attribution(self) -> str:
        """One-line attribution for the PR comment footer.

        Must be called after generate(). Raises RuntimeError if generate() has not
        been called yet.

        Examples:
            "groq"
            "gemini (groq rate-limited)"
            "gemini (groq failed)"
            "all providers failed"
        """
        if self.provider_used is None and not self.skipped:
            raise RuntimeError("attribution() called before generate()")
        if self.provider_used is None:
            return "all providers failed"
        if not self.skipped:
            return self.provider_used

        rate_limited = [s.name for s in self.skipped if s.was_rate_limited]
        errors = [s.name for s in self.skipped if not s.was_rate_limited]
        reasons: list[str] = []
        if rate_limited:
            reasons.append(f"{', '.join(rate_limited)} rate-limited")
        if errors:
            reasons.append(f"{', '.join(errors)} failed")
        return f"{self.provider_used} ({'; '.join(reasons)})"


def _is_rate_limit_error(exc: Exception) -> bool:
    """Return True if exc represents a rate-limit or quota exhaustion error."""
    msg = str(exc).lower()
    keywords = ("rate limit", "rate_limit", "quota", "429", "resource exhausted", "too many requests")
    if any(kw in msg for kw in keywords):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return status == 429
