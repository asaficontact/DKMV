"""Audit-log tests — the four §8.6 kinds + INV-4 secret hygiene (AC-12).

Asserts the durable audit sink records each of the four §8.6 event kinds — run
launches, token mint/use, egress denials, decision resolutions — and that **no
secret literal** is ever written to a record (redact-before-persist, INV-4).
Exercises both the :class:`MemoryAuditSink` (structured-record assertions) and the
:class:`FileAuditSink` (durable JSONL round-trip).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.executor.egress import EgressPolicy, audit_egress_denials
from app.secrets import Redactor
from app.secrets.github_token import GitHubTokenMinter
from app.security import (
    AuditEventKind,
    AuditLog,
    FileAuditSink,
    MemoryAuditSink,
)
from app.security.audit import AuditRecord

# A non-real secret literal (assembled from fragments so the INV-4 grep over
# ``app/`` never flags this test file as a secret being written to a log).
_FAKE_PAT = "ghp" + "_" + "A" * 36  # noqa: S105 - fixture, not a real secret


def _audit_with_redactor() -> tuple[AuditLog, MemoryAuditSink]:
    sink = MemoryAuditSink()
    redactor = Redactor(known_values=[_FAKE_PAT])
    return AuditLog(sink, redactor=redactor), sink


def test_records_run_launch() -> None:
    audit, sink = _audit_with_redactor()
    audit.record_run_launch(run_id="run-1", repo="acme/app", issue=42, agent="claude")
    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.kind is AuditEventKind.RUN_LAUNCH
    assert rec.run_id == "run-1"
    assert rec.details["repo"] == "acme/app"
    assert rec.details["issue"] == 42
    assert rec.details["agent"] == "claude"


def test_records_token_mint_and_use() -> None:
    audit, sink = _audit_with_redactor()
    expires = datetime.now(UTC) + timedelta(hours=1)
    audit.record_token_mint(run_id="run-2", repo="acme/app", expires_at=expires)
    audit.record_token_use(run_id="run-2", repo="acme/app", allowed=True)
    kinds = [r.kind for r in sink.records]
    assert AuditEventKind.TOKEN_MINT in kinds
    assert AuditEventKind.TOKEN_USE in kinds
    mint = next(r for r in sink.records if r.kind is AuditEventKind.TOKEN_MINT)
    assert mint.details["repo"] == "acme/app"
    assert "expires_at" in mint.details
    use = next(r for r in sink.records if r.kind is AuditEventKind.TOKEN_USE)
    assert use.details["allowed"] is True


def test_records_token_grant() -> None:
    """The real v1 GitHub-credential event: the platform granted a run repo access."""
    audit, sink = _audit_with_redactor()
    expires = datetime.now(UTC) + timedelta(hours=1)
    audit.record_token_grant(run_id="run-g", repo="acme/app", expires_at=expires)
    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.kind is AuditEventKind.TOKEN_GRANT
    assert rec.run_id == "run-g"
    assert rec.details["repo"] == "acme/app"
    assert rec.details["scope"] == "repo"
    assert "expires_at" in rec.details


def test_records_egress_denial() -> None:
    audit, sink = _audit_with_redactor()
    audit.record_egress_denial(host="evil.example.com", run_id="run-3")
    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.kind is AuditEventKind.EGRESS_DENIAL
    assert rec.details["host"] == "evil.example.com"
    assert rec.details["decision"] == "denied"


def test_records_decision_resolution() -> None:
    audit, sink = _audit_with_redactor()
    audit.record_decision_resolution(
        run_id="run-4",
        decision_id="dec-1",
        resolved_by="human",
        skip_remaining=False,
    )
    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.kind is AuditEventKind.DECISION_RESOLUTION
    assert rec.details["decision_id"] == "dec-1"
    assert rec.details["resolved_by"] == "human"


def test_all_four_kinds_recorded() -> None:
    """The binding AC-12 assertion: all four §8.6 kinds are recordable."""
    audit, sink = _audit_with_redactor()
    audit.record_run_launch(run_id="r", repo="acme/app", issue=1, agent="claude")
    audit.record_token_grant(run_id="r", repo="acme/app")
    audit.record_token_mint(run_id="r", repo="acme/app")
    audit.record_token_use(run_id="r", repo="acme/app", allowed=False)
    audit.record_egress_denial(host="evil.example.com", run_id="r")
    audit.record_decision_resolution(run_id="r", decision_id="d", resolved_by="timeout")
    kinds = {r.kind for r in sink.records}
    # The §8.6 audit kinds. ``token_grant`` is the v1 real GitHub-credential event;
    # mint/use remain in the contract for the deferred App model (ADR-P004).
    assert AuditEventKind.RUN_LAUNCH in kinds
    assert AuditEventKind.TOKEN_GRANT in kinds
    assert AuditEventKind.TOKEN_MINT in kinds
    assert AuditEventKind.TOKEN_USE in kinds
    assert AuditEventKind.EGRESS_DENIAL in kinds
    assert AuditEventKind.DECISION_RESOLUTION in kinds


def test_no_secret_literal_written() -> None:
    """INV-4: a secret value handed to an audit detail is REDACTED, never persisted."""
    audit, sink = _audit_with_redactor()
    # Simulate a call site that (wrongly) tries to stash a token value in a detail —
    # the redactor must scrub it before persistence.
    audit.record_run_launch(
        run_id="run-x",
        repo="acme/app",
        issue=7,
        agent=f"claude {_FAKE_PAT}",  # secret smuggled into a field
    )
    rec = sink.records[0]
    blob = json.dumps(rec.to_json())
    assert _FAKE_PAT not in blob
    assert "[REDACTED]" in blob


def test_file_sink_durable_round_trip(tmp_path: Path) -> None:
    """The FileAuditSink writes JSONL that round-trips (durable, §6.5)."""
    path = tmp_path / "audit.log"
    audit = AuditLog(FileAuditSink(path), redactor=Redactor(known_values=[_FAKE_PAT]))
    audit.record_run_launch(run_id="run-9", repo="acme/app", issue=3, agent="codex")
    audit.record_egress_denial(host="bad.example.com", run_id="run-9")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["kind"] == "run_launch"
    assert parsed[1]["kind"] == "egress_denial"
    # No secret literal anywhere in the persisted file (INV-4).
    assert _FAKE_PAT not in path.read_text(encoding="utf-8")


def test_audit_path_co_located_with_db() -> None:
    """The file sink lands next to the single SQLite file (§6.5 source of truth)."""
    audit = AuditLog.from_database_url("sqlite:///./data/dkmv.db")
    # The composed sink is a FileAuditSink whose path is ./data/audit.log.
    assert isinstance(audit._sink, FileAuditSink)  # type: ignore[attr-defined]  # DKMVP-ESCAPE: white-box assert on the composed sink path
    assert audit._sink.path == Path("./data/audit.log")  # type: ignore[attr-defined]  # DKMVP-ESCAPE: same


def test_egress_audit_helper_records_denied_hosts() -> None:
    """The executor/egress seam records each denied host to the audit trail (INV-3)."""
    audit, sink = _audit_with_redactor()
    policy = EgressPolicy(hosts=("github.com", "api.anthropic.com"))
    denied = audit_egress_denials(
        policy,
        ["api.github.com", "evil.example.com", "exfil.test"],
        audit=audit,
        run_id="run-5",
    )
    assert denied == ["evil.example.com", "exfil.test"]
    recorded_hosts = {r.details["host"] for r in sink.records}
    assert recorded_hosts == {"evil.example.com", "exfil.test"}
    assert all(r.kind is AuditEventKind.EGRESS_DENIAL for r in sink.records)


def test_token_minter_records_mint_and_use(tmp_path: Path) -> None:
    """The token minter/use path records mint + use, never the token value (INV-4)."""
    import asyncio

    from app.db import Repository
    from app.secrets.store import SecretStore

    from tests.conftest import _migrate

    async def _run() -> None:
        url = _migrate(tmp_path / "tok.db")
        repository = Repository(url)
        await repository.start()
        try:
            store = SecretStore(repository, key=SecretStore.generate_key())
            audit, sink = _audit_with_redactor()
            minter = GitHubTokenMinter(store, base_token=_FAKE_PAT)
            token = await minter.mint("acme/app", run_id="run-6", audit=audit)
            token.authorize_push("acme/app", audit=audit, run_id="run-6")
            kinds = {r.kind for r in sink.records}
            assert AuditEventKind.TOKEN_MINT in kinds
            assert AuditEventKind.TOKEN_USE in kinds
            # No record carries the token value (INV-4).
            blob = json.dumps([r.to_json() for r in sink.records])
            assert _FAKE_PAT not in blob
        finally:
            await repository.close()

    asyncio.run(_run())


def test_run_service_start_records_real_token_grant_in_production(tmp_path: Path) -> None:
    """AC-12 (honest, ADR-P004): the PRODUCTION run-launch path (``RunService.start``)
    records the **real** ``token_grant`` audit kind — the genuine "platform granted run
    X access to repo Y" decision as the credential is provisioned into RuntimeConfig.

    The previous FIX-2 fabricated a ``token_mint`` + ``token_use`` for a token that was
    never consumed (the engine's GitHub credential is the operator PAT threaded into
    RuntimeConfig independently). This asserts the honest grant instead: it is recorded,
    correlated to the real ``run_id``, carries no raw PAT (INV-4), and that the fake
    mint/use are **gone** from the launch path."""
    import asyncio
    from typing import Any

    from app.db import Repository
    from app.runtime import RunService
    from app.secrets.store import SecretStore

    from tests.conftest import _migrate, make_settings

    class _FakeRuntime:
        def __init__(self) -> None:
            self.started = False

        async def start(self, *, component: str, source: Any, **kwargs: Any) -> str:
            self.started = True
            return "handle"

    async def _run() -> None:
        url = _migrate(tmp_path / "rs.db")
        repository = Repository(url)
        await repository.start()
        try:
            settings = make_settings(
                OUTPUT_DIR=tmp_path / "out",
                GITHUB_TOKEN=_FAKE_PAT,
            )
            store = SecretStore(repository, key=SecretStore.generate_key())
            audit, sink = _audit_with_redactor()
            runtime = _FakeRuntime()
            service = RunService(settings, runtime=runtime)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed fake engine
            # The lifespan injection that turns the dormant hook live in production.
            service.bind_run_token_minting(secret_store=store, audit=audit)
            await service.start(
                component="dev",
                repo="acme/app",
                branch="dkmv/issue-1",
                feature_name="widget",
                run_id="run-prod-1",
            )
            assert runtime.started
            kinds = {r.kind for r in sink.records}
            # The REAL event: a credential grant correlated to the run.
            assert AuditEventKind.TOKEN_GRANT in kinds
            grant = next(r for r in sink.records if r.kind is AuditEventKind.TOKEN_GRANT)
            assert grant.run_id == "run-prod-1"
            assert grant.details["repo"] == "acme/app"
            assert grant.details["scope"] == "repo"
            # The fabricated (non-consumed) mint/use must NOT be emitted by the launch path.
            assert AuditEventKind.TOKEN_MINT not in kinds
            assert AuditEventKind.TOKEN_USE not in kinds
            # No record carries the raw operator PAT (INV-4).
            blob = json.dumps([r.to_json() for r in sink.records])
            assert _FAKE_PAT not in blob
        finally:
            await repository.close()

    asyncio.run(_run())


def test_run_service_start_without_github_token_skips_grant(tmp_path: Path) -> None:
    """No operator GITHUB_TOKEN → nothing was granted → start is a graceful no-op."""
    import asyncio
    from typing import Any

    from app.db import Repository
    from app.runtime import RunService
    from app.secrets.store import SecretStore

    from tests.conftest import _migrate, make_settings

    class _FakeRuntime:
        async def start(self, *, component: str, source: Any, **kwargs: Any) -> str:
            return "handle"

    async def _run() -> None:
        url = _migrate(tmp_path / "rs2.db")
        repository = Repository(url)
        await repository.start()
        try:
            settings = make_settings(OUTPUT_DIR=tmp_path / "out", GITHUB_TOKEN="")
            store = SecretStore(repository, key=SecretStore.generate_key())
            audit, sink = _audit_with_redactor()
            service = RunService(settings, runtime=_FakeRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed fake engine
            service.bind_run_token_minting(secret_store=store, audit=audit)
            await service.start(component="dev", repo="acme/app", run_id="run-x")
            assert sink.records == []
        finally:
            await repository.close()

    asyncio.run(_run())


def test_run_service_start_without_run_id_skips_grant(tmp_path: Path) -> None:
    """Absent ``run_id`` → no correlation → the grant is skipped (honest docstring)."""
    import asyncio
    from typing import Any

    from app.db import Repository
    from app.runtime import RunService
    from app.secrets.store import SecretStore

    from tests.conftest import _migrate, make_settings

    class _FakeRuntime:
        async def start(self, *, component: str, source: Any, **kwargs: Any) -> str:
            return "handle"

    async def _run() -> None:
        url = _migrate(tmp_path / "rs3.db")
        repository = Repository(url)
        await repository.start()
        try:
            settings = make_settings(OUTPUT_DIR=tmp_path / "out", GITHUB_TOKEN=_FAKE_PAT)
            store = SecretStore(repository, key=SecretStore.generate_key())
            audit, sink = _audit_with_redactor()
            service = RunService(settings, runtime=_FakeRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed fake engine
            service.bind_run_token_minting(secret_store=store, audit=audit)
            await service.start(component="dev", repo="acme/app")  # no run_id
            assert sink.records == []
        finally:
            await repository.close()

    asyncio.run(_run())


def test_file_audit_sink_created_with_restrictive_mode(tmp_path: Path) -> None:
    """FIX-4: the durable audit file is created 0o600 (owner-only), not the process umask."""
    import stat

    sink = FileAuditSink(tmp_path / "nested" / "audit.log")
    sink.write(AuditRecord(kind=AuditEventKind.RUN_LAUNCH, timestamp="2026-01-01T00:00:00+00:00"))
    mode = stat.S_IMODE((tmp_path / "nested" / "audit.log").stat().st_mode)
    # No group/world bits — owner read/write only.
    assert mode & 0o077 == 0
    assert mode & 0o600 == 0o600
