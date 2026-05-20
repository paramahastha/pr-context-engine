"""Unit tests for GeminiProvider — verifies the LLMProvider interface contract."""
from unittest.mock import patch

import pytest

from src.llm.gemini_provider import GeminiProvider


def test_generate_returns_text():
    """generate() returns response.text from the Gemini API."""
    expected = "gemini response text"
    with patch("src.llm.gemini_provider.genai") as mock_genai:
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value.text = expected

        provider = GeminiProvider(api_key="test-key")
        result = provider.generate("test prompt")

    assert result == expected
    mock_client.models.generate_content.assert_called_once_with(
        model="gemini-2.5-flash",
        contents="test prompt",
    )


def test_generate_raises_on_empty_text():
    """generate() raises RuntimeError when response.text is empty/None."""
    with patch("src.llm.gemini_provider.genai") as mock_genai:
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value.text = None

        provider = GeminiProvider(api_key="test-key")
        with pytest.raises(RuntimeError, match="empty"):
            provider.generate("test prompt")
