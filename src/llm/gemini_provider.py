"""Google Gemini-backed LLMProvider implementation (model: gemini-2.5-flash)."""
import logging

from google import genai

from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.5-flash"


class GeminiProvider(LLMProvider):
    """Calls the Gemini API via google-genai to satisfy the LLMProvider contract."""

    def __init__(self, api_key: str) -> None:
        """Build a Gemini client from an explicit API key."""
        self._client = genai.Client(api_key=api_key)

    def generate(self, prompt: str) -> str:
        """Send `prompt` to Gemini and return the completion text."""
        logger.info("Requesting Gemini completion (model=%s)", _MODEL)
        response = self._client.models.generate_content(
            model=_MODEL,
            contents=prompt,
        )
        try:
            text = response.text
        except ValueError as exc:
            raise RuntimeError("Gemini blocked the response (safety/recitation filter)") from exc
        if not text:
            raise RuntimeError("Gemini returned an empty completion")
        return text
