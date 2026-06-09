"""Security surface: app access control (INV-1) + the durable audit log (§8.6).

* :class:`AccessControlMiddleware` — the loopback + local-token + ``Host``/``Origin``
  + CSRF gate (the control plane reaches a root-equivalent Docker socket and
  launches money-spending runs — PRD NFR-SEC-2).
* :class:`AuditLog` + the :class:`AuditSink` implementations — the §8.6
  security-evidence trail (run launches, token mint/use, egress denials, decision
  resolutions), redact-before-persist (INV-4), separate from the agent event stream.
"""

from __future__ import annotations

from app.security.access_control import AccessControlMiddleware
from app.security.audit import (
    AuditEventKind,
    AuditLog,
    AuditRecord,
    AuditSink,
    FileAuditSink,
    MemoryAuditSink,
)

__all__ = [
    "AccessControlMiddleware",
    "AuditEventKind",
    "AuditLog",
    "AuditRecord",
    "AuditSink",
    "FileAuditSink",
    "MemoryAuditSink",
]
