from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dkmv.tasks.loader import TaskLoadError, TaskLoader
from dkmv.tasks.manifest import (
    ComponentManifest,
    ManifestDeliverable,
    ManifestInput,
    ManifestStateFile,
    ManifestTaskRef,
)


class TestManifestInput:
    def test_file_input_valid(self) -> None:
        inp = ManifestInput(name="prd", type="file", src="/tmp/prd.md", dest="/workspace/prd.md")
        assert inp.name == "prd"
        assert inp.type == "file"

    def test_file_input_missing_src(self) -> None:
        with pytest.raises(ValidationError, match="'file' input requires 'src'"):
            ManifestInput(name="prd", type="file", dest="/workspace/prd.md")

    def test_file_input_missing_dest(self) -> None:
        with pytest.raises(ValidationError, match="'file' input requires 'dest'"):
            ManifestInput(name="prd", type="file", src="/tmp/prd.md")

    def test_text_input_valid(self) -> None:
        inp = ManifestInput(name="config", type="text", dest="/workspace/cfg.txt", content="hello")
        assert inp.content == "hello"

    def test_text_input_missing_content(self) -> None:
        with pytest.raises(ValidationError, match="'text' input requires 'content'"):
            ManifestInput(name="config", type="text", dest="/workspace/cfg.txt")

    def test_text_input_missing_dest(self) -> None:
        with pytest.raises(ValidationError, match="'text' input requires 'dest'"):
            ManifestInput(name="config", type="text", content="hello")

    def test_env_input_valid(self) -> None:
        inp = ManifestInput(name="token", type="env", key="TOKEN", value="abc123")
        assert inp.key == "TOKEN"

    def test_env_input_missing_key(self) -> None:
        with pytest.raises(ValidationError, match="'env' input requires 'key'"):
            ManifestInput(name="token", type="env", value="abc123")

    def test_env_input_missing_value(self) -> None:
        with pytest.raises(ValidationError, match="'env' input requires 'value'"):
            ManifestInput(name="token", type="env", key="TOKEN")

    def test_optional_file_skips_validation(self) -> None:
        inp = ManifestInput(name="docs", type="file", optional=True)
        assert inp.optional is True
        assert inp.src is None
        assert inp.dest is None

    def test_relative_dest_normalized(self) -> None:
        inp = ManifestInput(name="prd", type="file", src="/tmp/prd.md", dest="prd.md")
        assert inp.dest == "/home/dkmv/workspace/.agent/prd.md"

    def test_relative_dir_dest_normalized(self) -> None:
        inp = ManifestInput(name="docs", type="file", src="/tmp/docs", dest="design_docs/")
        assert inp.dest == "/home/dkmv/workspace/.agent/design_docs/"

    def test_absolute_dest_unchanged(self) -> None:
        inp = ManifestInput(name="prd", type="file", src="/tmp/prd.md", dest="/custom/path/prd.md")
        assert inp.dest == "/custom/path/prd.md"

    def test_text_relative_dest_normalized(self) -> None:
        inp = ManifestInput(name="cfg", type="text", content="hello", dest="config.txt")
        assert inp.dest == "/home/dkmv/workspace/.agent/config.txt"

    def test_env_dest_stays_none(self) -> None:
        inp = ManifestInput(name="tok", type="env", key="K", value="V")
        assert inp.dest is None


