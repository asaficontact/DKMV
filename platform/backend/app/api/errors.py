"""API error envelope + status-code conventions (PRD §8.9).

Every non-2xx response from the platform API carries the binding envelope::

    { "error": { "code": "<machine_code>", "message": "<human>", "details"?: {...} } }

This module is the single place that shape is produced. It exposes:

* :class:`ApiError` — the exception the handlers (and route code) raise. It
  carries the HTTP status, the machine ``code``, a human ``message`` and an
  optional ``details`` mapping.
* A small library of ``ApiError`` factories for the §8.9 codes used in Phase 0
  (``validation_error``, ``run_not_found``, ``unauthorized``, ``forbidden`` …).
* :func:`install_error_handlers` — registers exception handlers on a FastAPI
  app so that ``ApiError``, FastAPI/Pydantic ``RequestValidationError`` and any
  uncaught exception all serialize into the envelope with the right status.

Status-code conventions implemented here (PRD §8.9):

===== ==========================================================
Code  Meaning
===== ==========================================================
400   validation (``code: validation_error`` + field details)
401   missing / invalid local token (``code: unauthorized``)
403   Host/Origin/CSRF rejected (``code: forbidden``)
404   not found
409   conflict (``duplicate_dispatch``, ``pause_already_resolved`` …)
429   rate-limited (surfaces ``Retry-After``)
500   internal (``internal_error``)
===== ==========================================================

**The 404 contract carries a semantic top-level code (PRD §8.9, AC-0.2-5).**
Domain 404s expose a *specific* machine ``code`` so a client can branch on the
case without inspecting ``details``: :func:`run_not_found` → ``run_not_found``
and :func:`issue_not_found` → ``issue_not_found`` (each also surfaces a
``details.resource`` discriminator for convenience). The generic ``not_found``
code is reserved for the **framework fallback only** — an unmatched route or a
bare ``HTTPException(404)`` that no domain helper produced.

Nothing here reaches into ``dkmv/`` or logs a secret value.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    """An error that serializes into the PRD §8.9 envelope.

    Args:
        status_code: HTTP status to return.
        code: Stable machine-readable error code (e.g. ``run_not_found``).
        message: Human-readable description (never embeds a secret value).
        details: Optional structured detail (e.g. per-field validation errors).
        headers: Optional response headers (e.g. ``Retry-After`` on 429).
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers

    def to_envelope(self) -> dict[str, Any]:
        """Render the ``{ "error": { code, message, details? } }`` body."""
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}

    def to_response(self) -> JSONResponse:
        """Render a :class:`JSONResponse` with the envelope + headers."""
        return JSONResponse(
            status_code=self.status_code,
            content=self.to_envelope(),
            headers=self.headers,
        )


# ── §8.9 factory helpers (the codes Phase 0 surfaces) ────────────────────────


def validation_error(message: str, details: dict[str, Any] | None = None) -> ApiError:
    """400 — request body/params failed validation (PRD §8.9, §8.10)."""
    return ApiError(400, "validation_error", message, details=details)


def unauthorized(message: str = "Missing or invalid local token") -> ApiError:
    """401 — the local auth token is missing or wrong (NFR-SEC-2)."""
    return ApiError(401, "unauthorized", message)


def forbidden(message: str = "Host/Origin/CSRF check failed") -> ApiError:
    """403 — Host/Origin/CSRF rejection (anti-DNS-rebinding, NFR-SEC-2)."""
    return ApiError(403, "forbidden", message)


# The generic 404 code, reserved for the framework fallback only — an unmatched
# route or a bare ``HTTPException(404)`` that no domain helper produced (PRD §8.9).
NOT_FOUND_CODE = "not_found"


def not_found(message: str = "Not found", *, resource: str | None = None) -> ApiError:
    """404 — the generic not-found error (framework fallback; ``not_found``).

    Domain code should prefer the semantic helpers (:func:`run_not_found`,
    :func:`issue_not_found`); this generic form is for cases with no specific
    resource. ``resource`` (if given) is surfaced under ``details.resource``.
    """
    details = {"resource": resource} if resource is not None else None
    return ApiError(404, NOT_FOUND_CODE, message, details=details)


