"""Live-run meters — the segment-sum cost/turns/tokens the meters row renders.

This is the **live computation** (slice 2.4 / INV-7, §8.3, §6.4) behind the
meters row of the live run view. It is the read-time twin of the persisted
:meth:`app.db.repository.Repository.run_spend` spend projection: both use the
**same** dedup-by-``task_index`` segment-sum semantics, so the figure the meter
shows and the figure the dashboard spend projects can never diverge into two
different definitions of "cost".

The binding rule (INV-7, §8.3, R-17)::

    run_cost = Σ( final cost_usd of each COMPLETED task )           # per (run_id, task_index)
             + ( latest  cost_usd within the ACTIVE task )

de-duplicated by ``task_index`` — **never** a naive ``SUM(cost_usd)`` over every
event (the outer ``cost_usd`` is **cumulative per task**, so a flat sum
double-counts every intermediate line), and **never** plain keep-latest-overall
(which would reset toward ``$0`` at every stage boundary and never climb to the
run total). ``task_completed`` / ``task_failed`` carry a completed segment's
**final** cumulative and are therefore **meter-critical** — they are the per-task
finals the sum is built from and must never be coalesced/dropped.

**Turns aggregate identically** (Σ per-task last-cumulative turns). **Tokens**
are summed the same way from each segment's last line (``usage.input_tokens`` /
``usage.output_tokens`` or the engine's ``num_turns``-adjacent token fields), so
they too climb monotonically across stages.

**Codex cost handling (INV-8, FR-06-1a).** A Codex run reports ``$0`` from the
engine: its cost is rendered **"—" (``cost_usd = None``), not ``$0.00``**, and
the run is **excluded from spend**. Its **tokens still count** (they are real even
though its cost is unpriced) — so a mixed Claude+Codex window shows
Claude-only spend but both agents' tokens. The exclusion is by the run's
``agent`` column, matching the persisted projection.

This module is a **pure read projection** over the
:class:`~app.db.repository.Repository` seam: no GitHub call, no engine call, no
``dkmv/`` import.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.db.repository import Repository
from app.db.spend_sql import COST_EXCLUDED_AGENT

#: ``event_type`` values that carry a **completed** segment's final cumulative
#: cost/turns (INV-7 meter-critical). They are the per-task finals the segment-sum
#: is built from — listed here so the meaning is explicit and greppable, even
#: though :func:`compute_run_meters` already includes every distinct
#: ``task_index`` (completed or active) by construction.
METER_CRITICAL_EVENT_TYPES: frozenset[str] = frozenset({"task_completed", "task_failed"})


def is_cost_excluded_agent(agent: Any) -> bool:
    """True iff a run's agent is the cost-excluded Codex agent (FR-06-1a / INV-8)."""
    return isinstance(agent, str) and agent.strip().lower() == COST_EXCLUDED_AGENT


@dataclass(frozen=True, slots=True)
class RunMeters:
    """The live meters-row figures for a run (§8.3 / FR-04-2).

    ``cost_usd`` is the **segment-sum** spend, or ``None`` for a Codex run (the
    meter renders "—", not ``$0.00`` — INV-8). ``turns`` / ``tokens_in`` /
    ``tokens_out`` are the segment-sum aggregates (Codex tokens DO count).
    ``cost_excluded`` flags the Codex case so the UI knows to render "—" and
    exclude the run from spend, distinct from a Claude run that genuinely cost
    ``$0`` so far.
    """

    #: Segment-sum cost, or None when the run's cost is excluded (Codex).
    cost_usd: float | None
    #: Segment-sum cumulative turns across tasks.
    turns: int
    #: Segment-sum input tokens across tasks (counts even for Codex).
    tokens_in: int
    #: Segment-sum output tokens across tasks (counts even for Codex).
    tokens_out: int
    #: True when the run's cost is excluded from spend (Codex) → meter shows "—".
    cost_excluded: bool


