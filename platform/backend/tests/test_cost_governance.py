"""Slice 5.2 — capability-aware cost governance (INV-8 / ADR-P009, NFR-COST-1, §7.2).

Asserts the honest, per-agent cost story — branching on the engine adapter's
``supports_budget()`` / ``supports_max_turns()`` (never a blanket "budget cap
exists"):

* **AC-6 (INV-8, binding).** A **Codex** run launched with ``max_budget_usd`` (or
  ``max_turns``) is rejected with ``400 unsupported_for_agent`` (status + code) —
  end-to-end over the real ``POST /runs`` path. The same body on **Claude** is
  accepted (the cap is supported). The validator branches on capability.
* **AC-7 (Codex timeout-only).** A Codex run is bounded by ``timeout_minutes``
  alone — no budget/turn cap fires — and the Codex default timeout is **strictly
  tighter** than the Claude default (``CODEX_DEFAULT_TIMEOUT_MINUTES <
  CLAUDE_DEFAULT_TIMEOUT_MINUTES``). A Codex launch with no explicit timeout starts
  the engine with the tighter Codex default.
* **AC-8 (Claude hard caps).** For Claude (``supports_budget`` true) the budget is
  a **hard cap that fires** (the run is *stopped*, not advised) when spend reaches
  ``max_budget_usd`` — and never fires for a timeout-only Codex run.

The launch tests reuse the slice-2.1 fake-engine + fake-GitHub harness so no
Docker / network is touched (INV-13); the enforcement-unit tests call the
capability-aware resolver directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from app.config import (
    CLAUDE_DEFAULT_TIMEOUT_MINUTES,
    CODEX_DEFAULT_TIMEOUT_MINUTES,
    default_timeout_minutes,
)
from app.orchestrator.enforcement import (
    budget_cap_fires,
    capabilities_for,
    resolve_enforced_caps,
)
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, build_client, make_settings
from tests.unit.test_runs_launch import FakeClient, FakeRuntime

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def _client(db_path: Path) -> tuple[TestClient, FakeRuntime, FakeClient]:
    """A TestClient over a fresh migrated DB + fake engine + fake GitHub (no Docker)."""
    from app.github.provider import set_github_client

    url = _migrate(db_path)
    runtime = FakeRuntime()
    client = build_client(settings=make_settings(DATABASE_URL=url), runtime=runtime)
    fake_gh = FakeClient()
    set_github_client(client.app, fake_gh)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck client
    return client, runtime, fake_gh


def _body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "issue_num": 11,
        "repo": "o/r",
        "workflow_id": "qa",
        "agent": "claude",
        "branch": "dkmv/issue-11-cost",
        "feature_name": "issue-11-cost",
    }
    base.update(overrides)
    return base


# ── AC-6 / INV-8 (binding): Codex budget/turns → 400 unsupported_for_agent ────


def test_ac6_codex_budget_rejected_400_unsupported_for_agent(tmp_path: Path) -> None:
    """A Codex run with ``max_budget_usd`` → ``400 unsupported_for_agent`` (status + code)."""
    client, _rt, _gh = _client(tmp_path / "c.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="codex", workflow_id="dev", max_budget_usd=10.0),
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unsupported_for_agent"


def test_ac6_codex_max_turns_rejected_400_unsupported_for_agent(tmp_path: Path) -> None:
    """A Codex run with ``max_turns`` → ``400 unsupported_for_agent`` (capability branch)."""
    client, _rt, _gh = _client(tmp_path / "c.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="codex", workflow_id="dev", max_turns=40),
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unsupported_for_agent"


def test_ac6_claude_same_budget_body_accepted(tmp_path: Path) -> None:
    """The same budget/turn body on Claude (``supports_budget`` true) is accepted."""
    client, runtime, _gh = _client(tmp_path / "c.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="claude", max_budget_usd=10.0, max_turns=40),
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    assert len(runtime.start_calls) == 1
    assert runtime.start_calls[0]["max_budget_usd"] == 10.0
    assert runtime.start_calls[0]["max_turns"] == 40


def test_ac6_enforcement_branches_on_capability() -> None:
    """INV-8: enforcement reads the adapter's supports_budget/supports_max_turns."""
    claude = capabilities_for("claude")
    codex = capabilities_for("codex")
    assert claude.supports_budget is True
    assert claude.supports_max_turns is True
    assert codex.supports_budget is False
    assert codex.supports_max_turns is False
    # Codex is the timeout-only profile (neither cost cap can fire).
    assert codex.timeout_only is True
    assert claude.timeout_only is False


