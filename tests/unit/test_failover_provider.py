"""Unit tests for FailoverProvider — ordering, failover, 429 detection, attribution."""
from unittest.mock import MagicMock

import pytest

from src.llm import FailoverProvider, _is_rate_limit_error


# --- helpers ---

def _mock(name: str, *, side_effect=None, return_value: str = "response"):
    """Return a (name, mock_provider) pair for use in FailoverProvider."""
    p = MagicMock()
    if side_effect is not None:
        p.generate.side_effect = side_effect
    else:
        p.generate.return_value = return_value
    return (name, p)


# --- construction ---

def test_requires_nonempty_provider_list():
    with pytest.raises(ValueError, match="at least one provider"):
        FailoverProvider([])


# --- primary succeeds ---

def test_uses_primary_on_success():
    fp = FailoverProvider([_mock("groq", return_value="groq ok"), _mock("gemini", return_value="gemini ok")])
    result = fp.generate("prompt")
    assert result == "groq ok"
    assert fp.provider_used == "groq"
    assert fp.skipped == []


def test_fallback_not_called_when_primary_succeeds():
    primary_name, primary_mock = _mock("groq", return_value="ok")
    fallback_name, fallback_mock = _mock("gemini", return_value="ok")
    fp = FailoverProvider([(primary_name, primary_mock), (fallback_name, fallback_mock)])
    fp.generate("prompt")
    primary_mock.generate.assert_called_once_with("prompt")
    fallback_mock.generate.assert_not_called()


# --- failover on rate-limit ---

def test_falls_back_on_rate_limit_error():
    rate_err = RuntimeError("429 Too Many Requests: rate limit exceeded")
    fp = FailoverProvider([_mock("groq", side_effect=rate_err), _mock("gemini", return_value="gemini ok")])

    result = fp.generate("prompt")

    assert result == "gemini ok"
    assert fp.provider_used == "gemini"
    assert len(fp.skipped) == 1
    assert fp.skipped[0].name == "groq"
    assert fp.skipped[0].was_rate_limited is True


def test_falls_back_on_generic_error():
    fp = FailoverProvider([
        _mock("groq", side_effect=RuntimeError("connection timeout")),
        _mock("gemini", return_value="gemini ok"),
    ])
    result = fp.generate("prompt")
    assert result == "gemini ok"
    assert fp.skipped[0].was_rate_limited is False


# --- all providers fail ---

def test_raises_when_all_providers_fail():
    fp = FailoverProvider([
        _mock("groq", side_effect=RuntimeError("rate limit")),
        _mock("gemini", side_effect=RuntimeError("quota exceeded")),
    ])
    with pytest.raises(RuntimeError, match="All 2 provider"):
        fp.generate("prompt")
    assert fp.provider_used is None
    assert len(fp.skipped) == 2


# --- attribution ---

def test_attribution_single_provider_success():
    fp = FailoverProvider([_mock("groq", return_value="ok")])
    fp.generate("prompt")
    assert fp.attribution() == "groq"


def test_attribution_before_generate_raises():
    fp = FailoverProvider([_mock("groq", return_value="ok")])
    with pytest.raises(RuntimeError, match="before generate"):
        fp.attribution()


def test_attribution_fallback_rate_limited():
    fp = FailoverProvider([
        _mock("groq", side_effect=RuntimeError("429 rate limit")),
        _mock("gemini", return_value="ok"),
    ])
    fp.generate("prompt")
    assert fp.attribution() == "gemini (groq rate-limited)"


def test_attribution_fallback_generic_error():
    fp = FailoverProvider([
        _mock("groq", side_effect=RuntimeError("connection error")),
        _mock("gemini", return_value="ok"),
    ])
    fp.generate("prompt")
    assert fp.attribution() == "gemini (groq failed)"


def test_attribution_multiple_skipped():
    fp = FailoverProvider([
        _mock("groq", side_effect=RuntimeError("429 rate limit")),
        _mock("anthropic", side_effect=RuntimeError("network error")),
        _mock("gemini", return_value="ok"),
    ])
    fp.generate("prompt")
    # groq was rate-limited, anthropic failed generically
    assert fp.attribution() == "gemini (groq rate-limited; anthropic failed)"


# --- _is_rate_limit_error ---

@pytest.mark.parametrize("msg", [
    "429 Too Many Requests",
    "rate limit exceeded",
    "rate_limit hit",
    "quota exhausted",
    "resource exhausted",
    "too many requests",
])
def test_is_rate_limit_error_message_variants(msg):
    assert _is_rate_limit_error(RuntimeError(msg)) is True


def test_is_rate_limit_error_status_code_attribute():
    exc = RuntimeError("server error")
    exc.status_code = 429  # type: ignore[attr-defined]
    assert _is_rate_limit_error(exc) is True


def test_is_rate_limit_error_other_status():
    exc = RuntimeError("internal server error")
    exc.status_code = 500  # type: ignore[attr-defined]
    assert _is_rate_limit_error(exc) is False


def test_is_rate_limit_error_generic_runtime():
    assert _is_rate_limit_error(RuntimeError("connection timeout")) is False


def test_is_rate_limit_error_code_attribute():
    exc = RuntimeError("server error")
    exc.code = 429  # type: ignore[attr-defined]
    assert _is_rate_limit_error(exc) is True


def test_state_resets_between_generate_calls():
    primary = MagicMock()
    primary.generate.side_effect = [RuntimeError("rate limit"), "ok on retry"]
    fallback = MagicMock()
    fallback.generate.return_value = "fallback ok"

    fp = FailoverProvider([("groq", primary), ("gemini", fallback)])

    result1 = fp.generate("p1")
    assert result1 == "fallback ok"
    assert fp.provider_used == "gemini"
    assert len(fp.skipped) == 1

    # Second call: groq succeeds; skipped must be reset to empty
    result2 = fp.generate("p2")
    assert result2 == "ok on retry"
    assert fp.provider_used == "groq"
    assert fp.skipped == []


def test_programming_errors_are_not_caught():
    bad_provider = MagicMock()
    bad_provider.generate.side_effect = TypeError("wrong type — programming bug")
    fp = FailoverProvider([("groq", bad_provider), _mock("gemini", return_value="ok")])
    with pytest.raises(TypeError):
        fp.generate("prompt")
