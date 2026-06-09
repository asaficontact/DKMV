"""§13 e2e — AT-Live: segment-sum cost climbs to the run total (no reset); SSE replay
no-gaps-no-dups; no token in the SSE URL (cookie auth).

Runs for REAL in-process against the live meter projection + the resumable replay
generator + the SSE cookie-auth helper — the three binding §8.3 live-run behaviors:

* the segment-sum cost (:func:`compute_run_meters`) climbs MONOTONICALLY across
  stage boundaries to the run total — never resetting toward $0 at a boundary, never
  double-counting the cumulative line (INV-7);
* the resumable replay (:func:`replay_then_tail`) emits every ``events.id`` exactly
  once across the backlog→live handoff — no gaps, no duplicates (INV-2 / §8.3);
* the SSE auth token rides the HttpOnly ``SameSite=Strict`` cookie and is NEVER in
  the URL/query string (INV-2): a token in the query would leak into logs + the
  append-only ``events`` table permanently.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from app.db import EventRecord, Repository
from app.runs.meters import compute_run_meters
from app.sse.auth import set_sse_cookie
from app.sse.observer_bridge import RunStreamHub, Subscriber
from app.sse.pump import StreamFrame
from app.sse.replay import replay_then_tail

from tests.conftest import _migrate

pytestmark = pytest.mark.asyncio

REPO = "o/r"


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> Repository:
    repo = Repository(_migrate(tmp_path / "live.db"))
    await repo.start()
    return repo


# ── AT-Live: segment-sum climbs to the run total, no reset at stage boundary ──


async def test_at_live_segment_sum_cost_climbs_to_run_total_no_reset(
    repository: Repository,
) -> None:
    """AT-Live: cost climbs across stages to the run total — no reset, no double-count."""
    run_id, _ = await repository.claim_run(idempotency_key="live-1", repo=REPO, agent="claude")

    # Stage 0 (task_index 0): cumulative line climbs $1 → $3 (final on completion).
    await repository.append_events(
        [
            EventRecord(run_id, 0, "assistant", {}, task_index=0, cost_usd=1.0, agent="claude"),
            EventRecord(run_id, 1, "assistant", {}, task_index=0, cost_usd=2.0, agent="claude"),
            EventRecord(
                run_id, 2, "task_completed", {}, task_index=0, cost_usd=3.0, agent="claude"
            ),
        ]
    )
    row = await repository.get_run(run_id)
    assert row is not None
    meters_after_stage0 = await compute_run_meters(repository, row)
    assert meters_after_stage0.cost_usd == pytest.approx(3.0)

    # Stage 1 (task_index 1): a NEW segment's cumulative starts at $0.50 → the meter
    # must be 3.0 + 0.5 = 3.5 (it does NOT reset to 0.5 at the stage boundary).
    await repository.append_events(
        [EventRecord(run_id, 3, "assistant", {}, task_index=1, cost_usd=0.5, agent="claude")]
    )
    meters_mid_stage1 = await compute_run_meters(repository, row)
    assert meters_mid_stage1.cost_usd == pytest.approx(3.5)  # climbed, not reset

    # Stage 1 completes at $4 cumulative → run total 3.0 + 4.0 = 7.0.
    await repository.append_events(
        [EventRecord(run_id, 4, "task_completed", {}, task_index=1, cost_usd=4.0, agent="claude")]
    )
    meters_final = await compute_run_meters(repository, row)
    assert meters_final.cost_usd == pytest.approx(7.0)
    # The persisted projection agrees with the live meter (one definition of cost).
    assert await repository.run_spend(run_id) == pytest.approx(7.0)
    await repository.close()


# ── AT-Live: SSE replay no-gaps / no-dups across the backlog→live handoff ─────


async def test_at_live_sse_replay_no_gaps_no_dups(repository: Repository) -> None:
    """AT-Live: every events.id is emitted exactly once across replay→live (INV-2)."""
    loop = asyncio.get_running_loop()
    run_id, _ = await repository.claim_run(idempotency_key="live-2", repo=REPO, agent="claude")
    backlog_ids = await repository.append_events(
        [EventRecord(run_id, i, "stream", {"i": i}, task_index=0) for i in range(1, 4)]
    )
    hub = RunStreamHub(run_id, loop)
    sub = Subscriber()
    hub.add_subscriber(sub)  # subscribe BEFORE the backlog read (the §8.3 contract)

    # A frame whose id overlaps the backlog (already persisted) + one new live id.
    overlap = StreamFrame(event_id=backlog_ids[-1], event_type="stream", body={"dup": True})
    live_new = StreamFrame(event_id=backlog_ids[-1] + 1, event_type="stream", body={"new": True})
    sub.publish(overlap)
    sub.publish(live_new)
    hub.mark_closed()

    seen: list[int] = []
    async for frame in replay_then_tail(repository=repository, hub=hub, subscriber=sub, last_id=0):
        seen.append(frame.event_id)

    # No gaps (1,2,3,4 contiguous) and no duplicates (the overlap id 3 appears once).
    assert seen == sorted(set(seen))  # strictly increasing → no dups
    assert seen == [*backlog_ids, backlog_ids[-1] + 1]  # backlog then the one live id
    await repository.close()


# ── AT-Live: the SSE token is in the cookie, NEVER in the URL ─────────────────


async def test_at_live_sse_token_in_cookie_never_in_url(repository: Repository) -> None:
    """AT-Live: SSE auth rides an HttpOnly SameSite=Strict cookie, not a query token (INV-2)."""

    class _Resp:
        def __init__(self) -> None:
            self.cookies: list[tuple[str, str, dict[str, object]]] = []

        def set_cookie(self, key: str, value: str, **kwargs: object) -> None:
            self.cookies.append((key, value, kwargs))

    resp = _Resp()
    token = "local-control-plane-token"  # noqa: S105 - fixture, not a real secret
    set_sse_cookie(resp, token)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck Response

    assert resp.cookies, "an SSE cookie must be set on connect"
    key, value, attrs = resp.cookies[-1]
    assert value == token
    # The cookie is HttpOnly + SameSite=Strict (browser EventSource cannot read/set it,
    # and it is not forgeable cross-site) — the token never needs to ride the URL.
    assert attrs.get("httponly") is True
    assert str(attrs.get("samesite", "")).lower() == "strict"

    # The replay/endpoint surface reads the cursor from Last-Event-ID, NOT a token=
    # query param — there is no token in any SSE URL the client builds (INV-2).
    from app.sse import auth as sse_auth_mod

    src = Path(sse_auth_mod.__file__).read_text()
    assert "token=" not in src  # no token-in-URL carrier anywhere in the SSE auth path
    await repository.close()
