"""Run launch + run read-model package (Phase 2, slice 2.1).

Owns the launch contract (:mod:`app.runs.launch` — §8.10 validation, ``auto →
workflow.agent`` resolution, the INV-5 claim-lock, and the
``EmbeddedRuntime.start`` bridge) and the run read model (:mod:`app.runs.service`
— the §8.9 ``GET /runs`` / ``GET /runs/{id}`` baseline shapes). The HTTP routes
live in :mod:`app.api.runs`; nothing here reaches into ``dkmv/`` except through
the in-process :class:`~app.runtime.RunService` seam (INV-13).
"""

from __future__ import annotations
