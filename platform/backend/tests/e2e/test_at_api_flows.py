"""§13 e2e — the HTTP-driven ATs: Connect / Board / Launch / History / CodexCost / Workflows.

These run for REAL against the FastAPI app (fake engine + fake GitHub, no Docker)
through the same loopback-pinned, token-authed, lifespan-entered client the unit
suite uses (INV-1). Each test seeds rows through a same-DB Repository and asserts
the endpoint's response, mapping the PRD §13 acceptance tests at the API boundary.
"""

from __future__ import annotations

import uuid

import pytest
from app.api.board import start_of_utc_day
from app.api.connect import REQUIRED_PAT_PERMISSIONS
from app.db import EventRecord, Repository

from tests.conftest import auth_headers
from tests.e2e.conftest import E2EHarness, run_body

pytestmark = pytest.mark.asyncio

REPO = "o/r"
_FINE_PAT = "github_pat_" + "A1B2C3D4E5F6G7H8I9J0"  # noqa: S105 - fixture, not a real secret


async def _seed_run(
    repository: Repository,
    *,
    agent: str,
    status: str,
    issue_num: int,
    task_costs: list[tuple[int, float]],
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> str:
    """Claim a run + append per-task cumulative cost rows (segment-sum inputs)."""
    run_id, _ = await repository.claim_run(
        idempotency_key=str(uuid.uuid4()), repo=REPO, issue_num=issue_num, agent=agent
    )
    await repository.update_run_fields(
        run_id, status=status, tokens_in=tokens_in, tokens_out=tokens_out
    )
    records: list[EventRecord] = []
    seq = 0
    for task_index, cost in task_costs:
        records.append(
            EventRecord(
                run_id,
                seq,
                "assistant",
                {},
                task_index=task_index,
                cost_usd=round(cost / 2, 4),
                agent=agent,
            )
        )
        seq += 1
        records.append(
            EventRecord(
                run_id, seq, "task_completed", {}, task_index=task_index, cost_usd=cost, agent=agent
            )
        )
        seq += 1
    if records:
        await repository.append_events(records)
    return run_id


# ── AT-Connect ────────────────────────────────────────────────────────────────


async def test_at_connect_pat_intake_returns_permission_contract(harness: E2EHarness) -> None:
    """AT-Connect: POST /connect/github echoes the four required permissions, PAT not leaked."""
    resp = harness.client.post(
        "/api/v1/connect/github", json={"token": _FINE_PAT}, headers=auth_headers()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert set(body["permissions"]) == set(REQUIRED_PAT_PERMISSIONS)
    # INV-4: the PAT value never appears in the response body.
    assert _FINE_PAT not in resp.text


async def test_at_connect_requires_local_token(harness: E2EHarness) -> None:
    """AT-Connect: the connect route is behind the INV-1 access-control gate."""
    resp = harness.client.post("/api/v1/connect/github", json={"token": _FINE_PAT})
    assert resp.status_code == 401


# ── AT-Launch ─────────────────────────────────────────────────────────────────


async def test_at_launch_claims_run_and_moves_label(harness: E2EHarness) -> None:
    """AT-Launch: POST /runs returns a platform UUID + moves the issue to in-progress."""
    resp = harness.client.post("/api/v1/runs", json=run_body(), headers=auth_headers())
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    assert uuid.UUID(run_id)  # platform UUID, not the engine id (§8.4)
    # INV-11: the issue moved to agent:in-progress via the replace-all label PUT.
    assert harness.github.replace_calls
    _repo, _num, labels = harness.github.replace_calls[-1]
    assert "agent:in-progress" in labels


async def test_at_launch_duplicate_dispatch_409(harness: E2EHarness) -> None:
    """AT-Launch: a second identical POST /runs → one row + a 409 (INV-5 claim-lock)."""
    body = run_body()
    assert harness.client.post("/api/v1/runs", json=body, headers=auth_headers()).status_code == 201
    second = harness.client.post("/api/v1/runs", json=body, headers=auth_headers())
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_dispatch"


# ── AT-Board ──────────────────────────────────────────────────────────────────


async def test_at_board_aggregate_strip(harness: E2EHarness) -> None:
    """AT-Board: GET /board/aggregate surfaces In-Progress / Needs-You + spend/tokens."""
    await _seed_run(
        harness.repository,
        agent="claude",
        status="running",
        issue_num=1,
        task_costs=[(0, 1.5), (1, 2.0)],
        tokens_in=70_000,
        tokens_out=18_000,
    )
    await _seed_run(
        harness.repository, agent="claude", status="paused", issue_num=2, task_costs=[(0, 0.5)]
    )
    resp = harness.client.get("/api/v1/repos/o/r/board/aggregate", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["in_progress"] == 1  # the running run
    assert body["needs_you"] == 1  # the paused run (§5.3.1 authority split)


# ── AT-History ────────────────────────────────────────────────────────────────


async def test_at_history_lists_runs_with_segment_sum_spend(harness: E2EHarness) -> None:
    """AT-History: GET /runs lists finished runs; cost is the segment-sum (not naive)."""
    await _seed_run(
        harness.repository,
        agent="claude",
        status="completed",
        issue_num=3,
        task_costs=[(0, 1.0), (0, 4.0), (1, 6.0)],
    )  # last-per-task: 4.0 + 6.0 = 10.0
    resp = harness.client.get("/api/v1/runs?repo=o/r", headers=auth_headers())
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["cost_usd"] == pytest.approx(10.0)  # segment-sum, not 11.0 naive


# ── AT-CodexCost ──────────────────────────────────────────────────────────────


async def test_at_codexcost_dash_not_zero_and_excluded_from_spend(harness: E2EHarness) -> None:
    """AT-CodexCost: a Codex run renders cost null ("—"), excluded from spend, tokens count."""
    await _seed_run(
        harness.repository,
        agent="claude",
        status="completed",
        issue_num=4,
        task_costs=[(0, 3.5)],
        tokens_in=1000,
        tokens_out=500,
    )
    await _seed_run(
        harness.repository,
        agent="codex",
        status="completed",
        issue_num=5,
        task_costs=[(0, 9.99)],
        tokens_in=40_000,
        tokens_out=12_000,
    )

    # History detail: the Codex run's cost is null (the UI renders "—", not $0.00).
    items = harness.client.get("/api/v1/runs?repo=o/r", headers=auth_headers()).json()["items"]
    by_issue = {it["issue"]["num"] if it.get("issue") else None: it for it in items}
    codex_item = next(it for it in items if it["agent"] == "codex")
    claude_item = next(it for it in items if it["agent"] == "claude")
    assert codex_item["cost_usd"] is None  # "—", NOT 0.0
    assert claude_item["cost_usd"] == pytest.approx(3.5)
    _ = by_issue  # the lookup is illustrative; the agent split is the assertion

    # Board spend excludes Codex; tokens count BOTH agents (FR-06-1a / INV-8).
    agg = await harness.repository.board_aggregate(REPO, since_iso=start_of_utc_day())
    assert agg.spent_today == pytest.approx(3.5)  # Claude-only
    assert agg.tokens_today == (1000 + 500) + (40_000 + 12_000)  # both agents


# ── AT-Workflows ──────────────────────────────────────────────────────────────


async def test_at_workflows_viewer_lists_builtins(harness: E2EHarness) -> None:
    """AT-Workflows: GET /workflows surfaces the read-only built-in component pipelines."""
    resp = harness.client.get("/api/v1/workflows", headers=auth_headers())
    assert resp.status_code == 200
    workflows = resp.json()
    ids = {w["id"] for w in workflows}
    # The built-in workflows the launch path accepts (qa/dev are exercised elsewhere).
    assert {"dev", "qa"} <= ids
    # Read-only: there is no create/update/delete route (ADR-P010) — a PUT 404/405s.
    assert harness.client.put(
        "/api/v1/workflows/dev", json={}, headers=auth_headers()
    ).status_code in {404, 405}
