"""Slice 2.3 — replay subscribe-before-read + dedup across the live handoff (AC-11).

Unit-tests :func:`app.sse.replay.replay_then_tail` directly against a migrated DB +
a live hub to prove the **no-gap / no-duplicate** contract at the handoff (the case
the HTTP test can't deterministically force): events that land in BOTH the durable
backlog and the live subscriber (because we subscribed before reading) are emitted
**exactly once**, in ``id`` order, and live-only events that follow stream through.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import app.sse.replay as replay_mod
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.db import Repository
from app.db.repository import EventRecord
from app.sse.observer_bridge import RunStreamHub, Subscriber
from app.sse.pump import StreamFrame, event_to_body
from app.sse.replay import iter_backlog, parse_last_event_id, replay_then_tail

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _migrate(db_path: Path) -> str:
    url = f"sqlite:///{db_path}"
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[Repository]:
    repo = Repository(_migrate(tmp_path / "replay.db"))
    await repo.start()
    try:
        yield repo
    finally:
        await repo.close()


async def _seed(repo: Repository, n: int) -> tuple[str, list[int]]:
    run_id, _ = await repo.claim_run(
        idempotency_key="replay-k",
        repo="o/r",
        issue_num=1,
        workflow_id="plan",
        agent="claude",
        branch="b",
        feature_name="f",
    )
    ids = await repo.append_events(
        [
            EventRecord(
                run_id=run_id,
                sequence=i,
                event_type="stream",
                payload={"type": "stream", "i": i},
                task_index=0,
            )
            for i in range(1, n + 1)
        ]
    )
    return run_id, ids


def test_parse_last_event_id() -> None:
    """The cursor parser degrades garbage/blank to a full replay (0)."""
    assert parse_last_event_id(None) == 0
    assert parse_last_event_id("") == 0
    assert parse_last_event_id("not-a-number") == 0
    assert parse_last_event_id("  42 ") == 42
    assert parse_last_event_id("-5") == 0


@pytest.mark.asyncio
async def test_replay_then_tail_no_gaps_no_dups_across_handoff(repository: Repository) -> None:
    """Backlog + live overlap → every id emitted exactly once, in order (AC-11)."""
    loop = asyncio.get_running_loop()
    run_id, backlog_ids = await _seed(repository, 3)
    hub = RunStreamHub(run_id, loop)
    sub = Subscriber()
    hub.add_subscriber(sub)  # subscribe-before-read

    # Simulate the overlap window: the last backlog event ALSO arrives live (the
    # pump persisted it just as we subscribed), PLUS two genuinely new live events.
    overlap_id = backlog_ids[-1]
    next_id = overlap_id + 1
    hub.publish(StreamFrame(overlap_id, "stream", {"i": "overlap"}))  # dup of backlog tail
    hub.publish(StreamFrame(next_id, "stream", {"i": "live-1"}))
    hub.publish(StreamFrame(next_id + 1, "task_completed", {"i": "live-2"}))
    hub.mark_closed()

    seen: list[int] = []
    async for frame in replay_then_tail(repository=repository, hub=hub, subscriber=sub, last_id=0):
        seen.append(frame.event_id)

    # No duplicates, strictly increasing, and the overlap id appears once.
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen))
    assert seen.count(overlap_id) == 1
    # Full coverage: the 3 backlog ids + the 2 new live ids, no gap.
    assert seen == [*backlog_ids, next_id, next_id + 1]


@pytest.mark.asyncio
async def test_replay_then_tail_respects_last_event_id(repository: Repository) -> None:
    """A non-zero cursor skips already-seen backlog ids (no re-send)."""
    loop = asyncio.get_running_loop()
    run_id, backlog_ids = await _seed(repository, 4)
    hub = RunStreamHub(run_id, loop)
    sub = Subscriber()
    hub.add_subscriber(sub)
    hub.mark_closed()

    cursor = backlog_ids[1]  # reconnect after the 2nd event
    seen: list[int] = []
    async for frame in replay_then_tail(
        repository=repository, hub=hub, subscriber=sub, last_id=cursor
    ):
        seen.append(frame.event_id)

    assert all(i > cursor for i in seen)
    assert seen == backlog_ids[2:]


@pytest.mark.asyncio
async def test_replay_then_tail_awaits_live_frame_then_closes(repository: Repository) -> None:
    """With an empty backlog the tail awaits a live frame, then ends on close.

    Exercises the live-wait race (``_next_or_close``): a frame published *after*
    the generator starts awaiting is delivered, and the subsequent ``mark_closed``
    terminates the stream cleanly (no hang).
    """
    loop = asyncio.get_running_loop()
    run_id, _ = await _seed(repository, 0)  # no backlog
    hub = RunStreamHub(run_id, loop)
    sub = Subscriber()
    hub.add_subscriber(sub)

    collected: list[int] = []

    async def consume() -> None:
        async for frame in replay_then_tail(
            repository=repository, hub=hub, subscriber=sub, last_id=0
        ):
            collected.append(frame.event_id)

    consumer = asyncio.ensure_future(consume())
    await asyncio.sleep(0.05)  # let the consumer reach the live await
    hub.publish(StreamFrame(1, "stream", {"i": "live"}))
    await asyncio.sleep(0.05)
    hub.mark_closed()
    await asyncio.wait_for(consumer, timeout=2.0)

    assert collected == [1]


@pytest.mark.asyncio
async def test_replay_then_tail_stops_on_disconnected_subscriber(repository: Repository) -> None:
    """A disconnected (slow) subscriber ends the tail (it reconnects + replays)."""
    loop = asyncio.get_running_loop()
    run_id, backlog_ids = await _seed(repository, 1)
    hub = RunStreamHub(run_id, loop)
    sub = Subscriber()
    hub.add_subscriber(sub)
    sub._disconnected = True  # noqa: SLF001 - simulate the slow-consumer cutoff

    seen: list[int] = []
    async for frame in replay_then_tail(repository=repository, hub=hub, subscriber=sub, last_id=0):
        seen.append(frame.event_id)
    # The backlog still flushes; the live tail then stops immediately.
    assert seen == backlog_ids


@pytest.mark.asyncio
async def test_iter_backlog_pages_large_backlog_no_gaps_no_dups(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX-3: a large backlog replays in BOUNDED pages — every id once, in order.

    Seeds many more events than a single page and shrinks ``BACKLOG_PAGE_SIZE`` so
    the read MUST span several pages, then asserts ``iter_backlog`` yields each id
    exactly once in strictly increasing order (no gap at a page boundary, no dup of
    the page's last row) — i.e. the bounded paging preserves the no-gaps/no-dups
    contract while keeping each read O(page), not O(run-so-far).
    """
    monkeypatch.setattr(replay_mod, "BACKLOG_PAGE_SIZE", 5)
    total = 23  # 23 / 5 → 5 pages (the last short page ends the loop)
    run_id, backlog_ids = await _seed(repository, total)

    seen: list[int] = []
    async for frame in iter_backlog(repository, run_id, 0):
        seen.append(frame.event_id)

    assert seen == backlog_ids  # every id, in id order
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen))  # no duplicate across page boundaries