# ── AC-7: Codex timeout-only + Codex default strictly tighter than Claude ─────


def test_ac7_codex_default_timeout_strictly_tighter_than_claude() -> None:
    """The Codex default timeout is **strictly** tighter than the Claude default."""
    assert CODEX_DEFAULT_TIMEOUT_MINUTES < CLAUDE_DEFAULT_TIMEOUT_MINUTES
    assert default_timeout_minutes("codex") < default_timeout_minutes("claude")
    assert default_timeout_minutes("codex") == CODEX_DEFAULT_TIMEOUT_MINUTES
    assert default_timeout_minutes("claude") == CLAUDE_DEFAULT_TIMEOUT_MINUTES


def test_ac7_codex_bounded_by_timeout_only_no_cost_caps() -> None:
    """A Codex run carries no budget/turn cap — timeout is its only guardrail."""
    caps = resolve_enforced_caps(
        agent="codex",
        max_budget_usd=None,
        max_turns=None,
        timeout_minutes=None,
    )
    # No cost cap can fire for Codex (timeout-only).
    assert caps.budget_cap_active is False
    assert caps.turn_cap_active is False
    assert caps.max_budget_usd is None
    assert caps.max_turns is None
    # The sole guardrail is the tighter Codex default timeout.
    assert caps.timeout_minutes == CODEX_DEFAULT_TIMEOUT_MINUTES
    # Even at arbitrarily high spend, no budget cap fires for Codex.
    assert budget_cap_fires(caps, spend_usd=999.0) is False


def test_ac7_codex_launch_starts_engine_with_tighter_default_timeout(tmp_path: Path) -> None:
    """A Codex launch with no explicit timeout starts the engine with the tighter default."""
    client, runtime, _gh = _client(tmp_path / "c.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="codex", workflow_id="dev"),
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    assert len(runtime.start_calls) == 1
    call = runtime.start_calls[0]
    assert call["timeout_minutes"] == CODEX_DEFAULT_TIMEOUT_MINUTES
    # Codex carries no budget/turn cap to the engine (timeout-only).
    assert call["max_budget_usd"] is None
    assert call["max_turns"] is None


def test_ac7_claude_launch_starts_engine_with_claude_default_timeout(tmp_path: Path) -> None:
    """A Claude launch with no explicit timeout uses the (looser) Claude default."""
    client, runtime, _gh = _client(tmp_path / "c.db")
    resp = client.post(
        "/api/v1/runs",
        json=_body(agent="claude"),
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    assert runtime.start_calls[0]["timeout_minutes"] == CLAUDE_DEFAULT_TIMEOUT_MINUTES


# ── AC-8: Claude budget is a hard cap that FIRES (run is stopped, not advised) ─


def test_ac8_claude_hard_budget_cap_fires() -> None:
    """For Claude the budget is a hard cap: it fires at/above the ceiling."""
    caps = resolve_enforced_caps(
        agent="claude",
        max_budget_usd=10.0,
        max_turns=40,
        timeout_minutes=None,
    )
    assert caps.budget_cap_active is True
    assert caps.max_budget_usd == 10.0
    assert caps.turn_cap_active is True
    # Below the cap → does not fire; at/above the cap → fires (run is stopped).
    assert budget_cap_fires(caps, spend_usd=9.99) is False
    assert budget_cap_fires(caps, spend_usd=10.0) is True
    assert budget_cap_fires(caps, spend_usd=12.5) is True


def test_ac8_claude_explicit_timeout_is_respected() -> None:
    """An explicit ``timeout_minutes`` is never overridden by the capability default."""
    caps = resolve_enforced_caps(
        agent="claude",
        max_budget_usd=None,
        max_turns=None,
        timeout_minutes=7,
    )
    assert caps.timeout_minutes == 7
