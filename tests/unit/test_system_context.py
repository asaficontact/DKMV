from __future__ import annotations

from dkmv.tasks.system_context import DKMV_SYSTEM_CONTEXT


class TestSystemContext:
    def test_system_context_is_non_empty(self) -> None:
        assert len(DKMV_SYSTEM_CONTEXT) > 100

    def test_system_context_contains_agent_identity(self) -> None:
        assert "DKMV Agent" in DKMV_SYSTEM_CONTEXT

    def test_system_context_contains_workspace_path(self) -> None:
        assert "/home/dkmv/workspace/" in DKMV_SYSTEM_CONTEXT

    def test_system_context_contains_agent_dir(self) -> None:
        assert ".agent/" in DKMV_SYSTEM_CONTEXT

    def test_system_context_contains_git_rules(self) -> None:
        assert "git" in DKMV_SYSTEM_CONTEXT.lower()
        assert "commit" in DKMV_SYSTEM_CONTEXT.lower()

    def test_system_context_contains_core_rules(self) -> None:
        assert "Core Rules" in DKMV_SYSTEM_CONTEXT

    def test_system_context_importable_from_package(self) -> None:
        from dkmv.tasks import DKMV_SYSTEM_CONTEXT as imported

        assert imported is DKMV_SYSTEM_CONTEXT
