"""Durable audit log — a security-evidence trail, separate from the event stream (§8.6).

§8.6 calls for an audit log that records the **security-relevant** actions the
control plane takes, distinct from the per-run agent ``events`` stream (which is a
debug/observability feed). The kinds recorded here (AC-12) are:

* ``run_launch`` — a run was dispatched (who/what/which repo + agent);
* ``token_grant`` — the platform **provisioned** a run's GitHub credential into its
  ``RuntimeConfig`` (the *fact* that run X was granted access to repo Y + the
  scope/TTL of the operator PAT, **never the token value**). This is the one real,
  platform-observable GitHub-credential security decision in v1 (see the deferral
  note below);
* ``token_mint`` / ``token_use`` — the deferred fine-grained GitHub-App model's
  per-run mint / in-container push-use telemetry (scope + TTL / allowed-denied,
  **never the token value**). These remain in the contract for the App model but
  are **not** emitted by the v1 launch path, which audits the real ``token_grant``;
* ``egress_denial`` — the network-layer egress allowlist blocked a host (the
  exfiltration-attempt signal — INV-3);
* ``decision_resolution`` — a HITL pause was resolved (human or timeout), incl. the
  irreversible PR-push approval gate (NFR-SEC-5).

**Honest v1 credential model (ADR-P004).** v1 threads the operator's fine-grained
PAT into the engine's ``RuntimeConfig``; the engine clones/pushes **inside the
gVisor container** with that PAT, so a true per-run *mint* and the in-container
*use* are **not observable in platform Python**. Fine-grained per-run token
*minting* (the GitHub-App installation-token model) and in-container push-*use*
telemetry are **deferred post-v1** (like the egress-denial proxy hook). The one
genuine, auditable GitHub-credential event the platform performs is **granting a
run access to a repo** — provisioning the credential into the run's
``RuntimeConfig`` — recorded here as ``token_grant``.

**Redact-before-persist (INV-4).** The audit log is a persistence sink, so every
record is scrubbed through the Phase-0 :class:`~app.secrets.Redactor` before it is
written. A leak into the audit trail is as permanent as one into ``events``; the
sink never receives a raw secret because (a) call sites pass scope/metadata, not
credential values, and (b) the redactor is a backstop over the whole record.

**Durability.** The default sink appends one JSON object per line (JSONL) to an
``audit.log`` file co-located with the single SQLite DB — §6.5's "the single file
is the source of truth for spend + audit". The append is fsync-guarded so a record
survives a crash. A :class:`MemoryAuditSink` is provided for tests. Both implement
the same :class:`AuditSink` protocol so the wiring (``app.state.audit``) is
sink-agnostic. The sink is intentionally **fire-and-forget safe**: a write failure
is swallowed + logged so an audit-IO error never blocks a run launch or a security
control (the control still happens; only its evidence line is lost).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.secrets import Redactor

_log = logging.getLogger(__name__)


class AuditEventKind(StrEnum):
    """The §8.6 audit-event kinds (AC-12). String-valued for JSONL fidelity."""

    RUN_LAUNCH = "run_launch"
    #: The v1 GitHub-credential security decision: the platform provisioned a run's
    #: credential into its RuntimeConfig (granted run X access to repo Y).
    TOKEN_GRANT = "token_grant"
    #: Deferred GitHub-App model (ADR-P004): per-run mint / in-container push-use
    #: telemetry. Kept in the contract; NOT emitted by the v1 launch path.
    TOKEN_MINT = "token_mint"
    TOKEN_USE = "token_use"
    EGRESS_DENIAL = "egress_denial"
    DECISION_RESOLUTION = "decision_resolution"


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One audit-trail entry: a timestamp, a kind, and a redacted detail mapping.

    ``timestamp`` is UTC ISO-8601. ``kind`` is one of the four (+ the two token
    sub-kinds) :class:`AuditEventKind` values. ``run_id`` / ``actor`` are pulled out
    as top-level correlation fields (so a security review can filter a run's trail);
    ``details`` carries the rest (repo, agent, scope, host, decision id, …). The
    record is **already redacted** by the sink before persistence (INV-4).
    """

    kind: AuditEventKind
    timestamp: str
    run_id: str | None = None
    actor: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-able dict (the one-line JSONL record shape)."""
        out: dict[str, Any] = {
            "timestamp": self.timestamp,
            "kind": self.kind.value,
        }
        if self.run_id is not None:
            out["run_id"] = self.run_id
        if self.actor is not None:
            out["actor"] = self.actor
        if self.details:
            out["details"] = self.details
        return out


@runtime_checkable
class AuditSink(Protocol):
    """A durable audit-record sink (file / memory / future DB)."""

    def write(self, record: AuditRecord) -> None:
        """Persist a (pre-redacted) audit record durably."""
        ...


@runtime_checkable
class ReadableAuditSink(Protocol):
    """An :class:`AuditSink` that can also be **read back** (G10 — the ``/audit`` feed).

    The audit trail is collected durably but was unreachable; the ``GET /audit``
    read endpoint surfaces it. Only a sink that can replay its records implements
    this (the file + memory sinks do); a write-only sink need not. Records come back
    NEWEST-FIRST + paginated (``limit``/``offset``) so the read is bounded — the file
    can grow unboundedly. The records are **already redacted** at write time (INV-4),
    so the read returns them as-is — no secret can appear.
    """

    def read_records(self, *, limit: int, offset: int) -> tuple[list[AuditRecord], int]:
        """Return ``(records_newest_first, total_count)`` for one page."""
        ...


class MemoryAuditSink:
    """In-memory :class:`AuditSink` for tests — keeps records on a list (+ readable)."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def write(self, record: AuditRecord) -> None:
        self.records.append(record)

    def read_records(self, *, limit: int, offset: int) -> tuple[list[AuditRecord], int]:
        """Return one newest-first page over the in-memory list (G10 read seam)."""
        newest_first = list(reversed(self.records))
        total = len(newest_first)
        return newest_first[offset : offset + limit], total


