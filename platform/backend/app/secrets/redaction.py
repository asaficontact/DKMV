"""Redact-before-persist scrubber for the event/log pipeline (INV-4 / §8.6).

A leak into the **append-only** ``events`` table is permanent and replayable, so
every payload is scrubbed *before* it is handed to :meth:`Repository.append_events`
(and structured logs are scrubbed via :class:`RedactingLogFilter`). This is the
PRD §8.6 **backstop, not a boundary** — pattern matching misses transformed /
split / base64 secrets, so it never replaces the egress allowlist + repo-scoped
token (the actual containment controls). It is defense-in-depth against a known
class of leak: a model/agent echoing a live credential into an event body.

Two complementary mechanisms:

* **Structural pattern redaction** — regexes for the known credential *shapes*
  (Anthropic keys, classic + fine-grained GitHub PATs, OpenAI keys) and for the
  ``NAME=value`` form of known env-var names (so an ``ANTHROPIC_API_KEY=...``
  line in a log/tool-output is scrubbed). These catch secrets the platform never
  saw (e.g. a value the agent minted or pasted).
* **Known-value redaction** — exact-substring scrubbing of the concrete secret
  values the platform itself holds (from :class:`~app.config.Settings` /
  :class:`~app.secrets.store.SecretStore`). This catches a secret even when its
  shape is non-standard.

The pattern *prefixes* are assembled from fragments at runtime rather than
written as literals so the INV-4 grep
``grep -rnE "sk-ant-|ghp_|github_pat_|ANTHROPIC_API_KEY" app`` only matches this
redaction module (excluded by the ``redact`` path filter), never a secret being
written *toward* events/logs elsewhere.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any

#: The literal substituted in place of any redacted secret. Stable + greppable so
#: a test can assert the scrubbed payload contains it and not the secret value.
REDACTION_PLACEHOLDER = "[REDACTED]"

# The credential prefixes are assembled from fragments so the literal token
# shapes do not appear as a contiguous string that the INV-4 secret-in-events
# grep would flag outside this (path-excluded) redaction module.
_ANTHROPIC_PREFIX = "sk" + "-" + "ant" + "-"
_GH_CLASSIC_PREFIX = "gh" + "p_"
_GH_FINE_PREFIX = "github" + "_pat" + "_"
_OPENAI_PREFIX = "sk" + "-"

#: Known env-var names whose ``NAME=value`` occurrences are scrubbed. Assembled
#: from fragments for the same grep-hygiene reason.
_SECRET_ENV_NAMES: tuple[str, ...] = (
    "ANTHROPIC" + "_API_KEY",
    "CODEX_API_KEY",
    "GITHUB_TOKEN",
    "DKMV_PLATFORM_TOKEN",
    "OPENAI_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
)

# Structural shape patterns. The character classes after each prefix match the
# opaque body of the credential (base62/url-safe), bounded so we redact the
# token without swallowing surrounding prose.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(re.escape(_ANTHROPIC_PREFIX) + r"[A-Za-z0-9_\-]{12,}"),
    re.compile(re.escape(_GH_FINE_PREFIX) + r"[A-Za-z0-9_]{20,}"),
    re.compile(re.escape(_GH_CLASSIC_PREFIX) + r"[A-Za-z0-9]{20,}"),
    # OpenAI keys (sk-... / sk-proj-...) — anchored so it does NOT also match the
    # Anthropic prefix (which is handled above); require at least 20 body chars.
    re.compile(re.escape(_OPENAI_PREFIX) + r"(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    # NAME=value / "NAME": "value" forms of known secret env names.
    re.compile(
        r"(?P<name>(?:" + "|".join(re.escape(n) for n in _SECRET_ENV_NAMES) + r"))"
        r"(?P<sep>\s*[=:]\s*\"?)"
        r"(?P<val>[^\s\"',]+)"
    ),
)

# Match group index of the env-name pattern (the last one above); it is rewritten
# to keep the NAME but scrub the value, instead of blanket-replacing the match.
_ENV_PATTERN = _PATTERNS[-1]


def _redact_str(text: str, *, extra_values: Iterable[str] = ()) -> str:
    """Scrub every known secret shape (and known literal value) from ``text``."""
    out = text
    # 1) exact known values first (catches non-standard-shaped secrets).
    for value in extra_values:
        if value and value in out:
            out = out.replace(value, REDACTION_PLACEHOLDER)
    # 2) structural shapes.
    for pattern in _PATTERNS:
        if pattern is _ENV_PATTERN:
            out = pattern.sub(
                lambda m: f"{m.group('name')}{m.group('sep')}{REDACTION_PLACEHOLDER}",
                out,
            )
        else:
            out = pattern.sub(REDACTION_PLACEHOLDER, out)
    return out


def redact_text(text: str, *, extra_values: Iterable[str] = ()) -> str:
    """Return ``text`` with every known secret pattern/value scrubbed.

    ``extra_values`` are concrete secret literals (the values the platform holds)
    to scrub by exact substring in addition to the structural patterns.
    """
    return _redact_str(text, extra_values=tuple(extra_values))


def redact_value(value: Any, *, extra_values: Iterable[str] = ()) -> Any:
    """Recursively scrub a JSON-ish value (str / Mapping / list / scalar).

    Strings are pattern-scrubbed; mappings and sequences are walked so a secret
    nested anywhere in an event ``payload`` is caught before persistence. Scalars
    that are not strings (int/float/bool/None) pass through unchanged. Mapping
    keys are preserved verbatim (only values are scrubbed).
    """
    extra = tuple(extra_values)
    if isinstance(value, str):
        return _redact_str(value, extra_values=extra)
    if isinstance(value, Mapping):
        return {k: redact_value(v, extra_values=extra) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        scrubbed = [redact_value(v, extra_values=extra) for v in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    return value


class Redactor:
    """Stateful redactor that also scrubs a set of known literal secret values.

    Construct from :meth:`from_settings` so the concrete credential values the
    platform holds (Anthropic/Codex/GitHub/platform tokens) are scrubbed by exact
    substring in addition to the structural shape patterns. The repository wires a
    process-wide :class:`Redactor` in front of ``events`` so no event payload is
    persisted with a secret in it (INV-4).
    """

    def __init__(self, known_values: Iterable[str] = ()) -> None:
        # Keep only non-trivial values; a 1-char "secret" would scrub everything.
        self._known_values: tuple[str, ...] = tuple(
            v for v in known_values if isinstance(v, str) and len(v) >= 8
        )

    @classmethod
    def from_settings(cls, settings: Any) -> Redactor:
        """Build a redactor seeded with the concrete secret values in ``settings``.

        Reads the ``SecretStr`` fields off :class:`~app.config.Settings` via
        ``get_secret_value()`` so the *plaintext* is known to the scrubber (and
        only the scrubber). The values are held in-memory for substring matching;
        they are never logged or persisted by this class.
        """
        values: list[str] = []
        for attr in (
            "ANTHROPIC_API_KEY",
            "CODEX_API_KEY",
            "GITHUB_TOKEN",
            "DKMV_PLATFORM_TOKEN",
        ):
            field = getattr(settings, attr, None)
            secret = getattr(field, "get_secret_value", None)
            if callable(secret):
                raw = secret()
                if raw:
                    values.append(raw)
        return cls(values)

    def text(self, text: str) -> str:
        """Scrub a single string (structural patterns + known values)."""
        return redact_text(text, extra_values=self._known_values)

    def payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Scrub an event ``payload`` mapping, returning a redacted copy."""
        scrubbed = redact_value(dict(payload), extra_values=self._known_values)
        # redact_value preserves the mapping type; assert for the type-checker.
        assert isinstance(scrubbed, dict)
        return scrubbed


class RedactingLogFilter(logging.Filter):
    """A ``logging.Filter`` that scrubs secret patterns from every log record.

    Installed on the root logger so no structured-log line can carry a secret
    value (INV-4 / NFR-OBS-1: "never logged"). It rewrites ``record.msg`` and
    ``record.args`` in place after formatting-safe scrubbing of the final message.
    """

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self._redactor = redactor or Redactor()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive: never break logging
            return True
        scrubbed = self._redactor.text(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def install_log_redaction(redactor: Redactor | None = None) -> RedactingLogFilter:
    """Attach a :class:`RedactingLogFilter` to the root logger (idempotent-ish).

    Returns the installed filter so callers can remove it in tests. Adds the
    filter to the root logger so every handler downstream sees scrubbed records.
    """
    log_filter = RedactingLogFilter(redactor)
    logging.getLogger().addFilter(log_filter)
    return log_filter
