"""``GET /api/v1/audit`` — the durable §8.6 audit trail, made reachable (G10).

The control plane durably appends security-relevant decisions (run launch, token
grant, egress denial, HITL resolution) to an ``audit.log`` JSONL via the
:class:`~app.security.audit.AuditLog` (INV-4 — redact-before-persist). Before G10
that trail had no read path, so an operator could not see what the platform did.
This endpoint surfaces it:

* **newest-first** — the most recent decisions first (the operational default);
* **paginated** — ``?limit&offset`` over the JSONL (the file can grow unboundedly,
  so the read is always bounded); returns ``{ items, total, next_offset }`` so a
  caller can page;
* **already redacted** — the records were scrubbed at *write* time (INV-4), so the
  read returns them verbatim; no secret can appear (no un-redact path exists);
* **graceful empty** — no audit file yet / an empty trail → ``{ items: [], total: 0,
  next_offset: null }`` rather than a 404/500.

It inherits the app access-control middleware (INV-1 — loopback ``Host`` + local
token + ``Origin``/CSRF), so the trail is NOT reachable without the local token.
Nothing here reaches into ``dkmv/`` — it reads the audit sink through the
:func:`app.api.deps.get_audit` seam only.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from app.api.deps import get_audit

#: No prefix here: the ``/api/v1`` version prefix is owned by the single parent
#: router in :mod:`app.api`.
router = APIRouter(tags=["audit"])

#: Default + max page size for the audit read (bounds an unboundedly-growing file).
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


@router.get("/audit")
def read_audit(
    request: Request,
    limit: int = Query(
        default=_DEFAULT_LIMIT,
        ge=1,
        le=_MAX_LIMIT,
        description="Page size (newest-first); capped so the unbounded JSONL stays bounded.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="How many newest records to skip (cursor over the newest-first order).",
    ),
) -> dict[str, Any]:
    """Return one newest-first page of the durable audit trail (G10 — authenticated).

    Resolves the lifespan-published :class:`~app.security.audit.AuditLog` via the
    :func:`app.api.deps.get_audit` seam and reads ``[offset : offset + limit]`` of its
    newest-first records. The records were redacted at write time (INV-4), so they are
    returned verbatim — no secret can appear. ``next_offset`` is the offset for the
    following page, or ``null`` when this page reached the end. When no audit sink is
    composed (a bare no-lifespan client) or the trail is empty / the file does not
    exist yet, returns an empty page gracefully. Behind INV-1 access control.
    """
    audit = get_audit(request)
    if audit is None:
        return {"items": [], "total": 0, "next_offset": None}
    records, total = audit.read_records(limit=limit, offset=offset)
    items = [record.to_json() for record in records]
    consumed = offset + len(items)
    next_offset = consumed if consumed < total else None
    return {"items": items, "total": total, "next_offset": next_offset}
