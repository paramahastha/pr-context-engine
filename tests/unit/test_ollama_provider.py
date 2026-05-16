"""Unit tests for OllamaProvider — verifies the LLMProvider interface contract."""
from unittest.mock import MagicMock, patch

import pytest

from src.llm.ollama_provider import OllamaProvider


def test_generate_returns_response():
    """generate() returns the 'response' field from Ollama's JSON payload."""
    expected = "ollama completion text"
    with patch("src.llm.ollama_provider.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": expected}
        mock_post.return_value = mock_resp

        provider = OllamaProvider()
        result = provider.generate("test prompt")

    assert result == expected
    mock_resp.raise_for_status.assert_called_once()
    mock_post.assert_called_once_with(
        "http://localhost:11434/api/generate",
        json={"model": "qwen2.5-coder:7b", "prompt": "test prompt", "stream": False},
        timeout=120,
    )


def test_generate_raises_on_empty_response():
    """generate() raises RuntimeError when the 'response' field is empty."""
    with patch("src.llm.ollama_provider.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": ""}
        mock_post.return_value = mock_resp

        provider = OllamaProvider()
        with pytest.raises(RuntimeError, match="empty"):
            provider.generate("test prompt")


def test_custom_base_url_and_model():
    """OllamaProvider respects custom base_url and model parameters."""
    with patch("src.llm.ollama_provider.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "ok"}
        mock_post.return_value = mock_resp

        provider = OllamaProvider(base_url="http://remote:11434", model="llama3")
        provider.generate("hi")

    mock_post.assert_called_once_with(
        "http://remote:11434/api/generate",
        json={"model": "llama3", "prompt": "hi", "stream": False},
        timeout=120,
    )
