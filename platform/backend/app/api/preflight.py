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

from fastapi import APIRouter, Query, Request

from app.executor.runtime_policy import isolation_status
from app.github.client import GitHubAuthError, GitHubError, WritePermission
from app.github.provider import get_github_client

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dkmv.runtime import CapabilityReport

    from app.runtime import RunService

# No prefix here: the ``/api/v1`` version prefix is owned by the single parent
# router in :mod:`app.api`, which this router attaches to.
router = APIRouter(tags=["preflight"])


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


def _write_permission_row(perm: WritePermission) -> dict[str, Any]:
    """Render the effective-write-permission probe as a §8.9 check row (FR-01-6).

    This is a **hard** preflight row on the *selected* repo: a read-only token
    (``can_write=False``) is a blocker so the Connect flow fails fast at connect,
    not late at PR-creation time (§8.1). The sub-label names the role / missing
    scopes; it never carries the token value.
    """
    if perm.can_write:
        sub = f"can write ({perm.role})"
    elif perm.missing:
        sub = f"read-only ({perm.role}) — needs " + ", ".join(perm.missing)
    else:
        sub = f"read-only ({perm.role})"
    return {
        "id": "github_write",
        "label": f"Write access to {perm.repo}",
        "sub": sub,
        "ok": perm.can_write,
    }


@router.get("/preflight")
async def preflight(
    request: Request,
    repo: str | None = Query(
        default=None,
        description="Selected 'owner/name' repo to add an effective-write-permission check for.",
    ),
) -> dict[str, Any]:
    """Return the standing environment checklist (FR-01-6).

    Reads the configured :class:`RunService` off ``app.state`` and renders its
    ``get_capabilities()`` report into the §8.9 envelope. When ``repo`` is given
    (the picker's *selected* repo), an **effective-write-permission** probe row is
    appended (§8.1): a read-only token makes it a blocker so ``ready`` is
    ``false`` — the Connect preflight box surfaces ``preflight_blocked`` and the
    flow stops at connect rather than failing late at PR time (AC-2).
    """
    run_service: RunService = request.app.state.run_service
    report = run_service.get_capabilities()
    payload = build_preflight_payload(report)

    # ── gVisor sandbox-runtime check (G1 / INV-3, hard requirement) ────────────
    # Fail-closed: when SANDBOX_RUNTIME=runsc but the daemon has no runsc runtime
    # and the operator has not opted into the weaker fallback, this is a blocker so
    # the launch path refuses to start a run under bare runc.
    settings = request.app.state.settings
    ok, detail = isolation_status(
        settings.SANDBOX_RUNTIME,
        allow_weaker_isolation=settings.ALLOW_WEAKER_ISOLATION,
    )
    runtime_row = {
        "id": "sandbox_runtime",
        "label": "Sandbox isolation (gVisor)",
        "sub": detail,
        "ok": ok,
    }
    payload["checks"].append(runtime_row)
    if not ok:
        payload["blockers"].append(runtime_row["label"])
        payload["ready"] = False

    if repo is None:
        return payload

    settings = request.app.state.settings
    client = await get_github_client(request.app, settings)
    try:
        perm = await client.check_write_permission(repo)
    except GitHubAuthError:
        # The credential itself is bad/expired — a hard blocker (not a repo-level
        # permission shortfall). Surface as a synthetic failing write row.
        row = {
            "id": "github_write",
            "label": f"Write access to {repo}",
            "sub": "GitHub rejected the credential",
            "ok": False,
        }
    except GitHubError:
        row = {
            "id": "github_write",
            "label": f"Write access to {repo}",
            "sub": "could not verify (GitHub unreachable or repo not found)",
            "ok": False,
        }
    else:
        row = _write_permission_row(perm)

    payload["checks"].append(row)
    if not row["ok"]:
        payload["blockers"].append(row["label"])
        payload["ready"] = False
    return payload