def run_not_found(run_id: str) -> ApiError:
    """404 — no run with this platform UUID.

    Carries the **semantic top-level code** ``run_not_found`` (AC-0.2-5, §8.9),
    plus a ``details.resource: run`` discriminator for convenience.
    """
    return ApiError(
        404,
        "run_not_found",
        f"Run {run_id} not found",
        details={"resource": "run"},
    )


def issue_not_found(repo: str, num: int) -> ApiError:
    """404 — no cached issue for ``repo#num``.

    Carries the **semantic top-level code** ``issue_not_found`` (AC-0.2-5,
    §8.9), plus a ``details.resource: issue`` discriminator for convenience.
    """
    return ApiError(
        404,
        "issue_not_found",
        f"Issue {repo}#{num} not found",
        details={"resource": "issue"},
    )


def preflight_blocked(blockers: list[str]) -> ApiError:
    """409 — environment preflight has unresolved blockers (PRD §8.9)."""
    return ApiError(
        409,
        "preflight_blocked",
        "Environment preflight failed",
        details={"blockers": blockers},
    )


def internal_error(message: str = "Internal server error") -> ApiError:
    """500 — uncaught/unexpected server failure (PRD §8.9)."""
    return ApiError(500, "internal_error", message)


# ── Exception handlers ───────────────────────────────────────────────────────


async def _api_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Serialize a raised :class:`ApiError` into the envelope."""
    assert isinstance(exc, ApiError)  # registered only for ApiError
    return exc.to_response()


async def _validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Map FastAPI/Pydantic validation failures to a 400 envelope.

    The raw ``RequestValidationError.errors()`` list is surfaced under
    ``details.fields`` so clients can map errors back to inputs (PRD §8.10).
    """
    assert isinstance(exc, RequestValidationError)
    err = validation_error(
        "Request validation failed",
        details={"fields": _jsonable_errors(exc.errors())},
    )
    return err.to_response()


async def _http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Wrap Starlette/FastAPI ``HTTPException`` in the envelope.

    Routes should prefer :class:`ApiError`, but framework-raised
    ``HTTPException`` (e.g. an unmatched route → 404) is normalized here so the
    envelope is universal. A framework 404 carries the generic ``not_found``
    code; domain 404s use the semantic codes ``run_not_found`` /
    ``issue_not_found`` from the helpers above (see the module docstring).
    """
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_TO_CODE.get(exc.status_code, "error")
    message = exc.detail if isinstance(exc.detail, str) else _STATUS_TO_MESSAGE.get(code, code)
    api = ApiError(exc.status_code, code, message)
    headers = getattr(exc, "headers", None)
    if headers:
        api.headers = dict(headers)
    return api.to_response()


async def _unhandled_handler(_request: Request, _exc: Exception) -> JSONResponse:
    """Last-resort 500 — never leak a stack trace or secret to the client."""
    return internal_error().to_response()


_STATUS_TO_CODE: dict[int, str] = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: NOT_FOUND_CODE,
    409: "conflict",
    429: "rate_limited",
    500: "internal_error",
}

# Human-readable fallback message when the framework HTTPException carries no
# string ``detail`` (keyed by the machine code above).
_STATUS_TO_MESSAGE: dict[str, str] = {
    "validation_error": "Request validation failed",
    "unauthorized": "Missing or invalid local token",
    "forbidden": "Host/Origin/CSRF check failed",
    NOT_FOUND_CODE: "Not found",
    "conflict": "Conflict",
    "rate_limited": "Rate limited",
    "internal_error": "Internal server error",
}


def _jsonable_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Reduce Pydantic error dicts to JSON-safe ``loc/msg/type`` entries.

    Pydantic v2 error dicts can carry a non-serializable ``ctx`` (e.g. an
    exception instance); we keep only the stable, serializable fields.
    """
    out: list[dict[str, Any]] = []
    for e in errors:
        out.append(
            {
                "loc": list(e.get("loc", [])),
                "msg": str(e.get("msg", "")),
                "type": str(e.get("type", "")),
            }
        )
    return out


def install_error_handlers(app: FastAPI) -> None:
    """Register the envelope handlers on ``app`` (idempotent per app)."""
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