class FileAuditSink:
    """JSONL :class:`AuditSink` appending fsync-guarded lines to an ``audit.log``.

    One JSON object per line, appended + flushed + fsync'd so a record survives a
    crash. A write failure is swallowed (logged at WARNING) so an audit-IO error
    never blocks the security control whose evidence it is recording.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def read_records(self, *, limit: int, offset: int) -> tuple[list[AuditRecord], int]:
        """Read one newest-first page of the JSONL trail (G10 — the ``/audit`` feed).

        Reads the whole ``audit.log`` (one JSON object per line), reverses to
        newest-first, and slices ``[offset : offset + limit]``. Records are already
        redacted at write time (INV-4), so this returns them verbatim — no secret can
        appear. A missing file (nothing audited yet) → ``([], 0)`` gracefully. A
        malformed line (a partial write on a crash) is skipped rather than failing the
        whole read. ``total`` is the count of well-formed records (the pagination
        denominator).
        """
        try:
            with open(self._path, encoding="utf-8") as handle:
                raw_lines = handle.readlines()
        except FileNotFoundError:
            return [], 0
        except OSError:  # pragma: no cover - defensive: a read error degrades to empty
            _log.warning("audit read failed for %s", self._path, exc_info=True)
            return [], 0
        records: list[AuditRecord] = []
        for raw in raw_lines:
            text = raw.strip()
            if not text:
                continue
            record = _record_from_json_line(text)
            if record is not None:
                records.append(record)
        records.reverse()  # newest-first
        total = len(records)
        return records[offset : offset + limit], total

    def write(self, record: AuditRecord) -> None:
        line = json.dumps(record.to_json(), default=str, ensure_ascii=False)
        try:
            # Open/create the durable evidence file with an explicit restrictive
            # mode (0o600 — owner read/write only) rather than the inherited process
            # umask, so the audit trail (a security-sensitive record of token mints,
            # egress denials, and HITL approvals) is not group/world-readable on a
            # multi-user host. ``os.open`` + ``O_APPEND|O_CREAT`` applies the mode
            # only on creation; an existing file keeps its (already-restrictive) mode.
            fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:  # pragma: no cover - defensive: never break a control on audit IO
            _log.warning("audit write failed for kind=%s", record.kind.value, exc_info=True)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _record_from_json_line(text: str) -> AuditRecord | None:
    """Parse one JSONL line back into an :class:`AuditRecord`, or ``None`` if malformed.

    The inverse of :meth:`AuditRecord.to_json`. A line whose ``kind`` is not a known
    :class:`AuditEventKind` (a forward-compat / corrupt line) or that does not parse
    is skipped (returns ``None``) so a single bad line never breaks the whole read.
    The line was redacted before it was written (INV-4), so the reconstructed record
    is already secret-free.
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw_kind = data.get("kind")
    if not isinstance(raw_kind, str):
        return None
    try:
        kind = AuditEventKind(raw_kind)
    except ValueError:
        return None
    timestamp = data.get("timestamp")
    if not isinstance(timestamp, str):
        return None
    details = data.get("details")
    return AuditRecord(
        kind=kind,
        timestamp=timestamp,
        run_id=data.get("run_id"),
        actor=data.get("actor"),
        details=details if isinstance(details, dict) else {},
    )


