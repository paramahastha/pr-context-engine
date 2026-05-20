"""Unit tests for src/config.py — verifies provider selection and error handling."""
import os
from unittest.mock import patch

import pytest

from src.config import get_provider
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.gemini_provider import GeminiProvider
from src.llm.groq_provider import GroqProvider
from src.llm.ollama_provider import OllamaProvider


def test_groq_selected_by_default():
    """get_provider returns GroqProvider when LLM_PROVIDER is unset."""
    env = {"GROQ_API_KEY": "test-key", "LLM_PROVIDER": ""}
    with patch.dict(os.environ, env, clear=False):
        with patch("src.llm.groq_provider.Groq"):
            provider = get_provider()
    assert isinstance(provider, GroqProvider)


def test_groq_selected_explicitly():
    """get_provider returns GroqProvider when LLM_PROVIDER=groq."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "test-key"}):
        with patch("src.llm.groq_provider.Groq"):
            provider = get_provider()
    assert isinstance(provider, GroqProvider)


def test_gemini_selected():
    """get_provider returns GeminiProvider when LLM_PROVIDER=gemini."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}):
        with patch("src.llm.gemini_provider.genai"):
            provider = get_provider()
    assert isinstance(provider, GeminiProvider)


def test_ollama_selected():
    """get_provider returns OllamaProvider when LLM_PROVIDER=ollama (no key needed)."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
        provider = get_provider()
    assert isinstance(provider, OllamaProvider)


def test_anthropic_selected():
    """get_provider returns AnthropicProvider when LLM_PROVIDER=anthropic."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"}):
        with patch("src.llm.anthropic_provider.anthropic"):
            provider = get_provider()
    assert isinstance(provider, AnthropicProvider)


def test_unknown_provider_raises():
    """get_provider raises ValueError for an unrecognised provider name."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "openai"}):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider()


def test_groq_missing_key_raises():
    """get_provider raises RuntimeError when GROQ_API_KEY is absent."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "groq"}, clear=False):
        os.environ.pop("GROQ_API_KEY", None)
        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            get_provider()


def test_gemini_missing_key_raises():
    """get_provider raises RuntimeError when GEMINI_API_KEY is absent."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "gemini"}, clear=False):
        os.environ.pop("GEMINI_API_KEY", None)
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            get_provider()


def test_anthropic_missing_key_raises():
    """get_provider raises RuntimeError when ANTHROPIC_API_KEY is absent."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic"}, clear=False):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            get_provider()