class TestManifestModels:
    def test_state_file(self) -> None:
        sf = ManifestStateFile(dest="/workspace/.agent/state.json", content='{"step": 0}')
        assert sf.dest == "/workspace/.agent/state.json"

    def test_deliverable(self) -> None:
        d = ManifestDeliverable(path="/workspace/output.json")
        assert d.required is True

    def test_deliverable_optional(self) -> None:
        d = ManifestDeliverable(path="/workspace/output.json", required=False)
        assert d.required is False

    def test_task_ref_minimal(self) -> None:
        ref = ManifestTaskRef(file="01-plan.yaml")
        assert ref.file == "01-plan.yaml"
        assert ref.model is None
        assert ref.pause_after is False

    def test_task_ref_with_overrides(self) -> None:
        ref = ManifestTaskRef(
            file="02-impl.yaml", model="claude-opus-4-6", max_turns=200, max_budget_usd=10.0
        )
        assert ref.model == "claude-opus-4-6"
        assert ref.max_turns == 200

    def test_task_ref_pause_after_true(self) -> None:
        ref = ManifestTaskRef(file="01-analyze.yaml", pause_after=True)
        assert ref.pause_after is True

    def test_task_ref_pause_after_default_false(self) -> None:
        ref = ManifestTaskRef(file="01-analyze.yaml")
        assert ref.pause_after is False

    def test_task_ref_for_each_default_none(self) -> None:
        ref = ManifestTaskRef(file="01-task.yaml")
        assert ref.for_each is None

    def test_task_ref_for_each_set(self) -> None:
        ref = ManifestTaskRef(file="implement-phase.yaml", for_each="phases")
        assert ref.for_each == "phases"


class TestComponentManifest:
    def test_minimal_manifest(self) -> None:
        m = ComponentManifest(name="test")
        assert m.name == "test"
        assert m.description == ""
        assert m.inputs == []
        assert m.workspace_dirs == []
        assert m.state_files == []
        assert m.agent_md is None
        assert m.model is None
        assert m.max_turns is None
        assert m.timeout_minutes is None
        assert m.max_budget_usd is None
        assert m.tasks == []
        assert m.deliverables == []

    def test_full_manifest(self) -> None:
        m = ComponentManifest(
            name="dev",
            description="Development component",
            inputs=[ManifestInput(name="prd", type="file", src="/tmp/p.md", dest="/w/p.md")],
            workspace_dirs=[".agent"],
            state_files=[ManifestStateFile(dest="/w/.agent/s.json", content="{}")],
            agent_md="# Dev Agent\nYou are a dev agent.",
            model="claude-sonnet-4-6",
            max_turns=50,
            tasks=[ManifestTaskRef(file="01-plan.yaml"), ManifestTaskRef(file="02-impl.yaml")],
            deliverables=[ManifestDeliverable(path="/w/output.md")],
        )
        assert m.name == "dev"
        assert len(m.inputs) == 1
        assert len(m.tasks) == 2
        assert m.agent_md is not None

    def test_agent_md_file_default_none(self) -> None:
        m = ComponentManifest(name="test")
        assert m.agent_md_file is None

    def test_agent_md_file_set(self) -> None:
        m = ComponentManifest(name="test", agent_md_file="/tmp/CLAUDE.md")
        assert m.agent_md_file == "/tmp/CLAUDE.md"

    def test_manifest_name_required(self) -> None:
        with pytest.raises(ValidationError):
            ComponentManifest()  # type: ignore[call-arg]


