"""``GET /api/v1/preflight`` — standing environment checks (FR-01-6, §8.9).

The preflight endpoint renders the engine's component-agnostic health probe
(``EmbeddedRuntime.get_capabilities()``) as the §8.9 response envelope::

    { "ready": bool, "checks": [{ "id", "label", "sub", "ok" }], "blockers": [...] }

The engine returns a *flat* :class:`CapabilityReport` (booleans + a few strings);
this module is the mapping layer that turns those fields into the row-per-check
shape the UI's preflight checklist consumes, deriving ``ready`` and the
``blockers`` list from the rows the platform treats as hard requirements.

Hard requirements (a failing one is a blocker → ``ready: false``): Docker
available, the sandbox image present, and at least one model credential present
(Anthropic or Codex). GitHub connectivity is surfaced as a row but is *not* a
hard blocker for the standing checklist (private-repo clones fail later with a
clear error; per-launch ``preflight_check`` is the gate for an actual run,
FR-03-3).

This is a per-launch-independent **standing** check; it is read-only and takes
no body, so it is a safe GET behind the access-control middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import CapabilityReport

    from app.runtime import RunService

router = APIRouter(prefix="/api/v1", tags=["preflight"])


def _mask_key(present: bool) -> str:
    """Render a masked credential hint without ever echoing the value."""
    return "present" if present else "missing"


def build_preflight_payload(report: CapabilityReport) -> dict[str, Any]:
    """Map a flat :class:`CapabilityReport` to the §8.9 preflight envelope.

    Each ``check`` row is ``{id, label, sub, ok}``. ``blockers`` collects the
    human labels of the failing **hard-requirement** rows; ``ready`` is true iff
    there are none.
    """
    has_model_key = report.has_anthropic_key or report.has_codex_key

    # (id, label, sub, ok, is_hard_requirement)
    rows: list[tuple[str, str, str, bool, bool]] = [
        (
            "docker",
            "Docker available",
            report.docker_version or "docker engine not reachable",
            report.docker_available,
            True,
        ),
        (
            "sandbox_image",
            "Sandbox image present",
            report.image_name,
            report.image_exists,
            True,
        ),
        (
            "anthropic_key",
            "Anthropic API key",
            _mask_key(report.has_anthropic_key),
            report.has_anthropic_key,
            False,
        ),
        (
            "codex_key",
            "Codex API key",
            _mask_key(report.has_codex_key),
            report.has_codex_key,
            False,
        ),
        (
            "model_credential",
            "Model credential present",
            "Anthropic or Codex key required",
            has_model_key,
            True,
        ),
        (
            "github_token",
            "GitHub connected",
            _mask_key(report.has_github_token),
            report.has_github_token,
            False,
        ),
    ]

    checks: list[dict[str, Any]] = [
        {"id": id_, "label": label, "sub": sub, "ok": ok} for (id_, label, sub, ok, _hard) in rows
    ]
    blockers: list[str] = [label for (_id, label, _sub, ok, hard) in rows if hard and not ok]

    return {
        "ready": len(blockers) == 0,
        "checks": checks,
        "blockers": blockers,
    }


@router.get("/preflight")
def preflight(request: Request) -> dict[str, Any]:
    """Return the standing environment checklist (FR-01-6).

    Reads the configured :class:`RunService` off ``app.state`` and renders its
    ``get_capabilities()`` report into the §8.9 envelope.
    """
    run_service: RunService = request.app.state.run_service
    report = run_service.get_capabilities()
    return build_preflight_payload(report)
