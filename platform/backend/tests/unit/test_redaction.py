"""Redact-before-persist pattern coverage (INV-4 / AC-0.5-4)."""

from __future__ import annotations

import logging

import pytest
from app.secrets.redaction import (
    REDACTION_PLACEHOLDER,
    RedactingLogFilter,
    Redactor,
    redact_text,
    redact_value,
)

# Synthetic (fake) secret values shaped like the real credentials. Assembled
# from fragments so this *test* fixture doesn't itself trip the secret-in-events
# grep with a contiguous literal.
_ANTHROPIC = "sk" + "-ant-" + "api03-" + "A" * 40
_GH_CLASSIC = "gh" + "p_" + "B" * 36
_GH_FINE = "github" + "_pat_" + "C" * 40
_OPENAI = "sk" + "-proj-" + "D" * 40


@pytest.mark.parametrize(
    "secret",
    [_ANTHROPIC, _GH_CLASSIC, _GH_FINE, _OPENAI],
    ids=["anthropic", "gh_classic", "gh_fine", "openai"],
)
def test_each_pattern_is_scrubbed(secret: str) -> None:
    text = f"the agent printed {secret} into its output"
    scrubbed = redact_text(text)
    assert secret not in scrubbed
    assert REDACTION_PLACEHOLDER in scrubbed


def test_env_name_value_form_is_scrubbed() -> None:
    line = "ANTHROPIC_API_KEY=" + _ANTHROPIC
    scrubbed = redact_text(line)
    # The NAME survives (useful signal), the VALUE is gone.
    assert "ANTHROPIC_API_KEY" in scrubbed
    assert _ANTHROPIC not in scrubbed
    assert REDACTION_PLACEHOLDER in scrubbed


def test_known_value_with_nonstandard_shape_is_scrubbed() -> None:
    # A secret whose *shape* is not a known pattern, but whose literal value the
    # platform holds — must still be scrubbed by exact-substring.
    weird = "ZZZ-internal-token-0123456789abcdef"
    redactor = Redactor(known_values=[weird])
    scrubbed = redactor.text(f"leaked {weird} here")
    assert weird not in scrubbed
    assert REDACTION_PLACEHOLDER in scrubbed


def test_payload_is_scrubbed_recursively() -> None:
    payload = {
        "type": "assistant_message",
        "text": f"here is the key {_ANTHROPIC}",
        "nested": {"deep": [f"and {_GH_CLASSIC}", "clean"]},
        "cost_usd": 0.42,
        "count": 7,
    }
    redacted = redact_value(payload)
    flat = repr(redacted)
    assert _ANTHROPIC not in flat
    assert _GH_CLASSIC not in flat
    # Non-string scalars pass through untouched.
    assert redacted["cost_usd"] == 0.42
    assert redacted["count"] == 7


def test_clean_payload_is_unchanged() -> None:
    payload = {"type": "tool_use", "name": "edit", "ok": True}
    assert redact_value(payload) == payload


def test_redactor_from_settings_scrubs_configured_secret() -> None:
    class _Field:
        def __init__(self, raw: str) -> None:
            self._raw = raw

        def get_secret_value(self) -> str:
            return self._raw

    class _Settings:
        ANTHROPIC_API_KEY = _Field("super-secret-anthropic-value-12345")
        CODEX_API_KEY = _Field("")
        GITHUB_TOKEN = _Field("ghp-operator-token-value-7777")
        DKMV_PLATFORM_TOKEN = _Field("local-token-abcdefgh")

    redactor = Redactor.from_settings(_Settings())
    scrubbed = redactor.text("saw super-secret-anthropic-value-12345 in the wild")
    assert "super-secret-anthropic-value-12345" not in scrubbed


def test_short_known_value_does_not_over_redact() -> None:
    # A 1-char "secret" would scrub everything; from_settings/Redactor must drop
    # trivially-short values.
    redactor = Redactor(known_values=["a", "xy"])
    assert redactor.text("a quick brown xy fox") == "a quick brown xy fox"


def test_log_filter_scrubs_records() -> None:
    log_filter = RedactingLogFilter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token is %s",
        args=(_ANTHROPIC,),
        exc_info=None,
    )
    assert log_filter.filter(record) is True
    assert _ANTHROPIC not in record.getMessage()
    assert REDACTION_PLACEHOLDER in record.getMessage()