class AuditLog:
    """The audit-recording facade the call sites use (run launch / token / egress / HITL).

    Wraps a durable :class:`AuditSink` with a :class:`~app.secrets.Redactor` so every
    record is scrubbed before persistence (INV-4). Exposes one method per §8.6 audit
    kind so a call site records the *fact* with structured, secret-free metadata —
    never a credential value. The methods are synchronous + swallow sink errors, so
    they are safe to call from any path (a launch, a token mint, the egress decision,
    the HITL resolve) without awaiting or risking that an audit failure aborts the
    control.
    """

    def __init__(self, sink: AuditSink, *, redactor: Redactor | None = None) -> None:
        self._sink = sink
        self._redactor = redactor or Redactor()

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
        *,
        redactor: Redactor | None = None,
    ) -> AuditLog:
        """Build a :class:`FileAuditSink`-backed audit log co-located with the DB.

        Resolves ``audit.log`` next to the single SQLite file (``sqlite:///<path>``)
        so the audit trail lives in the same data dir as the spend source of truth
        (§6.5). A non-file URL (or an in-memory DB) falls back to ``./data/audit.log``.
        """
        path = _audit_path_for_database_url(database_url)
        return cls(FileAuditSink(path), redactor=redactor)

    def read_records(self, *, limit: int, offset: int) -> tuple[list[AuditRecord], int]:
        """Return one newest-first page of the trail, or ``([], 0)`` if not readable (G10).

        The ``GET /audit`` read seam: delegates to the underlying sink when it is a
        :class:`ReadableAuditSink` (the file + memory sinks). The records were redacted
        before they were written (INV-4), so they are returned verbatim — no secret can
        appear. A write-only / future sink that cannot replay degrades to an empty page
        (the endpoint then reports "no audit trail available") rather than erroring.
        """
        if isinstance(self._sink, ReadableAuditSink):
            return self._sink.read_records(limit=limit, offset=offset)
        return [], 0

    def _record(
        self,
        kind: AuditEventKind,
        *,
        run_id: str | None,
        actor: str | None,
        details: dict[str, Any],
    ) -> None:
        # Redact the whole detail mapping (+ the correlation fields) before persist.
        safe_details = self._redactor.payload(details) if details else {}
        record = AuditRecord(
            kind=kind,
            timestamp=_utc_now_iso(),
            run_id=self._redactor.text(run_id) if run_id else None,
            actor=self._redactor.text(actor) if actor else None,
            details=safe_details,
        )
        self._sink.write(record)

    # ── The four §8.6 audit kinds (AC-12) ────────────────────────────────────

    def record_run_launch(
        self,
        *,
        run_id: str,
        repo: str,
        issue: int | str | None = None,
        agent: str | None = None,
        workflow_id: str | None = None,
        actor: str = "platform",
    ) -> None:
        """Record that a run was dispatched (the run-launch evidence line)."""
        details: dict[str, Any] = {"repo": repo}
        if issue is not None:
            details["issue"] = issue
        if agent is not None:
            details["agent"] = agent
        if workflow_id is not None:
            details["workflow_id"] = workflow_id
        self._record(
            AuditEventKind.RUN_LAUNCH,
            run_id=run_id,
            actor=actor,
            details=details,
        )

    def record_token_grant(
        self,
        *,
        run_id: str,
        repo: str,
        scope: str = "repo",
        expires_at: datetime | str | None = None,
        actor: str = "platform",
    ) -> None:
        """Record that the platform granted a run access to ``repo`` (the v1 real event).

        This is the genuine, platform-observable GitHub-credential security decision:
        the platform provisioned the run's credential into its ``RuntimeConfig``, i.e.
        granted run ``run_id`` access to ``repo``. The record carries only the *fact*
        plus the credential's ``scope`` (the operator PAT's repo scope) and optional
        ``expires_at`` TTL metadata — **never the token value** (INV-4; the redactor is
        a backstop over the whole record). The deferred GitHub-App per-run *mint* and
        in-container *use* telemetry (``token_mint`` / ``token_use``) are NOT emitted by
        v1 — this honest grant record stands in their place (see the module docstring +
        ADR-P004).
        """
        details: dict[str, Any] = {"repo": repo, "scope": scope}
        if expires_at is not None:
            details["expires_at"] = (
                expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
            )
        self._record(
            AuditEventKind.TOKEN_GRANT,
            run_id=run_id,
            actor=actor,
            details=details,
        )

    def record_token_mint(
        self,
        *,
        run_id: str,
        repo: str,
        expires_at: datetime | str | None = None,
        actor: str = "platform",
    ) -> None:
        """Record a deferred GitHub-App per-run token mint (scope + TTL, never value).

        Part of the deferred fine-grained-App credential model (ADR-P004); **not**
        emitted by the v1 launch path, which records the real ``token_grant`` instead.
        Retained so the App-model call sites (post-v1) and the Phase-0 minter machinery
        keep a stable seam.
        """
        details: dict[str, Any] = {"repo": repo}
        if expires_at is not None:
            details["expires_at"] = (
                expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
            )
        self._record(
            AuditEventKind.TOKEN_MINT,
            run_id=run_id,
            actor=actor,
            details=details,
        )

    def record_token_use(
        self,
        *,
        run_id: str,
        repo: str,
        allowed: bool,
        actor: str = "platform",
    ) -> None:
        """Record a deferred GitHub-App in-container push-use attempt (allowed/denied).

        Part of the deferred credential model (ADR-P004); **not** emitted by the v1
        launch path (the in-container push USE is not observable in platform Python).
        Retained for the Phase-0 :class:`~app.secrets.github_token.MintedToken`
        ``authorize_push`` guard + the post-v1 App model. Never records the value.
        """
        self._record(
            AuditEventKind.TOKEN_USE,
            run_id=run_id,
            actor=actor,
            details={"repo": repo, "allowed": allowed},
        )

    def record_egress_denial(
        self,
        *,
        host: str,
        run_id: str | None = None,
        actor: str = "egress-proxy",
    ) -> None:
        """Record that the egress allowlist blocked a host (the exfil signal — INV-3)."""
        self._record(
            AuditEventKind.EGRESS_DENIAL,
            run_id=run_id,
            actor=actor,
            details={"host": host, "decision": "denied"},
        )

    def record_decision_resolution(
        self,
        *,
        run_id: str,
        decision_id: str,
        resolved_by: str,
        skip_remaining: bool = False,
        actor: str = "human",
    ) -> None:
        """Record a HITL pause resolution (incl. the NFR-SEC-5 PR-push approval gate)."""
        self._record(
            AuditEventKind.DECISION_RESOLUTION,
            run_id=run_id,
            actor=actor,
            details={
                "decision_id": decision_id,
                "resolved_by": resolved_by,
                "skip_remaining": skip_remaining,
            },
        )


def _audit_path_for_database_url(database_url: str) -> Path:
    """Resolve the ``audit.log`` path co-located with a ``sqlite:///<path>`` DB."""
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        raw = database_url[len(prefix) :]
        # In-memory / shared-cache URLs have no on-disk dir; fall back below.
        if raw and ":memory:" not in raw:
            db_path = Path(raw)
            return db_path.parent / "audit.log"
    return Path("./data/audit.log")
