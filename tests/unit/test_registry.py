from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dkmv.cli import app
from dkmv.registry import ComponentRegistry

runner = CliRunner()


def _init_registry(tmp_path: Path, entries: dict[str, str] | None = None) -> None:
    """Create .dkmv/components.json with optional entries."""
    dkmv_dir = tmp_path / ".dkmv"
    dkmv_dir.mkdir(exist_ok=True)
    (dkmv_dir / "components.json").write_text(json.dumps(entries or {}, indent=2) + "\n")


def _make_component(tmp_path: Path, name: str, yaml_name: str = "01-task.yaml") -> Path:
    """Create a component directory with a YAML file."""
    comp_dir = tmp_path / name
    comp_dir.mkdir(exist_ok=True)
    (comp_dir / yaml_name).write_text("name: test")
    return comp_dir


# ── Load/Save ────────────────────────────────────────────────────────


class TestLoadSave:
    def test_load_empty_registry(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        result = ComponentRegistry.load(tmp_path)
        assert result == {}

    def test_load_with_entries(self, tmp_path: Path) -> None:
        _init_registry(tmp_path, {"my-comp": "./my-component"})
        result = ComponentRegistry.load(tmp_path)
        assert result == {"my-comp": "./my-component"}

    def test_load_no_file_returns_empty(self, tmp_path: Path) -> None:
        result = ComponentRegistry.load(tmp_path)
        assert result == {}

    def test_save_writes_json(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        ComponentRegistry.save(tmp_path, {"comp": "/path/to/comp"})
        content = (tmp_path / ".dkmv" / "components.json").read_text()
        assert json.loads(content) == {"comp": "/path/to/comp"}
        assert content.endswith("\n")


# ── Register ─────────────────────────────────────────────────────────


class TestRegister:
    def test_register_absolute_path(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        comp_dir = _make_component(tmp_path, "my-component")
        result = ComponentRegistry.register(tmp_path, "my-comp", str(comp_dir))
        assert result == comp_dir
        registry = ComponentRegistry.load(tmp_path)
        assert registry["my-comp"] == str(comp_dir)

    def test_register_relative_path(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        _make_component(tmp_path, "my-component")
        result = ComponentRegistry.register(tmp_path, "my-comp", "my-component")
        assert result == (tmp_path / "my-component").resolve()
        registry = ComponentRegistry.load(tmp_path)
        assert registry["my-comp"] == "my-component"

    def test_register_returns_resolved_path(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        _make_component(tmp_path, "comp")
        result = ComponentRegistry.register(tmp_path, "x", "comp")
        assert result.is_absolute()

    def test_rejects_builtin_name(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        comp_dir = _make_component(tmp_path, "dev-dir")
        with pytest.raises(ValueError, match="conflicts with built-in"):
            ComponentRegistry.register(tmp_path, "dev", str(comp_dir))

    def test_rejects_duplicate(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        comp_dir = _make_component(tmp_path, "comp")
        ComponentRegistry.register(tmp_path, "my-comp", str(comp_dir))
        with pytest.raises(ValueError, match="already registered"):
            ComponentRegistry.register(tmp_path, "my-comp", str(comp_dir))

    def test_force_overwrites(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        comp1 = _make_component(tmp_path, "comp1")
        comp2 = _make_component(tmp_path, "comp2")
        ComponentRegistry.register(tmp_path, "my-comp", str(comp1))
        result = ComponentRegistry.register(tmp_path, "my-comp", str(comp2), force=True)
        assert result == comp2

    def test_rejects_nonexistent_dir(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        with pytest.raises(ValueError, match="Not a directory"):
            ComponentRegistry.register(tmp_path, "x", str(tmp_path / "nonexistent"))

    def test_rejects_no_yaml(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        comp_dir = tmp_path / "empty-comp"
        comp_dir.mkdir()
        (comp_dir / "readme.md").write_text("hi")
        with pytest.raises(ValueError, match="No YAML task files"):
            ComponentRegistry.register(tmp_path, "x", str(comp_dir))

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        outside_dir = tmp_path.parent / "outside-component"
        outside_dir.mkdir(exist_ok=True)
        (outside_dir / "01-task.yaml").write_text("name: test")
        with pytest.raises(ValueError, match="must be within the project root"):
            ComponentRegistry.register(tmp_path, "evil", str(outside_dir))

    def test_rejects_relative_path_traversal(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        outside_dir = tmp_path.parent / "outside-component"
        outside_dir.mkdir(exist_ok=True)
        (outside_dir / "01-task.yaml").write_text("name: test")
        with pytest.raises(ValueError, match="must be within the project root"):
            ComponentRegistry.register(tmp_path, "evil", "../outside-component")

    def test_accepts_tasks_subdir_yaml(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        comp_dir = tmp_path / "comp"
        comp_dir.mkdir()
        tasks_dir = comp_dir / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "01-task.yaml").write_text("name: test")
        result = ComponentRegistry.register(tmp_path, "x", str(comp_dir))
        assert result == comp_dir


# ── Unregister ───────────────────────────────────────────────────────


class TestUnregister:
    def test_removes_entry(self, tmp_path: Path) -> None:
        _init_registry(tmp_path, {"my-comp": "./comp"})
        ComponentRegistry.unregister(tmp_path, "my-comp")
        assert ComponentRegistry.load(tmp_path) == {}

    def test_rejects_unknown(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        with pytest.raises(ValueError, match="not registered"):
            ComponentRegistry.unregister(tmp_path, "unknown")

    def test_preserves_other_entries(self, tmp_path: Path) -> None:
        _init_registry(tmp_path, {"a": "./a", "b": "./b"})
        ComponentRegistry.unregister(tmp_path, "a")
        registry = ComponentRegistry.load(tmp_path)
        assert "a" not in registry
        assert registry["b"] == "./b"


# ── list_all ─────────────────────────────────────────────────────────


class TestListAll:
    def test_no_project_root_returns_builtins_only(self) -> None:
        infos = ComponentRegistry.list_all()
        names = {i.name for i in infos}
        assert names == {"dev", "qa", "docs", "plan", "ship"}
        for info in infos:
            assert info.component_type == "built-in"

    def test_empty_registry_returns_builtins_only(self, tmp_path: Path) -> None:
        _init_registry(tmp_path)
        infos = ComponentRegistry.list_all(tmp_path)
        assert all(i.component_type == "built-in" for i in infos)

    def test_with_registered_component(self, tmp_path: Path) -> None:
        comp_dir = _make_component(tmp_path, "my-component")
        _init_registry(tmp_path, {"my-comp": str(comp_dir)})
        infos = ComponentRegistry.list_all(tmp_path)
        custom = [i for i in infos if i.component_type == "custom"]
        assert len(custom) == 1
        assert custom[0].name == "my-comp"
        assert custom[0].task_count == 1
        assert custom[0].valid is True

    def test_stale_path_marked_invalid(self, tmp_path: Path) -> None:
        _init_registry(tmp_path, {"stale": "/nonexistent/path"})
        infos = ComponentRegistry.list_all(tmp_path)
        custom = [i for i in infos if i.component_type == "custom"]
        assert len(custom) == 1
        assert custom[0].valid is False
        assert custom[0].task_count == 0

    def test_builtin_info_correct(self) -> None:
        infos = ComponentRegistry.list_all()
        dev = next(i for i in infos if i.name == "dev")
        assert dev.component_type == "built-in"
        assert dev.task_count == 2  # implement-phase.yaml, component.yaml
        assert dev.description == "Plan and implement features from a PRD"


# ── CLI Commands ─────────────────────────────────────────────────────


class TestComponentsCLI:
    def test_components_without_init(self) -> None:
        result = runner.invoke(app, ["components"])
        assert result.exit_code == 0
        assert "dev" in result.output
        assert "qa" in result.output
        assert "plan" in result.output
        assert "docs" in result.output
        assert "built-in" in result.output

    def test_components_with_registered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        comp_dir = _make_component(tmp_path, "my-component")
        _init_registry(tmp_path, {"my-comp": str(comp_dir)})
        # Also need config.json for find_project_root to work
        (tmp_path / ".dkmv" / "config.json").write_text(
            '{"version": 1, "project_name": "test", "repo": "https://github.com/test/test"}\n'
        )
        result = runner.invoke(app, ["components"])
        assert result.exit_code == 0
        assert "my-comp" in result.output
        assert "custom" in result.output


class TestRegisterCLI:
    def test_register_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_registry(tmp_path)
        (tmp_path / ".dkmv" / "config.json").write_text(
            '{"version": 1, "project_name": "test", "repo": "https://github.com/test/test"}\n'
        )
        comp_dir = _make_component(tmp_path, "my-component")
        result = runner.invoke(app, ["register", "my-comp", str(comp_dir)])
        assert result.exit_code == 0
        assert "Registered" in result.output
        assert "1 task" in result.output

    def test_register_without_init_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["register", "x", "."])
        assert result.exit_code == 1
        assert "not initialized" in result.output


class TestUnregisterCLI:
    def test_unregister_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_registry(tmp_path, {"my-comp": "./comp"})
        (tmp_path / ".dkmv" / "config.json").write_text(
            '{"version": 1, "project_name": "test", "repo": "https://github.com/test/test"}\n'
        )
        result = runner.invoke(app, ["unregister", "my-comp"])
        assert result.exit_code == 0
        assert "Unregistered" in result.output

    def test_unregister_without_init_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["unregister", "x"])
        assert result.exit_code == 1
        assert "not initialized" in result.output
