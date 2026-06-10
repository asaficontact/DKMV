"""G10 — GET /api/v1/audit makes the durable §8.6 audit trail reachable.

The control plane durably appends security decisions (run launch, token grant,
egress denial, HITL resolution) to ``audit.log``; before G10 there was no read path.
These tests lock in:

* the endpoint returns the recorded entries NEWEST-FIRST, paginated (``limit``/
  ``offset`` → ``{items, total, next_offset}``);
* the entries are secret-free (records were redacted at write time — INV-4);
* the empty / no-audit-file case is handled gracefully (200 + empty page);
* it is behind INV-1 access control (401 without the local token);
* the file-sink round-trip (read back what was written, malformed line skipped).
"""

from __future__ import annotations

from pathlib import Path

from app.secrets import Redactor
from app.security import AuditLog, FileAuditSink, MemoryAuditSink

from tests.conftest import auth_headers, build_client

# A non-real secret literal, assembled so the INV-4 source grep never flags it.
_FAKE_PAT = "ghp" + "_" + "Z" * 36  # noqa: S105 - fixture, not a real secret


def _publish_audit(client: object, audit: AuditLog) -> None:
    client.app.state.audit = audit  # type: ignore[attr-defined]


def _seed_three(audit: AuditLog) -> None:
    audit.record_run_launch(run_id="run-1", repo="acme/app", issue=1, agent="claude")
    audit.record_token_grant(run_id="run-2", repo="acme/app")
    audit.record_egress_denial(host="evil.example.com", run_id="run-3")


def test_returns_entries_newest_first() -> None:
    client = build_client()
    sink = MemoryAuditSink()
    audit = AuditLog(sink, redactor=Redactor(known_values=[_FAKE_PAT]))
    _seed_three(audit)
    _publish_audit(client, audit)

    body = client.get("/api/v1/audit", headers=auth_headers()).json()
    assert body["total"] == 3
    kinds = [item["kind"] for item in body["items"]]
    # Newest-first: the egress denial (last written) is first.
    assert kinds == ["egress_denial", "token_grant", "run_launch"]
    assert body["next_offset"] is None


def test_pagination_offset_limit() -> None:
    client = build_client()
    sink = MemoryAuditSink()
    audit = AuditLog(sink)
    _seed_three(audit)
    _publish_audit(client, audit)

    page1 = client.get("/api/v1/audit?limit=2", headers=auth_headers()).json()
    assert [i["kind"] for i in page1["items"]] == ["egress_denial", "token_grant"]
    assert page1["total"] == 3
    assert page1["next_offset"] == 2

    page2 = client.get("/api/v1/audit?limit=2&offset=2", headers=auth_headers()).json()
    assert [i["kind"] for i in page2["items"]] == ["run_launch"]
    assert page2["next_offset"] is None


def test_entries_are_secret_free() -> None:
    client = build_client()
    sink = MemoryAuditSink()
    audit = AuditLog(sink, redactor=Redactor(known_values=[_FAKE_PAT]))
    # A call site that (defensively) passes a token-shaped value into details; the
    # write-time redactor scrubs it, so the read must never surface it.
    audit.record_run_launch(run_id="run-x", repo="acme/app", workflow_id=_FAKE_PAT)
    _publish_audit(client, audit)

    resp = client.get("/api/v1/audit", headers=auth_headers())
    assert _FAKE_PAT not in resp.text


def test_empty_when_no_audit_sink() -> None:
    client = build_client()
    # Force no audit sink (a bare no-lifespan-style posture).
    client.app.state.audit = None  # type: ignore[attr-defined]
    body = client.get("/api/v1/audit", headers=auth_headers()).json()
    assert body == {"items": [], "total": 0, "next_offset": None}


def test_empty_when_file_missing(tmp_path: Path) -> None:
    client = build_client()
    # A file sink whose audit.log was never written (nothing audited yet).
    sink = FileAuditSink(tmp_path / "audit.log")
    _publish_audit(client, AuditLog(sink))
    body = client.get("/api/v1/audit", headers=auth_headers()).json()
    assert body == {"items": [], "total": 0, "next_offset": None}


def test_file_sink_roundtrip_and_skips_malformed(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    sink = FileAuditSink(path)
    audit = AuditLog(sink)
    _seed_three(audit)
    # Append a malformed line + a blank line — must be skipped, not crash the read.
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("{not valid json\n\n")

    records, total = sink.read_records(limit=10, offset=0)
    assert total == 3
    assert [r.kind.value for r in records] == ["egress_denial", "token_grant", "run_launch"]


def test_requires_token_inv1() -> None:
    client = build_client()
    resp = client.get("/api/v1/audit")  # no auth header
    assert resp.status_code == 401
