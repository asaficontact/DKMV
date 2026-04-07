"""Artifact access for run outputs."""

from __future__ import annotations

import json
import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class ArtifactRef(BaseModel):
    """Reference to a file artifact from a run."""

    artifact_id: str = ""
    run_id: str
    filename: str
    path: Path
    size_bytes: int
    artifact_type: str  # "config", "result", "stream", "prompt", "instructions", "output", "log"
    task_name: str = ""
    created_at: datetime = datetime.min
    content_type: str = ""
    original_path: str = ""
    step_instance: str = ""


_TYPE_MAP: dict[str, str] = {
    "config.json": "config",
    "result.json": "result",
    "stream.jsonl": "stream",
    "container.txt": "config",
    "prompts_log.md": "log",
    "tasks_result.json": "result",
}


def _classify(filename: str) -> str:
    """Classify a file by name pattern."""
    if filename in _TYPE_MAP:
        return _TYPE_MAP[filename]
    if filename.startswith("prompt_"):
        return "prompt"
    if filename.startswith("claude_md_") or filename.endswith("_instructions.md"):
        return "instructions"
    if filename.endswith(".log"):
        return "log"
    return "output"


def _extract_task_name(filename: str) -> str:
    """Extract task name from artifact filename if possible."""
    if filename.startswith("prompt_") and filename.endswith(".md"):
        return filename[len("prompt_") : -len(".md")]
    if filename.startswith("claude_md_") and filename.endswith(".md"):
        return filename[len("claude_md_") : -len(".md")]
    return ""


def _guess_content_type(filename: str) -> str:
    """Guess MIME content type from filename."""
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        return mime
    if filename.endswith(".jsonl"):
        return "application/x-jsonlines"
    return "application/octet-stream"


def _build_ref(run_id: str, filename: str, p: Path) -> ArtifactRef:
    """Build an ArtifactRef from a file path."""
    stat = p.stat()
    return ArtifactRef(
        artifact_id=f"{run_id}/{filename}",
        run_id=run_id,
        filename=filename,
        path=p,
        size_bytes=stat.st_size,
        artifact_type=_classify(filename),
        task_name=_extract_task_name(filename),
        created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        content_type=_guess_content_type(filename),
    )


def _read_meta(meta_path: Path) -> dict[str, str]:
    """Read a .meta.json sidecar file, returning an empty dict on failure."""
    try:
        data = json.loads(meta_path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _build_task_ref(run_id: str, task_name: str, filename: str, p: Path) -> ArtifactRef:
    """Build an ArtifactRef for a task-scoped artifact."""
    stat = p.stat()
    rel_filename = f"tasks/{task_name}/{filename}"
    meta_path = p.parent / f"{filename}.meta.json"
    meta = _read_meta(meta_path) if meta_path.exists() else {}
    return ArtifactRef(
        artifact_id=f"{run_id}/{rel_filename}",
        run_id=run_id,
        filename=rel_filename,
        path=p,
        size_bytes=stat.st_size,
        artifact_type="output",
        task_name=meta.get("task_name", task_name),
        created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        content_type=_guess_content_type(filename),
        original_path=meta.get("original_path", ""),
        step_instance=task_name,
    )


def list_artifacts(run_id: str, output_dir: Path) -> list[ArtifactRef]:
    """List all artifacts for a run.

    Args:
        run_id: The run to list artifacts for.
        output_dir: Base output directory containing runs/.

    Returns:
        List of ArtifactRef objects, sorted by filename.
    """
    run_dir = output_dir / "runs" / run_id
    if not run_dir.exists():
        return []

    artifacts: list[ArtifactRef] = []
    for p in sorted(run_dir.iterdir()):
        if p.is_file():
            artifacts.append(_build_ref(run_id, p.name, p))
    # Also scan logs/ subdirectory
    logs_dir = run_dir / "logs"
    if logs_dir.is_dir():
        for p in sorted(logs_dir.iterdir()):
            if p.is_file():
                artifacts.append(_build_ref(run_id, f"logs/{p.name}", p))

    # Scan tasks/ subdirectories for task-scoped artifacts
    tasks_dir = run_dir / "tasks"
    if tasks_dir.is_dir():
        for task_dir in sorted(tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            for p in sorted(task_dir.iterdir()):
                if p.is_file() and not p.name.endswith(".meta.json"):
                    artifacts.append(_build_task_ref(run_id, task_dir.name, p.name, p))

    return artifacts


def get_artifact(run_id: str, filename: str, output_dir: Path) -> str:
    """Read the content of an artifact file.

    Args:
        run_id: The run containing the artifact.
        filename: The artifact filename (may include subdirectory like
                  "logs/foo.log" or "tasks/step-1/plan.json").
        output_dir: Base output directory containing runs/.

    Returns:
        File content as a string.

    Raises:
        FileNotFoundError: If the artifact file does not exist.
    """
    path = output_dir / "runs" / run_id / filename
    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {path}")
    return path.read_text()
