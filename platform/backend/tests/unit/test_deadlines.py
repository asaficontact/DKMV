"""UTC-persisted deadline evaluation (slice 3.3 — AC-13, binding).

These tests pin the binding durability property: every orchestrator deadline is a
**UTC timestamp re-evaluated against a fresh ``now()``** — never an in-memory
``asyncio.sleep`` timer — so a deadline whose ``due_at`` fell inside a suspend gap
fires on the next evaluation, however long the gap was. A **frozen clock** is
advanced past a persisted ``due_at`` (simulating a laptop suspend) and the
deadline is asserted to fire, with no real sleeping. A source-level grep asserts
``deadlines.py`` contains no ``sleep(`` (the AC-13 grep).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.orchestrator import deadlines


def _at(seconds: float, *, base: datetime) -> deadlines.Clock:
    """A frozen clock reading ``base + seconds`` (no real time passes)."""

    def _clock() -> datetime:
        return base + timedelta(seconds=seconds)

    return _clock


def test_is_due_false_before_and_true_after_a_frozen_suspend_gap() -> None:
    base = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    # A deadline persisted 100s into the future.
    due_at = deadlines.due_at_from_now(100, now=lambda: base)

    # Before the deadline: not due (clock at +50s).
    assert deadlines.is_due(due_at, now=_at(50, base=base)) is False

    # Simulate a suspend: the clock jumps far PAST due_at (+10_000s). The deadline
    # fires on this single re-evaluation — no timer was slept; the persisted
    # due_at is simply compared against the resumed now().
    assert deadlines.is_due(due_at, now=_at(10_000, base=base)) is True


def test_is_due_handles_none_and_unparseable() -> None:
    # No deadline set → never due.
    assert deadlines.is_due(None) is False
    # A malformed persisted cell does not crash a tick; treated as "not due".
    assert deadlines.is_due("not-a-timestamp") is False


def test_seconds_since_measures_against_fresh_now() -> None:
    base = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    ts = deadlines.to_iso(base)
    # 300s later (a frozen jump) → 300s elapsed, re-evaluated, not a slept timer.
    assert deadlines.seconds_since(ts, now=_at(300, base=base)) == 300.0
    # No ts → None (distinct from "0 seconds ago").
    assert deadlines.seconds_since(None) is None


def test_deadline_value_object_fires_on_frozen_jump() -> None:
    base = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    dl = deadlines.Deadline(kind="backoff", due_at=deadlines.due_at_from_now(60, now=lambda: base))
    assert dl.fires(now=_at(10, base=base)) is False
    assert dl.fires(now=_at(120, base=base)) is True


def test_parse_iso_coerces_naive_to_utc() -> None:
    naive = "2026-06-09T12:00:00"
    parsed = deadlines.parse_iso(naive)
    assert parsed is not None
    assert parsed.tzinfo is UTC


def test_deadlines_module_has_no_sleep_timer() -> None:
    """AC-13 binding grep: ``deadlines.py`` implements NO deadline as a sleep timer."""
    source = Path(deadlines.__file__).read_text()
    # Strip the module docstring (which legitimately discusses ``asyncio.sleep`` as
    # the WRONG approach) before the grep, so only actual code is checked.
    code = source.split('"""', 2)[-1]
    assert "sleep(" not in code
