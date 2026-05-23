"""Unit tests for GroqProvider — verifies the LLMProvider interface contract."""
from unittest.mock import patch

import pytest

from src.llm.groq_provider import GroqProvider


def test_generate_returns_completion():
    """generate() returns the content string from the Groq completion."""
    expected = "bullet 1\nbullet 2\nbullet 3"
    with patch("src.llm.groq_provider.Groq") as MockGroq:
        mock_client = MockGroq.return_value
        mock_client.chat.completions.create.return_value.choices[0].message.content = expected

        provider = GroqProvider(api_key="test-key")
        result = provider.generate("test prompt")

    assert result == expected
    mock_client.chat.completions.create.assert_called_once_with(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "test prompt"}],
    )


def test_generate_raises_on_empty_content():
    """generate() raises RuntimeError when the completion content is None."""
    with patch("src.llm.groq_provider.Groq") as MockGroq:
        mock_client = MockGroq.return_value
        mock_client.chat.completions.create.return_value.choices[0].message.content = None

        provider = GroqProvider(api_key="test-key")
        with pytest.raises(RuntimeError, match="empty"):
            provider.generate("test prompt")
