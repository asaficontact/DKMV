"""Create the four ``agent:*`` control-plane labels on connect (PRD §8.1).

The board state plane is a set of four single-occupancy GitHub labels —
``agent:queued | agent:in-progress | agent:paused | agent:review`` (§5.3.1). For
the board to render and for the state-machine writes (slice 1.3) to succeed, those
labels must **exist** on the repo. The PRD requires creating them **on connect if
absent** (§8.1).

This module owns **label creation only**. The ``set_agent_state`` *mutation*
primitive (assigning/clearing an ``agent:*`` label on an issue via
``PUT .../issues/{n}/labels`` replace-all) is slice 1.3 and is deliberately not
here — so nothing in this module performs an ``agent:*`` *transition*, and the
fictional label-patch endpoint that INV-11 forbids never appears (INV-11).

**Idempotent.** Creation is safe to re-run on every reconnect: a label that
already exists returns a 422 from GitHub's create-label endpoint, which we treat
as "already present" rather than an error (AC-4). The result reports which labels
were newly created vs. already there.

**Colors live here, not in the frontend tokens file.** These are *GitHub* label
colors (six-hex, no ``#``) that GitHub stores and renders — they are an API value,
not a UI design token, so they belong on the backend. The frontend renders board
state via its own ported ``--st-*`` tokens (INV-14), independent of GitHub's label
color.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.github.client import GitHubError


@dataclass(frozen=True, slots=True)
class AgentLabel:
    """One ``agent:*`` control-plane label spec (name + GitHub color + blurb)."""

    name: str
    #: GitHub label color: six hex digits, **no** leading ``#`` (GitHub's format).
    color: str
    description: str


#: The four control-plane labels (§8.1, §5.3.1), in board-column order. Colors are
#: GitHub label colors (six-hex, no ``#``) chosen to echo the design palette's
#: state hues (queued=slate, in-progress=blue, paused=amber, review=violet) so the
#: GitHub UI roughly mirrors the board — but the platform board uses its own
#: ported ``--st-*`` tokens, not these, for rendering (INV-14).
AGENT_LABELS: tuple[AgentLabel, ...] = (
    AgentLabel("agent:queued", "94a3b8", "DKMV: queued to run"),
    AgentLabel("agent:in-progress", "4f8cff", "DKMV: a run is live"),
    AgentLabel("agent:paused", "f5a623", "DKMV: run paused for a decision"),
    AgentLabel("agent:review", "a78bfa", "DKMV: PR open, awaiting human review"),
)

#: The bare names of the four labels — the ``agent:*`` set the state machine (1.3)
#: replaces over. Exposed so derivation/precedence logic shares one source.
AGENT_LABEL_NAMES: frozenset[str] = frozenset(label.name for label in AGENT_LABELS)


@dataclass(frozen=True, slots=True)
class EnsureLabelsResult:
    """Outcome of :func:`ensure_agent_labels`.

    ``created`` are the labels this call newly created; ``existing`` were already
    present (a 422 on create, treated as idempotent success). Their union is
    always the four :data:`AGENT_LABELS` names on success.
    """

    created: tuple[str, ...]
    existing: tuple[str, ...]


async def ensure_agent_labels(client: object, repo: str) -> EnsureLabelsResult:
    """Create any missing ``agent:*`` labels on ``repo`` (idempotent; §8.1, AC-4).

    For each of the four :data:`AGENT_LABELS`, ``POST /repos/{o}/{r}/labels``. A
    422 (GitHub's "label already exists") is **not** an error here — it means the
    label is already present, so a re-connect re-runs this safely without a
    duplicate-label failure (AC-4). Any other non-2xx surfaces as a
    :class:`GitHubError`.

    Note this is **label creation**, not an ``agent:*`` *transition*: no issue is
    labeled here. The label-on-issue mutation (``set_agent_state`` via
    ``PUT .../labels`` replace-all) is slice 1.3 (INV-11).

    ``client`` is duck-typed to expose an async ``create_label(repo, name, color,
    description)`` returning ``True`` when newly created and ``False`` when it
    already existed (the 422 idempotent case). The PAT client implements this;
    tests pass a fake.
    """
    create_label = getattr(client, "create_label", None)
    if create_label is None:  # pragma: no cover - guards a misuse, not a path
        raise GitHubError("GitHub client does not support label creation")

    created: list[str] = []
    existing: list[str] = []
    for label in AGENT_LABELS:
        was_created = await create_label(
            repo,
            name=label.name,
            color=label.color,
            description=label.description,
        )
        (created if was_created else existing).append(label.name)
    return EnsureLabelsResult(created=tuple(created), existing=tuple(existing))
