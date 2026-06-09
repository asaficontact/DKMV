"""Structured, OTel-compatible logging with run/issue/session context (NFR-OBS-1).

Phase 5 / slice 5.3 makes the backend's logs **structured** and **correlatable**:
every log line emitted while handling a run carries the run's ``run_id`` plus the
GitHub ``issue`` and the ``session`` it belongs to, in a JSON shape whose keys map
1:1 onto the OpenTelemetry resource/attribute model. The full OTel GenAI *tracer*
(spans, ``gen_ai.usage.*_tokens``, tail-sampling) is **deferred** (N8) — this
slice ships the structured-log substrate it upgrades **additively** onto, not the
tracer itself.

How correlation flows (no manual threading):

* :func:`bind_log_context` stashes a :class:`StructuredLogContext` in a
  :class:`contextvars.ContextVar`. Because it is a ``ContextVar`` it follows the
  ``asyncio`` task (and any ``run_in_executor`` call that copies the context), so a
  log emitted deep inside a run's pipeline picks the fields up automatically.
* :class:`StructuredLogFormatter` reads the active context for each record and
  emits a single JSON object: a stable envelope (``timestamp``/``level``/
  ``logger``/``message``) plus the OTel-shaped correlation block.

**Redact-before-persist (INV-4).** Structured logs are a persistence sink too, so
:func:`install_structured_logging` installs the Phase-0
:class:`~app.secrets.RedactingLogFilter` alongside the structured formatter. The
filter scrubs the *message* before it is formatted; the formatter additionally
scrubs the assembled JSON line through the same :class:`~app.secrets.Redactor` so a
secret that reached a log *via a context value or an extra field* is removed too.
No secret pattern ever reaches a persisted log line.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from app.secrets import RedactingLogFilter, Redactor

#: The correlation field names carried on every run-scoped log record. Exposed so
#: a test can assert the structured record includes the run/issue/session context
#: (AC-11) and so the INV-4 grep over this module matches only ``run_id`` as a
#: schema key, never a secret being written.
LOG_CONTEXT_FIELDS: tuple[str, ...] = ("run_id", "issue", "session")

#: The OTel-compatible attribute keys the correlation block is emitted under. These
#: are the conventional ``code``/``service`` resource attributes the deferred GenAI
#: tracer (N8) reuses, so adding spans later is an additive upgrade — the log line
#: already speaks the schema. (We keep the platform-native key names too so a human
#: reading a log line does not need the OTel mapping in their head.)
OTEL_ATTRIBUTE_KEYS: dict[str, str] = {
    "run_id": "dkmv.run.id",
    "issue": "dkmv.issue.number",
    "session": "dkmv.session.id",
}


@dataclass(frozen=True, slots=True)
class StructuredLogContext:
    """The per-run correlation fields stamped on every log record for a run.

    ``run_id`` is the platform run UUID; ``issue`` is the GitHub issue number (as a
    string so an unnumbered/synthetic run can carry a non-numeric correlation id);
    ``session`` is the engine session / pipeline-run identifier. All three are
    OTel-compatible *attribute* values — never a secret.
    """

    run_id: str | None = None
    issue: str | None = None
    session: str | None = None

    def as_attributes(self) -> dict[str, Any]:
        """Return the non-empty fields as a flat ``{field: value}`` mapping."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    def as_otel_attributes(self) -> dict[str, Any]:
        """Return the fields keyed by their OTel attribute names (N8-ready)."""
        attrs = self.as_attributes()
        return {OTEL_ATTRIBUTE_KEYS[k]: v for k, v in attrs.items() if k in OTEL_ATTRIBUTE_KEYS}


#: The active log context for the current ``asyncio`` task / call stack. The
#: ``ContextVar`` default is ``None`` (B039 — no mutable/instance default) and
#: :func:`current_log_context` maps an unset context to an empty
#: :class:`StructuredLogContext` (a process-level log carries no run correlation,
#: which is correct — not every log line belongs to a run). The empty instance is a
#: frozen singleton, so there is no per-call allocation on the hot logging path.
_EMPTY_CONTEXT = StructuredLogContext()
_LOG_CONTEXT: contextvars.ContextVar[StructuredLogContext | None] = contextvars.ContextVar(
    "dkmv_log_context",
    default=None,
)


def current_log_context() -> StructuredLogContext:
    """Return the correlation context bound to the current task / call stack."""
    return _LOG_CONTEXT.get() or _EMPTY_CONTEXT


def bind_log_context(
    *,
    run_id: str | None = None,
    issue: str | None = None,
    session: str | None = None,
) -> contextvars.Token[StructuredLogContext | None]:
    """Bind a new correlation context, merging over the current one.

    Returns the :class:`contextvars.Token` so a caller can reset to the prior
    context (``_LOG_CONTEXT.reset(token)``); prefer :func:`log_context` (the
    context manager) which resets automatically.
    """
    current = current_log_context()
    merged = StructuredLogContext(
        run_id=run_id if run_id is not None else current.run_id,
        issue=issue if issue is not None else current.issue,
        session=session if session is not None else current.session,
    )
    return _LOG_CONTEXT.set(merged)


