"""Slice 2.5 — concurrency-slot accounting primitive (AC-18 / T086).

The slot-release-on-pause / reacquire-on-resume accounting Phase 5's admission
semaphore consumes. Phase 2 does NOT enforce a cap; this asserts the counter moves
correctly (a paused run frees its slot, a resumed run takes one back) and never
goes negative on a double-release.
"""

from __future__ import annotations

from app.hitl import ConcurrencySlots


def test_acquire_release_accounting() -> None:
    slots = ConcurrencySlots(capacity=3)
    assert slots.held == 0
    assert slots.available == 3

    slots.acquire()  # a run launches
    assert slots.held == 1
    assert slots.available == 2

    slots.release()  # the run pauses (genuinely idle — frees its slot)
    assert slots.held == 0
    assert slots.available == 3

    slots.acquire()  # the run resumes (re-acquires a slot)
    assert slots.held == 1


def test_release_never_goes_negative() -> None:
    slots = ConcurrencySlots(capacity=1)
    slots.release()  # double / spurious release
    slots.release()
    assert slots.held == 0
    assert slots.available == 1  # no phantom capacity manufactured
