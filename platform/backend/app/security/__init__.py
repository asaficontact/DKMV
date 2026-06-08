"""App access control (loopback + token + Host/Origin + CSRF — INV-1).

The control plane reaches a root-equivalent Docker socket and launches
money-spending runs, so the API is gated by :class:`AccessControlMiddleware`
(PRD NFR-SEC-2). Import it from here.
"""

from __future__ import annotations

from app.security.access_control import AccessControlMiddleware

__all__ = ["AccessControlMiddleware"]
