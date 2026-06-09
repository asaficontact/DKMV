"""§13 e2e — AT-Isolation + AT-Security: gVisor runsc, egress allowlist deny,
repo-scoped token, and secret-free events/logs/audit (AC-15 / INV-3/4).

The brief's HONEST live-vs-skipped split:

* The **in-process** half ALWAYS runs — it asserts the *configuration* (the release
  config pins ``SANDBOX_RUNTIME=runsc`` + ``EGRESS_ALLOWLIST`` on) and the
  *Python-level enforcement*: the egress policy DENIES a non-allowlisted host, the
  repo-scoped run token REFUSES a foreign-repo push, and the redactor keeps
  events/logs/audit secret-free.
* The **live-container** half (a real sandboxed run started under runsc, a real
  egress-deny observed over the wire) is GATED behind a Docker/runsc-availability
  ``skipif`` (:mod:`tests.e2e.gating`) that self-skips — reported as SKIPPED, never
  faked, never silently passed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from app.config import Settings
from app.db import EventRecord, Repository
from app.executor.egress import EgressPolicy, audit_egress_denials
from app.executor.local_docker import LocalDockerExecutor
from app.executor.runtime_policy import GVISOR_RUNTIME, resolve_runtime
from app.runtime import RunService
from app.secrets.github_token import GitHubTokenMinter, TokenScopeError
from app.secrets.redaction import REDACTION_PLACEHOLDER, Redactor
from app.secrets.store import SecretStore
from app.security.audit import AuditLog, MemoryAuditSink

from tests.conftest import StubRuntime, _migrate
from tests.e2e.gating import requires_live_sandbox, requires_runsc

# asyncio_mode="auto" (pyproject) collects the async tests without an explicit mark;
# this module mixes sync + async tests, so NO module-level asyncio pytestmark (it
# would wrongly mark the sync tests and warn).

# Synthetic secret literals shaped like the real credentials (fragment-joined so
# this test file does not itself carry a contiguous secret literal).
_ANTHROPIC = "sk" + "-ant-" + "api03-" + "E" * 40
_GH_CLASSIC = "gh" + "p_" + "F" * 36
_GH_FINE = "github" + "_pat_" + "G" * 40


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]  # DKMVP-ESCAPE: pydantic-settings test kwargs


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> Repository:
    repo = Repository(_migrate(tmp_path / "iso.db"))
    await repo.start()
    return repo


# ── AT-Isolation: config pins runsc + egress allowlist on (in-process, ALWAYS) ─


def test_at_isolation_release_config_pins_runsc_default() -> None:
    """AT-Isolation: SANDBOX_RUNTIME defaults to gVisor runsc (INV-3)."""
    settings = _settings()
    assert settings.SANDBOX_RUNTIME == GVISOR_RUNTIME
    # The policy resolves runsc (skip the host-availability probe in-process) and the
    # executor emits the --runtime=runsc flag.
    assert resolve_runtime(settings.SANDBOX_RUNTIME, check_available=False) == GVISOR_RUNTIME


def test_at_isolation_executor_applies_runtime_and_egress_args() -> None:
    """AT-Isolation: the executor pins --runtime=runsc + the egress-confinement args."""
    settings = _settings()
    run_service = RunService(settings, runtime=StubRuntime())  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck stub
    executor = LocalDockerExecutor(run_service, settings, check_runtime_available=False)
    args = executor.sandbox_docker_args
    assert f"--runtime={GVISOR_RUNTIME}" in args
    assert any(a.startswith("--network=") for a in args)  # egress-confined network
    assert any(a.startswith("--dns=") for a in args)  # pinned resolver


def test_at_isolation_egress_denies_non_allowlisted_host(repository: Repository) -> None:
    """AT-Isolation: a non-allowlisted host is DENIED + the denial is audit-logged (INV-3)."""
    policy = EgressPolicy(hosts=("api.github.com", "api.anthropic.com"))
    assert policy.is_allowed("exfil.attacker.com") is False  # blocked (default-deny)
    assert policy.is_allowed("api.github.com") is True  # allowlisted reachable
    # The denial surfaces to the durable audit trail (the exfil-attempt signal).
    sink = MemoryAuditSink()
    audit = AuditLog(sink)
    denied = audit_egress_denials(
        policy, ["exfil.attacker.com", "api.github.com"], audit=audit, run_id="run-1"
    )
    assert denied == ["exfil.attacker.com"]
    assert any(r.kind.value == "egress_denial" for r in sink.records)


async def test_at_isolation_repo_scoped_token_refuses_foreign_repo() -> None:
    """AT-Isolation: a repo-scoped run token cannot push to a second repo (INV-4)."""
    store = SecretStore(key=SecretStore.generate_key())
    minter = GitHubTokenMinter(store, base_token="ghp-operator-pat")
    token = await minter.mint("octo/target-repo", run_id="run-1")
    token.authorize_push("octo/target-repo")  # authorized for its own repo
    with pytest.raises(TokenScopeError):  # refused for any OTHER repo (containment)
        token.authorize_push("octo/other-repo")


# ── AT-Security: no secret in events / audit (in-process, ALWAYS) ─────────────


async def test_at_security_no_secret_in_events(repository: Repository) -> None:
    """AT-Security: a payload carrying every secret pattern is scrubbed before events (INV-4)."""
    redactor = Redactor(known_values=["nonstandard-shaped-secret-xyz12345"])
    repo = Repository(repository._database_url, redactor=redactor)  # noqa: SLF001 - test seam
    await repo.start()
    try:
        run_id, _ = await repo.claim_run(idempotency_key="sec", repo="o/r")
        await repo.append_events(
            [
                EventRecord(
                    run_id,
                    1,
                    "assistant_message",
                    {
                        "text": f"leaking {_ANTHROPIC} and {_GH_CLASSIC} and {_GH_FINE}",
                        "nested": {"v": "nonstandard-shaped-secret-xyz12345"},
                    },
                )
            ]
        )
        rows = await repo.read_events_after(run_id, 0)
        persisted = rows[0]["payload_json"]
        for secret in (_ANTHROPIC, _GH_CLASSIC, _GH_FINE, "nonstandard-shaped-secret-xyz12345"):
            assert secret not in persisted
        assert "text" in json.loads(persisted)  # structure intact, just scrubbed
    finally:
        await repo.close()


def test_at_security_no_secret_in_audit() -> None:
    """AT-Security: the audit trail is redact-before-persist — no secret literal written (INV-4)."""
    sink = MemoryAuditSink()
    audit = AuditLog(sink, redactor=Redactor())
    # A call site that (incorrectly) passed a secret-shaped value is backstopped.
    audit.record_run_launch(run_id="run-1", repo=f"o/r {_ANTHROPIC}", agent="claude")
    written = json.dumps([r.to_json() for r in sink.records])
    assert _ANTHROPIC not in written
    assert REDACTION_PLACEHOLDER in written


# ── Live-only halves (Docker / runsc gated — SELF-SKIP, never faked) ──────────


@requires_runsc
def test_at_isolation_live_runsc_runtime_registered() -> None:
    """AT-Isolation (live): the runsc runtime is registered with the local daemon.

    Gated: self-skips when runsc/Docker is absent. The in-process config + policy
    assertions above (SANDBOX_RUNTIME=runsc resolves, --runtime=runsc emitted) cover
    this AT when the live runtime is unavailable.
    """
    from app.executor.runtime_policy import runtime_available

    assert runtime_available(GVISOR_RUNTIME) is True


@requires_live_sandbox
def test_at_isolation_live_egress_deny_over_the_wire() -> None:
    """AT-Isolation (live): a non-allowlisted host is blocked at the network layer.

    Gated: self-skips without a live, egress-confined sandbox (the full §8.8 setup).
    The in-process egress-deny assertion above covers the policy decision; this
    placeholder marks where the over-the-wire exfil-attempt assertion runs when a
    real sandbox + filtering proxy are available — it is NEVER faked from a Python
    decision (a synthetic pass would record a denial that never happened).
    """
    pytest.fail("unreachable: gated by requires_live_sandbox (self-skips)")
