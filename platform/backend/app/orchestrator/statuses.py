"""The shared run-status sets the admission + dispatch gates read (single source).

Both the bounded dispatcher (slot accounting) and the admission controller (memory
accounting) need to enumerate the non-terminal run statuses whose runs consume a
governed resource. The two sets differ only by ``paused`` — a paused run has
**released its concurrency slot** (INV-9, so it is NOT slot-holding) but its
container is **still parked open holding memory** (§8.5, so it IS memory-holding).

Keeping the two tuples in two modules invited drift (a future status — say a new
``draining`` state — would have to be added in both by hand). This module is the
**one** definition; :mod:`app.orchestrator.dispatch` and
:mod:`app.orchestrator.admission` import from here so a status change is made once.
"""

from __future__ import annotations

#: Non-terminal statuses whose runs currently HOLD a concurrency slot (the resync
#: target). ``pending`` (claimed, container starting) + ``running`` + ``stopping``
#: each hold one. A ``paused`` run is excluded — it RELEASED its slot at the pause
#: point (INV-9), so counting it would double-reserve. Terminal statuses hold none.
SLOT_HOLDING_STATUSES: tuple[str, ...] = ("pending", "running", "stopping")

#: Non-terminal statuses whose containers hold host memory (the admission target).
#: Identical to :data:`SLOT_HOLDING_STATUSES` plus ``paused``: a paused run released
#: its slot but its container is still parked open holding memory (§8.5), so it DOES
#: count toward ``HOST_MEMORY_BUDGET``. Terminal statuses hold nothing.
MEMORY_HOLDING_STATUSES: tuple[str, ...] = (*SLOT_HOLDING_STATUSES, "paused")


__all__ = ["MEMORY_HOLDING_STATUSES", "SLOT_HOLDING_STATUSES"]