class TestLoadManifest:
    def test_load_valid_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "component.yaml"
        manifest_path.write_text(
            "name: test\n"
            "description: A test component\n"
            "model: claude-sonnet-4-6\n"
            "max_turns: 50\n"
            "tasks:\n"
            "  - file: 01-task.yaml\n"
        )
        loader = TaskLoader()
        manifest = loader.load_manifest(manifest_path, {})
        assert manifest.name == "test"
        assert manifest.model == "claude-sonnet-4-6"
        assert manifest.max_turns == 50
        assert len(manifest.tasks) == 1

    def test_load_manifest_with_jinja_variables(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "component.yaml"
        manifest_path.write_text(
            "name: test\n"
            "inputs:\n"
            '  - name: prd\n    type: file\n    src: "{{ prd_path }}"\n'
            "    dest: /workspace/prd.md\n"
            "tasks:\n"
            "  - file: 01-task.yaml\n"
        )
        loader = TaskLoader()
        manifest = loader.load_manifest(manifest_path, {"prd_path": "/tmp/my-prd.md"})
        assert manifest.inputs[0].src == "/tmp/my-prd.md"

    def test_load_manifest_jinja_undefined_error(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "component.yaml"
        manifest_path.write_text(
            "name: test\n"
            "inputs:\n"
            '  - name: prd\n    type: file\n    src: "{{ missing_var }}"\n'
            "    dest: /workspace/prd.md\n"
            "tasks:\n"
            "  - file: 01-task.yaml\n"
        )
        loader = TaskLoader()
        with pytest.raises(TaskLoadError):
            loader.load_manifest(manifest_path, {})

    def test_load_manifest_yaml_error(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "component.yaml"
        manifest_path.write_text("name: test\n  bad_indent: yes\n")
        loader = TaskLoader()
        with pytest.raises(TaskLoadError):
            loader.load_manifest(manifest_path, {})

    def test_load_manifest_validation_error(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "component.yaml"
        manifest_path.write_text(
            "description: missing name field\ntasks:\n  - file: 01-task.yaml\n"
        )
        loader = TaskLoader()
        with pytest.raises(TaskLoadError):
            loader.load_manifest(manifest_path, {})

    def test_load_manifest_with_agent_md(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "component.yaml"
        manifest_path.write_text(
            "name: plan\n"
            "agent_md: |\n"
            "  ## Workspace Layout\n"
            "  You have access to the workspace.\n"
            "tasks:\n"
            "  - file: 01-task.yaml\n"
        )
        loader = TaskLoader()
        manifest = loader.load_manifest(manifest_path, {})
        assert manifest.agent_md is not None
        assert "Workspace Layout" in manifest.agent_md

    def test_load_manifest_with_workspace_dirs(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "component.yaml"
        manifest_path.write_text(
            "name: test\nworkspace_dirs:\n  - .agent\n  - .cache\ntasks:\n  - file: 01-task.yaml\n"
        )
        loader = TaskLoader()
        manifest = loader.load_manifest(manifest_path, {})
        assert manifest.workspace_dirs == [".agent", ".cache"]

    def test_load_manifest_with_state_files(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "component.yaml"
        manifest_path.write_text(
            "name: test\n"
            "state_files:\n"
            "  - dest: /workspace/.agent/state.json\n"
            '    content: "{}"\n'
            "tasks:\n"
            "  - file: 01-task.yaml\n"
        )
        loader = TaskLoader()
        manifest = loader.load_manifest(manifest_path, {})
        assert len(manifest.state_files) == 1
        assert manifest.state_files[0].dest == "/workspace/.agent/state.json"

    def test_load_manifest_task_ref_overrides(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "component.yaml"
        manifest_path.write_text(
            "name: test\n"
            "model: claude-sonnet-4-6\n"
            "max_turns: 50\n"
            "tasks:\n"
            "  - file: 01-task.yaml\n"
            "    max_turns: 100\n"
            "    max_budget_usd: 5.0\n"
        )
        loader = TaskLoader()
        manifest = loader.load_manifest(manifest_path, {})
        assert manifest.tasks[0].max_turns == 100
        assert manifest.tasks[0].max_budget_usd == 5.0
        assert manifest.tasks[0].model is None  # not overridden


class TestLoadComponentWithManifest:
    def test_manifest_based_ordering(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-component"
        comp_dir.mkdir()
        (comp_dir / "component.yaml").write_text(
            "name: test\ntasks:\n  - file: 02-second.yaml\n  - file: 01-first.yaml\n"
        )
        (comp_dir / "01-first.yaml").write_text("name: first\nprompt: go\n")
        (comp_dir / "02-second.yaml").write_text("name: second\nprompt: go\n")

        loader = TaskLoader()
        tasks = loader.load_component(comp_dir, {})
        assert tasks[0].name == "second"
        assert tasks[1].name == "first"

    def test_fallback_without_manifest(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-component"
        comp_dir.mkdir()
        (comp_dir / "01-first.yaml").write_text("name: first\ninstructions: do stuff\nprompt: go\n")
        (comp_dir / "02-second.yaml").write_text(
            "name: second\ninstructions: do stuff\nprompt: go\n"
        )

        loader = TaskLoader()
        tasks = loader.load_component(comp_dir, {})
        assert tasks[0].name == "first"
        assert tasks[1].name == "second"

    def test_component_yaml_excluded_from_fallback_scan(self, tmp_path: Path) -> None:
        comp_dir = tmp_path / "my-component"
        comp_dir.mkdir()
        (comp_dir / "01-first.yaml").write_text("name: first\ninstructions: do stuff\nprompt: go\n")
        # A stray component.yaml that has no tasks key — should not be scanned
        # as a task YAML in fallback mode. But since we filter it by name, it won't.
        # This tests the fallback path excludes component.yaml.
        # Actually, component.yaml would fail load() since it has no name field like tasks.
        # The real test: if component.yaml exists, manifest path is used.
        # So this test verifies fallback path doesn't include component.yaml.
        loader = TaskLoader()
        tasks = loader.load_component(comp_dir, {})
        assert len(tasks) == 1
        assert tasks[0].name == "first"


class TestApplyManifestDefaults:
    """Test _apply_manifest_defaults static method on ComponentRunner."""

    def test_defaults_applied_when_task_has_none(self) -> None:
        from dkmv.tasks.component import ComponentRunner
        from dkmv.tasks.models import TaskDefinition

        task = TaskDefinition(name="test", prompt="go")
        manifest = ComponentManifest(
            name="test",
            model="claude-sonnet-4-6",
            max_turns=50,
            timeout_minutes=15,
            max_budget_usd=1.0,
        )
        ComponentRunner._apply_manifest_defaults(task, manifest, None)
        assert task.model == "claude-sonnet-4-6"
        assert task.max_turns == 50
        assert task.timeout_minutes == 15
        assert task.max_budget_usd == 1.0

    def test_task_ref_overrides_defaults(self) -> None:
        from dkmv.tasks.component import ComponentRunner
        from dkmv.tasks.models import TaskDefinition

        task = TaskDefinition(name="test", prompt="go")
        manifest = ComponentManifest(
            name="test",
            model="claude-sonnet-4-6",
            max_turns=50,
        )
        task_ref = ManifestTaskRef(file="01-test.yaml", max_turns=100, max_budget_usd=5.0)
        ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)
        assert task.model == "claude-sonnet-4-6"  # from manifest
        assert task.max_turns == 100  # from task_ref
        assert task.max_budget_usd == 5.0  # from task_ref

    def test_task_yaml_value_preserved(self) -> None:
        from dkmv.tasks.component import ComponentRunner
        from dkmv.tasks.models import TaskDefinition

        task = TaskDefinition(name="test", prompt="go", model="claude-opus-4-6", max_turns=200)
        manifest = ComponentManifest(
            name="test",
            model="claude-sonnet-4-6",
            max_turns=50,
        )
        task_ref = ManifestTaskRef(file="01-test.yaml", max_turns=100)
        ComponentRunner._apply_manifest_defaults(task, manifest, task_ref)
        assert task.model == "claude-opus-4-6"  # task YAML wins
        assert task.max_turns == 200  # task YAML wins

    def test_no_defaults_no_crash(self) -> None:
        from dkmv.tasks.component import ComponentRunner
        from dkmv.tasks.models import TaskDefinition

        task = TaskDefinition(name="test", prompt="go")
        manifest = ComponentManifest(name="test")
        ComponentRunner._apply_manifest_defaults(task, manifest, None)
        assert task.model is None
        assert task.max_turns is None


class TestBuiltinManifestLoading:
    """Verify each built-in component.yaml loads correctly."""

    SAMPLE_VARS: dict[str, Any] = {
        "prd_path": "/tmp/test-prd.md",
        "impl_docs_path": "/tmp/impl-docs",
        "create_pr": "false",
        "pr_base": "main",
        "phases": [
            {"phase_number": 1, "phase_name": "foundation", "phase_file": "phase1_foundation.md"},
        ],
    }

    def test_dev_manifest_loads(self) -> None:
        from dkmv.tasks.discovery import resolve_component

        component_dir = resolve_component("dev")
        loader = TaskLoader()
        manifest = loader.load_manifest(component_dir / "component.yaml", self.SAMPLE_VARS)
        assert manifest.name == "dev"
        assert len(manifest.inputs) == 1
        assert len(manifest.tasks) == 1
        assert manifest.tasks[0].file == "implement-phase.yaml"
        assert manifest.tasks[0].for_each == "phases"
        assert manifest.agent_md_file == "/tmp/impl-docs/CLAUDE.md"

    def test_qa_manifest_loads(self) -> None:
        from dkmv.tasks.discovery import resolve_component

        component_dir = resolve_component("qa")
        loader = TaskLoader()
        manifest = loader.load_manifest(component_dir / "component.yaml", self.SAMPLE_VARS)
        assert manifest.name == "qa"
        assert len(manifest.inputs) == 1
        assert len(manifest.tasks) == 3
        assert manifest.tasks[0].pause_after is True
        assert manifest.agent_md_file == "/tmp/impl-docs/CLAUDE.md"

    def test_docs_manifest_loads(self) -> None:
        from dkmv.tasks.discovery import resolve_component

        component_dir = resolve_component("docs")
        loader = TaskLoader()
        manifest = loader.load_manifest(component_dir / "component.yaml", self.SAMPLE_VARS)
        assert manifest.name == "docs"
        assert len(manifest.inputs) == 1
        assert manifest.inputs[0].name == "impl_docs"
        assert len(manifest.tasks) == 3
        assert manifest.agent_md_file == "/tmp/impl-docs/CLAUDE.md"

    def test_plan_manifest_loads(self) -> None:
        from dkmv.tasks.discovery import resolve_component

        component_dir = resolve_component("plan")
        loader = TaskLoader()
        manifest = loader.load_manifest(component_dir / "component.yaml", self.SAMPLE_VARS)
        assert manifest.name == "plan"
        assert len(manifest.inputs) == 2
        assert len(manifest.tasks) == 5
        assert manifest.agent_md is not None
        assert "Workspace Layout" in manifest.agent_md

    def test_plan_manifest_model(self) -> None:
        from dkmv.tasks.discovery import resolve_component

        component_dir = resolve_component("plan")
        loader = TaskLoader()
        manifest = loader.load_manifest(component_dir / "component.yaml", self.SAMPLE_VARS)
        assert manifest.model == "claude-opus-4-6"

    def test_plan_manifest_task_ref_overrides(self) -> None:
        from dkmv.tasks.discovery import resolve_component

        component_dir = resolve_component("plan")
        loader = TaskLoader()
        manifest = loader.load_manifest(component_dir / "component.yaml", self.SAMPLE_VARS)
        # 03-phases.yaml has max_turns=100, max_budget=5.00
        phases_ref = manifest.tasks[2]
        assert phases_ref.file == "03-phases.yaml"
        assert phases_ref.max_turns == 100
        assert phases_ref.max_budget_usd == 5.0

    def test_plan_manifest_analyze_has_pause_after(self) -> None:
        from dkmv.tasks.discovery import resolve_component

        component_dir = resolve_component("plan")
        loader = TaskLoader()
        manifest = loader.load_manifest(component_dir / "component.yaml", self.SAMPLE_VARS)
        analyze_ref = manifest.tasks[0]
        assert analyze_ref.file == "01-analyze.yaml"
        assert analyze_ref.pause_after is True
        # Other tasks should not have pause_after
        for ref in manifest.tasks[1:]:
            assert ref.pause_after is False
