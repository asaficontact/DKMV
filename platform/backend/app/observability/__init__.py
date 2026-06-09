"""Observability surface (NFR-OBS-1 / §8.6): structured, OTel-compatible logs.

Public surface:

* :class:`StructuredLogContext` — the per-run ``run_id`` / ``issue`` / ``session``
  correlation fields carried on every log record for a run (the OTel-compatible
  resource/attribute schema the deferred GenAI tracer — N8 — upgrades additively).
* :func:`bind_log_context` / :func:`current_log_context` — bind/read the active
  context via a :class:`contextvars.ContextVar` so a log emitted anywhere inside a
  run's task carries the correlation fields without threading them by hand.
* :func:`install_structured_logging` — configure the root logger with the JSON
  structured formatter **plus** the redact-before-persist filter (INV-4) so no log
  line can carry a secret.
* :func:`get_logger` — a thin ``logging.getLogger`` wrapper for module loggers.

This is logs only. The full OpenTelemetry GenAI tracer (spans, ``gen_ai.usage.*``)
is deferred (N8); the schema here is chosen so adding it later is additive, not a
rewrite.
"""

from __future__ import annotations

from app.observability.logging import (
    LOG_CONTEXT_FIELDS,
    StructuredLogContext,
    StructuredLogFormatter,
    bind_log_context,
    current_log_context,
    get_logger,
    install_structured_logging,
    log_context,
)

__all__ = [
    "LOG_CONTEXT_FIELDS",
    "StructuredLogContext",
    "StructuredLogFormatter",
    "bind_log_context",
    "current_log_context",
    "get_logger",
    "install_structured_logging",
    "log_context",
]
