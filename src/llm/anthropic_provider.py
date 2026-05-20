"""Anthropic Claude-backed LLMProvider implementation (model: claude-sonnet-4-6)."""
import logging

import anthropic

from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1024


class AnthropicProvider(LLMProvider):
    """Calls the Anthropic Messages API to satisfy the LLMProvider contract."""

    def __init__(self, api_key: str) -> None:
        """Build an Anthropic client from an explicit API key."""
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, prompt: str) -> str:
        """Send `prompt` as a single user message and return the completion text."""
        logger.info("Requesting Anthropic completion (model=%s)", _MODEL)
        message = self._client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        if not message.content or not message.content[0].text:
            raise RuntimeError("Anthropic returned an empty completion")
        text = message.content[0].text
        return text