def _payload(raw: Any) -> dict[str, Any]:
    """Decode a persisted ``payload_json`` string into the inner event dict.

    The persisted payload is the **inner** engine ``RuntimeEvent.data`` dict
    (§6.4). A malformed/empty payload degrades to ``{}`` rather than failing the
    whole meter read.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):  # pragma: no cover - persisted JSON is well-formed
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _segment_turns(payload: dict[str, Any]) -> int:
    """The segment's cumulative turns from its last line's inner payload.

    The engine surfaces turns as ``num_turns`` on a result line and as ``turns``
    on a lifecycle ``task_completed`` / ``task_failed`` line (§6.4). Either is the
    cumulative count for that task — we read whichever is present, defaulting to
    ``0`` for a non-numeric/absent value.
    """
    for key in ("turns", "num_turns"):
        value = payload.get(key)
        if isinstance(value, bool):  # bool is an int subclass — never a turn count
            continue
        if isinstance(value, int | float):
            return int(value)
    return 0


def _segment_tokens(payload: dict[str, Any]) -> tuple[int, int]:
    """The segment's cumulative ``(in, out)`` tokens from its last line's payload.

    Reads the engine usage block (``usage.input_tokens`` / ``output_tokens``),
    falling back to the flat ``input_tokens`` / ``output_tokens`` keys some lines
    carry. Defaults to ``(0, 0)`` when no token figures are present. Tokens count
    for **every** agent including Codex (FR-06-1a).
    """
    usage = payload.get("usage")
    source: dict[str, Any] = usage if isinstance(usage, dict) else payload
    return (_int(source.get("input_tokens")), _int(source.get("output_tokens")))


def _int(value: Any) -> int:
    """Coerce a numeric (non-bool) value to ``int``, else ``0``."""
    if isinstance(value, bool):
        return 0
    return int(value) if isinstance(value, int | float) else 0


async def compute_run_meters(repository: Repository, run: dict[str, Any]) -> RunMeters:
    """Compute the live segment-sum meters for one run row (INV-7 / §8.3).

    Reads the run's per-``task_index`` last-cumulative segments
    (:meth:`Repository.read_run_segments`) and **sums** ``cost_usd`` / ``turns`` /
    tokens across distinct tasks — the segment-sum: Σ(completed-task finals) +
    latest-within-active. Because the read already keeps exactly one (highest-id,
    non-NULL-cost) row **per** ``task_index``, this is neither a flat
    ``SUM`` over events (no double-count) nor keep-latest-overall (no reset at the
    stage boundary): the figure climbs monotonically across stages toward the run
    total.

    **Codex (INV-8 / FR-06-1a):** ``cost_usd`` is returned ``None`` (the meter
    renders "—") and ``cost_excluded`` is ``True`` so the run is excluded from
    spend — but its **tokens still count** (the same segment-sum, summed
    regardless of agent).
    """
    agent = run.get("agent")
    excluded = is_cost_excluded_agent(agent)
    segments = await repository.read_run_segments(str(run["id"]))

    cost = 0.0
    turns = 0
    tokens_in = 0
    tokens_out = 0
    for seg in segments:
        # task_index is the dedup key (INV-7): one segment per task. The cost on
        # this row is that task's last cumulative line — its final if completed,
        # its latest if active.
        _task_index = seg.get("task_index")
        cost += float(seg.get("cost_usd") or 0.0)
        payload = _payload(seg.get("payload_json"))
        turns += _segment_turns(payload)
        seg_in, seg_out = _segment_tokens(payload)
        tokens_in += seg_in
        tokens_out += seg_out

    # Tokens may also be back-filled on the run row at completion (the §6.5
    # snapshot the supervisor writes) — prefer the larger so a finished run whose
    # events were retention-pruned still shows its tokens.
    tokens_in = max(tokens_in, _int(run.get("tokens_in")))
    tokens_out = max(tokens_out, _int(run.get("tokens_out")))
    turns = max(turns, _int(run.get("turns")))

    return RunMeters(
        cost_usd=None if excluded else cost,
        turns=turns,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_excluded=excluded,
    )


def meters_payload(meters: RunMeters) -> dict[str, Any]:
    """Project :class:`RunMeters` to the §8.3 meters-row wire shape.

    ``cost_usd`` is ``null`` for a Codex run (the UI renders "—"); ``cost_excluded``
    tells the client this is the unpriced-agent case (so it shows "—" rather than
    a genuine ``$0.00``).
    """
    return {
        "cost_usd": meters.cost_usd,
        "cost_excluded": meters.cost_excluded,
        "turns": meters.turns,
        "tokens_in": meters.tokens_in,
        "tokens_out": meters.tokens_out,
    }
