"""RunService — thin in-process wrapper over EmbeddedRuntime (INV-13).

The backend reaches the locked DKMV engine only through :class:`RunService`,
which owns one configured ``EmbeddedRuntime`` built from a ``RuntimeConfig`` with
a platform-owned ``output_dir`` (PRD §6.2, §6.5 OQ-4). Import it from here.
"""

from __future__ import annotations

from app.runtime.run_service import RunService, build_runtime_config

__all__ = ["RunService", "build_runtime_config"]
