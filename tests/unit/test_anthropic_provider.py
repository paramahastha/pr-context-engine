"""Unit tests for AnthropicProvider — verifies the LLMProvider interface contract."""
from unittest.mock import MagicMock, patch

import pytest

from src.llm.anthropic_provider import AnthropicProvider


def test_generate_returns_text():
    """generate() returns the first content block's text from the Anthropic response."""
    expected = "claude completion text"
    with patch("src.llm.anthropic_provider.anthropic") as mock_anthropic:
        mock_client = mock_anthropic.Anthropic.return_value
        mock_message = MagicMock()
        mock_message.content[0].text = expected
        mock_client.messages.create.return_value = mock_message

        provider = AnthropicProvider(api_key="test-key")
        result = provider.generate("test prompt")

    assert result == expected
    mock_client.messages.create.assert_called_once_with(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": "test prompt"}],
    )


def test_generate_raises_on_empty_text():
    """generate() raises RuntimeError when the completion text is empty/falsy."""
    with patch("src.llm.anthropic_provider.anthropic") as mock_anthropic:
        mock_client = mock_anthropic.Anthropic.return_value
        mock_message = MagicMock()
        mock_message.content[0].text = ""
        mock_client.messages.create.return_value = mock_message

        provider = AnthropicProvider(api_key="test-key")
        with pytest.raises(RuntimeError, match="empty"):
            provider.generate("test prompt")
