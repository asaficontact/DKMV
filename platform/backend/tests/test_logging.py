"""Structured-logging tests — run/issue/session context + INV-4 redaction (AC-11).

Asserts a structured log record (1) carries the ``run_id`` / ``issue`` / ``session``
correlation block in the OTel-compatible schema and (2) never carries a secret
pattern — the redact-before-persist guarantee (INV-4 / NFR-OBS-1).
"""

from __future__ import annotations

import json
import logging

from app.observability import (
    LOG_CONTEXT_FIELDS,
    StructuredLogContext,
    StructuredLogFormatter,
    bind_log_context,
    current_log_context,
    install_structured_logging,
    log_context,
)
from app.observability.logging import OTEL_ATTRIBUTE_KEYS
from app.secrets import Redactor

# A non-real secret literal assembled from fragments (the INV-4 grep over ``app/``
# excludes ``test`` so this is fine, but we keep it assembled for hygiene).
_FAKE_KEY = "sk-" + "ant-" + "a" * 40  # noqa: S105 - fixture, not a real secret


def _format(record: logging.LogRecord, redactor: Redactor | None = None) -> dict[str, object]:
    formatter = StructuredLogFormatter(redactor)
    return json.loads(formatter.format(record))


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.runs.launch",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_structured_record_has_envelope() -> None:
    payload = _format(_record("run started"))
    assert payload["message"] == "run started"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.runs.launch"
    assert "timestamp" in payload


def test_log_context_carries_run_issue_session() -> None:
    """AC-11: a record emitted inside a bound context carries the correlation block."""
    with log_context(run_id="run-123", issue="42", session="sess-9"):
        payload = _format(_record("dispatching"))
    context = payload["context"]
    assert isinstance(context, dict)
    for field in LOG_CONTEXT_FIELDS:
        assert field in context
    assert context["run_id"] == "run-123"
    assert context["issue"] == "42"
    assert context["session"] == "sess-9"


def test_otel_attribute_schema_present() -> None:
    """The correlation block is also emitted under OTel attribute keys (N8-ready)."""
    with log_context(run_id="run-123", issue="42", session="sess-9"):
        payload = _format(_record("dispatching"))
    otel = payload["otel"]
    assert isinstance(otel, dict)
    assert otel[OTEL_ATTRIBUTE_KEYS["run_id"]] == "run-123"
    assert otel[OTEL_ATTRIBUTE_KEYS["issue"]] == "42"
    assert otel[OTEL_ATTRIBUTE_KEYS["session"]] == "sess-9"


def test_context_is_merged_and_reset() -> None:
    assert current_log_context() == StructuredLogContext()
    token = bind_log_context(run_id="run-1")
    try:
        with log_context(issue="7"):
            ctx = current_log_context()
            assert ctx.run_id == "run-1"  # merged from the outer bind
            assert ctx.issue == "7"
    finally:
        import app.observability.logging as logging_mod

        logging_mod._LOG_CONTEXT.reset(token)
    # Fully unwound back to empty.
    assert current_log_context() == StructuredLogContext()


def test_secret_in_message_is_redacted() -> None:
    """INV-4: a secret in the log message is scrubbed before persistence."""
    redactor = Redactor(known_values=[_FAKE_KEY])
    payload = _format(_record(f"using key {_FAKE_KEY}"), redactor)
    blob = json.dumps(payload)
    assert _FAKE_KEY not in blob
    assert "[REDACTED]" in blob


def test_secret_in_context_field_is_redacted() -> None:
    """INV-4: a secret arriving via a context/extra value is scrubbed too."""
    redactor = Redactor(known_values=[_FAKE_KEY])
    # Smuggle the secret into the session correlation field (a misuse the formatter
    # must still scrub — the assembled JSON line is redacted as a backstop).
    with log_context(run_id="run-1", session=_FAKE_KEY):
        payload = _format(_record("dispatching"), redactor)
    blob = json.dumps(payload)
    assert _FAKE_KEY not in blob


def test_install_structured_logging_emits_redacted_json() -> None:
    """End-to-end: the installed root logger emits a redacted structured JSON line.

    Binds a ``StringIO`` buffer handler with the StructuredLogFormatter to the root
    logger (the same formatter ``install_structured_logging`` installs) so the test
    reads the emitted line deterministically — pytest's ``capsys`` doesn't capture a
    StreamHandler bound to the original ``sys.stderr`` before capture started.
    """
    import io

    redactor = Redactor(known_values=[_FAKE_KEY])
    # Install the redaction wiring (root filter on all handlers), then attach a
    # captured buffer handler carrying the same structured formatter.
    install_structured_logging(redactor)
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(StructuredLogFormatter(redactor))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        logger = logging.getLogger("app.test.logging")
        with log_context(run_id="run-77", issue="5", session="s1"):
            logger.info("hello %s", _FAKE_KEY)
        handler.flush()
        line = buffer.getvalue().strip().splitlines()[-1]
        payload = json.loads(line)
        assert payload["context"]["run_id"] == "run-77"
        assert _FAKE_KEY not in line
    finally:
        root.removeHandler(handler)
