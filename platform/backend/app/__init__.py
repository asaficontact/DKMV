"""DKMV Platform backend (FastAPI control plane).

A self-hostable web control plane that turns GitHub Issues into autonomous
DKMV coding-agent runs. It wraps the locked ``dkmv`` engine via
``dkmv.runtime.EmbeddedRuntime`` in-process — never by shelling the CLI
(INV-13).
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
