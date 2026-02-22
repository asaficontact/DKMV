from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dkmv.tasks.discovery import (
    BUILTIN_COMPONENTS,
    ComponentNotFoundError,
    resolve_component,
)


class TestPathDetection:
    def test_string_with_slash_treated_as_path(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my" / "component"
        comp_dir.mkdir(parents=True)
        (comp_dir / "01-task.yaml").write_text("")
        result = resolve_component(str(comp_dir))
        assert result == comp_dir.resolve()

    def test_string_starting_with_dot_treated_as_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        comp_dir = tmp_path / "component"
        comp_dir.mkdir()
        (comp_dir / "task.yml").write_text("")
        monkeypatch.chdir(tmp_path)
        result = resolve_component("./component")
        assert result == comp_dir.resolve()

    def test_plain_name_treated_as_builtin(self, tmp_path: Path) -> None:
        builtin_dir = tmp_path / "dev"
        builtin_dir.mkdir()
        with patch("dkmv.tasks.discovery.files") as mock_files:
            mock_resource = MagicMock()
            mock_resource.__str__ = lambda self: str(builtin_dir)
            mock_files.return_value.joinpath.return_value = mock_resource
            result = resolve_component("dev")
            assert result == builtin_dir


class TestExplicitPathResolution:
    def test_relative_path_resolves_to_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        comp_dir = tmp_path / "tasks"
        comp_dir.mkdir()
        (comp_dir / "01.yaml").write_text("")
        monkeypatch.chdir(tmp_path)
        result = resolve_component("./tasks")
        assert result.is_absolute()
        assert result == comp_dir.resolve()

    def test_absolute_path_used_directly(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "comp"
        comp_dir.mkdir()
        (comp_dir / "task.yaml").write_text("")
        result = resolve_component(str(comp_dir))
        assert result == comp_dir.resolve()

    def test_nonexistent_directory_raises(self) -> None:
        with pytest.raises(ComponentNotFoundError, match="Directory not found"):
            resolve_component("/nonexistent/path/to/component")

    def test_directory_without_yaml_raises(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "empty"
        comp_dir.mkdir()
        (comp_dir / "readme.md").write_text("hi")
        with pytest.raises(ComponentNotFoundError, match="No task YAML files"):
            resolve_component(str(comp_dir))

    def test_directory_with_yaml_succeeds(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "comp"
        comp_dir.mkdir()
        (comp_dir / "01-plan.yaml").write_text("")
        (comp_dir / "02-impl.yml").write_text("")
        result = resolve_component(str(comp_dir))
        assert result == comp_dir.resolve()

    def test_directory_with_tasks_subdir(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "comp"
        comp_dir.mkdir()
        tasks_dir = comp_dir / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "01-plan.yaml").write_text("")
        result = resolve_component(str(comp_dir))
        assert result == comp_dir.resolve()

    def test_directory_with_no_yaml_in_root_but_tasks_subdir(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "comp"
        comp_dir.mkdir()
        (comp_dir / "readme.md").write_text("hi")
        tasks_dir = comp_dir / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "01-plan.yaml").write_text("")
        result = resolve_component(str(comp_dir))
        assert result == comp_dir.resolve()


class TestBuiltinResolution:
    def test_known_builtin_resolves(self, tmp_path: Path) -> None:
        builtin_dir = tmp_path / "qa"
        builtin_dir.mkdir()
        with patch("dkmv.tasks.discovery.files") as mock_files:
            mock_resource = MagicMock()
            mock_resource.__str__ = lambda self: str(builtin_dir)
            mock_files.return_value.joinpath.return_value = mock_resource
            result = resolve_component("qa")
            mock_files.assert_called_once_with("dkmv.builtins")
            mock_files.return_value.joinpath.assert_called_once_with("qa")
            assert result == builtin_dir

    def test_builtin_missing_directory_raises(self) -> None:
        with patch("dkmv.tasks.discovery.files") as mock_files:
            mock_resource = MagicMock()
            mock_resource.__str__ = lambda self: "/nonexistent/builtins/dev"
            mock_files.return_value.joinpath.return_value = mock_resource
            with pytest.raises(ComponentNotFoundError, match="package directory not found"):
                resolve_component("dev")

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(ComponentNotFoundError, match="Unknown component 'custom'"):
            resolve_component("custom")

    def test_error_lists_available_builtins(self) -> None:
        with pytest.raises(ComponentNotFoundError) as exc_info:
            resolve_component("notreal")
        msg = str(exc_info.value)
        for name in BUILTIN_COMPONENTS:
            assert name in msg

    def test_all_builtins_recognized(self) -> None:
        assert BUILTIN_COMPONENTS == {"dev", "qa", "judge", "docs"}