@pytest.mark.asyncio
async def test_iter_backlog_respects_cursor_and_drains_exactly(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX-3: paging from a non-zero cursor yields only id > cursor, fully drained."""
    monkeypatch.setattr(replay_mod, "BACKLOG_PAGE_SIZE", 3)
    run_id, backlog_ids = await _seed(repository, 10)
    cursor = backlog_ids[3]

    seen: list[int] = []
    async for frame in iter_backlog(repository, run_id, cursor):
        seen.append(frame.event_id)

    assert all(i > cursor for i in seen)
    assert seen == backlog_ids[4:]  # exactly the tail, drained across pages


@pytest.mark.asyncio
async def test_replay_then_tail_pages_backlog_then_tails(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX-3: replay_then_tail uses the paged backlog, then tails live with dedup."""
    monkeypatch.setattr(replay_mod, "BACKLOG_PAGE_SIZE", 4)
    loop = asyncio.get_running_loop()
    run_id, backlog_ids = await _seed(repository, 11)  # 3 pages of backlog
    hub = RunStreamHub(run_id, loop)
    sub = Subscriber()
    hub.add_subscriber(sub)  # subscribe-before-read

    # Overlap (the backlog tail also arrives live) + one new live event.
    overlap_id = backlog_ids[-1]
    next_id = overlap_id + 1
    hub.publish(StreamFrame(overlap_id, "stream", {"i": "overlap"}))
    hub.publish(StreamFrame(next_id, "task_completed", {"i": "live"}))
    hub.mark_closed()

    seen: list[int] = []
    async for frame in replay_then_tail(repository=repository, hub=hub, subscriber=sub, last_id=0):
        seen.append(frame.event_id)

    assert seen == [*backlog_ids, next_id]  # paged backlog + live, no gap
    assert len(seen) == len(set(seen))  # the overlap id is not duplicated


def test_event_to_body_roundtrips_through_frame() -> None:
    """A live frame body and a replayed-row body agree on the outer shape (sanity)."""
    from dkmv.runtime import RuntimeEvent

    ev = RuntimeEvent(
        sequence=1,
        timestamp=datetime.now(UTC),
        run_id="r",
        event_type="result",
        task_index=0,
        cost_usd=1.0,
    )
    body = event_to_body(ev)
    assert body["event_type"] == "result"
    assert body["task_index"] == 0
