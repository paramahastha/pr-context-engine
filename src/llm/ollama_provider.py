"""Ollama-backed LLMProvider for local development (default model: qwen2.5-coder:7b)."""
import logging

import requests

from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "qwen2.5-coder:7b"


class OllamaProvider(LLMProvider):
    """Calls a local Ollama instance via REST to satisfy the LLMProvider contract.

    No API key required — runs entirely offline. Suitable for dev/iteration.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        """Configure the Ollama endpoint and model."""
        self._base_url = base_url.rstrip("/")
        self._model = model

    def generate(self, prompt: str) -> str:
        """POST the prompt to Ollama's /api/generate and return the response text."""
        logger.info("Requesting Ollama completion (model=%s)", self._model)
        response = requests.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        text = response.json().get("response", "")
        if not text:
            raise RuntimeError("Ollama returned an empty response")
        return text
