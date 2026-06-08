"""Security-baseline test suite (slice 0.5; PRD §13 security profile).

Run with ``pytest -q -k security_baseline``: egress denial, no-secret-in-events,
Host/Origin/CSRF rejection (403) + missing-token (401), GitHub token repo-scope,
and the brokered-socket guard (the backend has no direct ``docker.sock``).
"""
