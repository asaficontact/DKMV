from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from syrupy.assertion import SnapshotAssertion

from dkmv.components.dev import DevComponent, DevConfig
from dkmv.components.docs import DocsComponent, DocsConfig
from dkmv.components.judge import JudgeComponent, JudgeConfig
from dkmv.components.qa import QAComponent, QAConfig
from dkmv.config import DKMVConfig
from dkmv.core.runner import RunManager
from dkmv.core.stream import StreamParser


@pytest.fixture
def global_config() -> DKMVConfig:
    return DKMVConfig.model_construct(
        anthropic_api_key="sk-ant-test",
        github_token="ghp_test",
        default_model="claude-sonnet-4-6",
        default_max_turns=10,
        image_name="dkmv-sandbox:latest",
        output_dir=Path("./outputs"),
        timeout_minutes=5,
        memory_limit="4g",
    )


@pytest.fixture
def run_manager(tmp_path: Path) -> RunManager:
    return RunManager(output_dir=tmp_path)


@pytest.fixture
def stream_parser() -> StreamParser:
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    return StreamParser(console=console)


@pytest.fixture
def prd_file(tmp_path: Path) -> Path:
    prd = tmp_path / "prd.md"
    prd.write_text("## Requirements\nBuild feature X\n")
    return prd


@pytest.fixture
def feedback_file(tmp_path: Path) -> Path:
    fb = tmp_path / "feedback.json"
    fb.write_text('{"items": []}')
    return fb


@pytest.fixture
def design_docs_dir(tmp_path: Path) -> Path:
    docs = tmp_path / "design_docs"
    docs.mkdir()
    (docs / "arch.md").write_text("Architecture doc")
    return docs


# --- Dev Prompt Snapshots ---


class TestDevPromptSnapshot:
    def test_basic_prompt(
        self,
        snapshot: SnapshotAssertion,
        global_config: DKMVConfig,
        run_manager: RunManager,
        stream_parser: StreamParser,
        prd_file: Path,
    ) -> None:
        component = DevComponent(
            global_config=global_config,
            sandbox=None,  # type: ignore[arg-type]
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert prompt == snapshot

    def test_prompt_with_feedback(
        self,
        snapshot: SnapshotAssertion,
        global_config: DKMVConfig,
        run_manager: RunManager,
        stream_parser: StreamParser,
        prd_file: Path,
        feedback_file: Path,
    ) -> None:
        component = DevComponent(
            global_config=global_config,
            sandbox=None,  # type: ignore[arg-type]
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            feedback_path=feedback_file,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert prompt == snapshot

    def test_prompt_with_design_docs(
        self,
        snapshot: SnapshotAssertion,
        global_config: DKMVConfig,
        run_manager: RunManager,
        stream_parser: StreamParser,
        prd_file: Path,
        design_docs_dir: Path,
    ) -> None:
        component = DevComponent(
            global_config=global_config,
            sandbox=None,  # type: ignore[arg-type]
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            design_docs_path=design_docs_dir,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert prompt == snapshot

    def test_prompt_with_both(
        self,
        snapshot: SnapshotAssertion,
        global_config: DKMVConfig,
        run_manager: RunManager,
        stream_parser: StreamParser,
        prd_file: Path,
        feedback_file: Path,
        design_docs_dir: Path,
    ) -> None:
        component = DevComponent(
            global_config=global_config,
            sandbox=None,  # type: ignore[arg-type]
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = DevConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            feedback_path=feedback_file,
            design_docs_path=design_docs_dir,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert prompt == snapshot


# --- QA Prompt Snapshots ---


class TestQAPromptSnapshot:
    def test_basic_prompt(
        self,
        snapshot: SnapshotAssertion,
        global_config: DKMVConfig,
        run_manager: RunManager,
        stream_parser: StreamParser,
        prd_file: Path,
    ) -> None:
        component = QAComponent(
            global_config=global_config,
            sandbox=None,  # type: ignore[arg-type]
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = QAConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert prompt == snapshot


# --- Judge Prompt Snapshots ---


class TestJudgePromptSnapshot:
    def test_basic_prompt(
        self,
        snapshot: SnapshotAssertion,
        global_config: DKMVConfig,
        run_manager: RunManager,
        stream_parser: StreamParser,
        prd_file: Path,
    ) -> None:
        component = JudgeComponent(
            global_config=global_config,
            sandbox=None,  # type: ignore[arg-type]
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = JudgeConfig(
            repo="https://github.com/test/repo.git",
            prd_path=prd_file,
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert prompt == snapshot


# --- Docs Prompt Snapshots ---


class TestDocsPromptSnapshot:
    def test_basic_prompt(
        self,
        snapshot: SnapshotAssertion,
        global_config: DKMVConfig,
        run_manager: RunManager,
        stream_parser: StreamParser,
    ) -> None:
        component = DocsComponent(
            global_config=global_config,
            sandbox=None,  # type: ignore[arg-type]
            run_manager=run_manager,
            stream_parser=stream_parser,
        )
        config = DocsConfig(
            repo="https://github.com/test/repo.git",
            branch="feature/test",
            timeout_minutes=5,
        )
        prompt = component.build_prompt(config)
        assert prompt == snapshot
