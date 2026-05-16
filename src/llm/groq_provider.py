"""Groq-backed LLMProvider implementation (model: llama-3.3-70b-versatile)."""
import logging

from groq import Groq

from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_MODEL = "llama-3.3-70b-versatile"


class GroqProvider(LLMProvider):
    """Calls the Groq chat-completions API to satisfy the LLMProvider contract."""

    def __init__(self, api_key: str) -> None:
        """Build a Groq client from an explicit API key."""
        self._client = Groq(api_key=api_key)

    def generate(self, prompt: str) -> str:
        """Send `prompt` as a single user message and return the completion text."""
        logger.info("Requesting Groq completion (model=%s)", _MODEL)
        response = self._client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("Groq returned an empty completion")
        return content
