"""Slice 2.1 — unit tests for the :mod:`app.runs.launch` pure helpers.

Exercises the validation/resolution helpers directly (no HTTP) so the §8.10 edge
branches are covered deterministically: the idempotency-key composition (§8.2),
the local-context existence + traversal guards, the ``auto`` workflow-agent
resolution fallback (FR-03-3), and the ``on_pause`` pass-through placeholder
(slice-2.5 seam).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from app.api.errors import ApiError
from app.runs.launch import (
    _passthrough_on_pause,
    _resolve_workflow_agent,
    _validate_context_paths,
    idempotency_key,
    resolve_agent,
)


def test_idempotency_key_is_issue_workflow_branch() -> None:
    # §8.2: issue_num + workflow_id + base_branch (NOT a hash of the body).
    key = idempotency_key(7, "qa", "dkmv/issue-7")
    assert "7" in key and "qa" in key and "dkmv/issue-7" in key
    # Deterministic — a retry reuses the same key.
    assert key == idempotency_key(7, "qa", "dkmv/issue-7")


def test_resolve_agent_explicit_passthrough() -> None:
    assert resolve_agent("codex", "qa") == "codex"
    assert resolve_agent("claude", "qa") == "claude"


def test_resolve_agent_auto_resolves_to_concrete() -> None:
    # auto → workflow.agent (or its model-implied agent / the Claude default).
    assert resolve_agent("auto", "qa") in {"claude", "codex"}


def test_resolve_workflow_agent_unknown_falls_back_to_default() -> None:
    # An unresolvable workflow falls back to the platform default rather than
    # raising (the validate_component check already surfaced the real error).
    assert _resolve_workflow_agent("no-such-workflow-xyz") == "claude"


def test_context_local_existence_ok(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("hi", encoding="utf-8")
    resolved = _validate_context_paths(["notes.md"], project_root=tmp_path)
    assert resolved[0].name == "notes.md"


def test_context_local_missing_rejected(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as exc:
        _validate_context_paths(["missing.md"], project_root=tmp_path)
    assert exc.value.status_code == 400


def test_context_absolute_path_rejected() -> None:
    with pytest.raises(ApiError):
        _validate_context_paths(["/etc/passwd"], project_root=None)


def test_context_traversal_rejected_remote() -> None:
    with pytest.raises(ApiError):
        _validate_context_paths(["../secret"], project_root=None)


def test_context_empty_rejected() -> None:
    with pytest.raises(ApiError):
        _validate_context_paths([" "], project_root=None)


def test_passthrough_on_pause_is_noop() -> None:
    # The slice-2.5 placeholder returns None (mirrors the engine's no-on_pause skip).
    assert asyncio.new_event_loop().run_until_complete(_passthrough_on_pause(object())) is None