@contextlib.contextmanager
def log_context(
    *,
    run_id: str | None = None,
    issue: str | None = None,
    session: str | None = None,
) -> Iterator[StructuredLogContext]:
    """Bind run/issue/session correlation for the duration of the ``with`` block.

    Every log record emitted inside the block (including from awaited coroutines on
    the same task) carries the bound fields; on exit the prior context is restored.
    """
    token = bind_log_context(run_id=run_id, issue=issue, session=session)
    try:
        yield current_log_context()
    finally:
        _LOG_CONTEXT.reset(token)


class StructuredLogFormatter(logging.Formatter):
    """Emit each log record as a single redacted JSON line with OTel correlation.

    The line shape::

        {
          "timestamp": "...Z",        # ISO-8601 UTC
          "level": "INFO",
          "logger": "app.runs.launch",
          "message": "...",
          "context": {"run_id": "...", "issue": "...", "session": "..."},
          "otel": {"dkmv.run.id": "...", ...},   # OTel attribute keys (N8-ready)
          ...extra fields...
        }

    The context block is sourced from the active :class:`StructuredLogContext` (so a
    record never has to pass it explicitly). Any non-standard attribute set on the
    record via ``logger.info(..., extra={...})`` is included verbatim. The whole
    assembled line is scrubbed through the :class:`~app.secrets.Redactor` before it
    is returned (INV-4) so a secret that arrived via a context value or an extra
    field cannot survive into the persisted line.
    """

    #: ``logging.LogRecord`` attributes that are part of the standard envelope and
    #: therefore not re-emitted as ad-hoc "extra" fields.
    _RESERVED: frozenset[str] = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "taskName",
            "message",
            "asctime",
        }
    )

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self._redactor = redactor or Redactor()

    def format(self, record: logging.LogRecord) -> str:
        context = current_log_context()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        attributes = context.as_attributes()
        if attributes:
            payload["context"] = attributes
            payload["otel"] = context.as_otel_attributes()
        # Ad-hoc structured fields passed via ``extra=`` (e.g. a metric/gauge) are
        # carried verbatim so a caller can attach typed observability data.
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        line = json.dumps(payload, default=str, ensure_ascii=False)
        # Redact the *assembled* line so a secret arriving via a context/extra value
        # is scrubbed even though the raw message was clean (INV-4 — log is a sink).
        return self._redactor.text(line)


#: Marker attribute set on the structured handler this function installs so a
#: re-install can find + reuse its own handler (idempotent) without clobbering a
#: handler the host process / a test attached to the root logger.
_STRUCTURED_HANDLER_ATTR = "_dkmv_structured_handler"


def install_structured_logging(
    redactor: Redactor | None = None,
    *,
    level: int = logging.INFO,
) -> StructuredLogFormatter:
    """Configure the root logger for structured, redacted, OTel-shaped logs.

    Adds (once) a single structured ``StreamHandler`` carrying the
    :class:`StructuredLogFormatter` to the root logger, and installs a
    :class:`~app.secrets.RedactingLogFilter` on **every** root handler (the
    structured one AND any the host process / uvicorn / a test attached) plus the
    root logger itself, so the *message* is scrubbed before formatting and the
    *assembled JSON line* is scrubbed by the formatter — the two-layer INV-4
    backstop. It does **not** remove pre-existing handlers (boot ordering: the
    process's log handlers exist before the app factory runs, and they must stay +
    get the redaction filter). Idempotent: a re-install reuses its own marked
    handler instead of stacking a second. Returns the formatter for tests.
    """
    used = redactor or Redactor()
    root = logging.getLogger()
    root.setLevel(level)
    formatter = StructuredLogFormatter(used)

    # Reuse our own previously-installed structured handler if present (idempotent);
    # otherwise add one. Never touch handlers we did not install.
    existing = next(
        (h for h in root.handlers if getattr(h, _STRUCTURED_HANDLER_ATTR, False)),
        None,
    )
    if existing is None:
        handler: logging.Handler = logging.StreamHandler()
        setattr(handler, _STRUCTURED_HANDLER_ATTR, True)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    else:
        existing.setFormatter(formatter)

    # Attach the message-level redaction filter to the root logger AND every handler
    # (ours + any pre-existing), so no record — direct or propagated — escapes
    # un-scrubbed (INV-4). De-dup so a re-install does not stack filters.
    log_filter = RedactingLogFilter(used)
    if log_filter not in root.filters:
        root.addFilter(log_filter)
    for handler in root.handlers:
        if not any(isinstance(f, RedactingLogFilter) for f in handler.filters):
            handler.addFilter(log_filter)
    return formatter


def get_logger(name: str) -> logging.Logger:
    """Return a module logger (thin ``logging.getLogger`` wrapper).

    Module loggers propagate to the root logger configured by
    :func:`install_structured_logging`, so they inherit the structured formatter +
    redaction without per-module setup.
    """
    return logging.getLogger(name)
