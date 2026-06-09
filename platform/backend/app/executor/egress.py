"""Network-enforced egress allowlist for the sandbox (INV-3 / §8.6 / NFR-SEC-1).

The sandbox's network is restricted to an allowlist (GitHub API/git + the
configured model API endpoints) **enforced at the network layer** — a firewall /
filtering proxy with DNS pinned to a trusted resolver — **not** via the agent's
own config. Honor-system allowlists have shipped ``endsWith`` / SOCKS5 / DNS
bypasses, so the agent must not be able to opt out: this is the *primary* control
that blunts exfiltration of the agent's own live credentials once a prompt
injection lands (PRD §8.6, R-3/R-14).

This module owns the allowlist **policy** and turns it into the host-side network
artifacts the executor applies when it starts a sandbox:

* :meth:`EgressPolicy.is_allowed` — the network-layer decision a filtering proxy
  enforces (host must match an allowlisted host or a permitted suffix; everything
  else is DENIED by default — default-on).
* :meth:`EgressPolicy.docker_network_args` — the Docker run args that attach the
  sandbox to an **internal**, egress-restricted network (it joins the allowlist
  proxy network and is denied the default bridge), so the container cannot route
  to an arbitrary host even if the agent reconfigures itself.
* :meth:`EgressPolicy.pinned_dns_args` — pin the container's resolver to the
  trusted DNS so a poisoned/agent-chosen resolver cannot bypass the host filter.

The decision is **default-deny**: an empty or unmatched host is blocked.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.security.audit import AuditLog

logger = logging.getLogger(__name__)

#: The trusted resolver the sandbox DNS is pinned to (Cloudflare; §8.6 "DNS
#: pinned to a trusted resolver"). Overridable per policy.
DEFAULT_PINNED_DNS = "1.1.1.1"

#: The internal Docker network the egress-filtering proxy lives on. The sandbox
#: joins ONLY this network (no default bridge), so all egress is funneled through
#: the allowlist proxy — the network-layer enforcement point.
EGRESS_NETWORK_NAME = "dkmv-egress"


def _normalize_host(host: str) -> str:
    """Lowercase + strip a host; drop any scheme/port/path noise a caller passes."""
    h = host.strip().lower()
    # Strip scheme.
    if "://" in h:
        h = h.split("://", 1)[1]
    # Strip path / query.
    h = h.split("/", 1)[0]
    # Strip port.
    if ":" in h:
        h = h.split(":", 1)[0]
    return h.strip(".")


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    """The default-on egress allowlist applied at the network layer (INV-3).

    Args:
        hosts: The exact allowlisted hosts (GitHub + model APIs). A query host is
            allowed iff it equals one of these OR is a subdomain of one of them
            (so ``codeload.github.com`` matches an allowlisted ``github.com``),
            but **never** by a permissive ``endsWith`` over an attacker-chosen
            string — matching is on DNS label boundaries only.
        pinned_dns: The trusted resolver the container DNS is pinned to.
    """

    hosts: tuple[str, ...]
    pinned_dns: str = DEFAULT_PINNED_DNS
    _normalized: frozenset[str] = field(init=False, repr=False, compare=False, default=frozenset())

    def __post_init__(self) -> None:
        normalized = frozenset(_normalize_host(h) for h in self.hosts if _normalize_host(h))
        # ``frozen=True`` blocks normal assignment; use object.__setattr__ for the
        # derived cache (standard frozen-dataclass pattern).
        object.__setattr__(self, "_normalized", normalized)

    @classmethod
    def from_settings(cls, settings: object) -> EgressPolicy:
        """Build the policy from ``settings.egress_hosts`` (the §8.8 allowlist)."""
        hosts = getattr(settings, "egress_hosts", None)
        if not hosts:
            # Default-on: even a misconfigured/empty allowlist must not become
            # allow-all. Fall back to the GitHub + model-API defaults.
            hosts = ["api.github.com", "github.com", "api.anthropic.com", "api.openai.com"]
        return cls(hosts=tuple(hosts))

    def is_allowed(self, host: str) -> bool:
        """Network-layer decision: is ``host`` reachable from the sandbox?

        Default-**deny**: an empty/unmatched host is blocked. A host matches iff
        it equals an allowlisted host or is a DNS-label-boundary subdomain of one
        (``a.github.com`` matches ``github.com``; ``evilgithub.com`` does NOT).
        """
        candidate = _normalize_host(host)
        if not candidate:
            return False
        for allowed in self._normalized:
            if candidate == allowed or candidate.endswith("." + allowed):
                return True
        return False

    def denied(self, hosts: Iterable[str]) -> list[str]:
        """Return the subset of ``hosts`` the allowlist blocks (for audit/logging)."""
        return [h for h in hosts if not self.is_allowed(h)]

    def docker_network_args(self, network_name: str = EGRESS_NETWORK_NAME) -> list[str]:
        """Docker run args that confine the sandbox to the egress-filtered network.

        The container joins ONLY the internal allowlist-proxy network — it is not
        attached to the default bridge — so every outbound connection is forced
        through the network-layer filter. This is what makes the allowlist
        *enforced* rather than honor-system (§8.6).
        """
        return [f"--network={network_name}"]

    def pinned_dns_args(self) -> list[str]:
        """Docker run args pinning the container resolver to the trusted DNS.

        Prevents a poisoned or agent-reconfigured resolver from resolving a
        non-allowlisted host past the host filter (§8.6: "DNS pinned to a trusted
        resolver").
        """
        return [f"--dns={self.pinned_dns}"]

    def docker_egress_args(self, network_name: str = EGRESS_NETWORK_NAME) -> list[str]:
        """All egress-enforcement Docker args (network confinement + pinned DNS)."""
        return [*self.docker_network_args(network_name), *self.pinned_dns_args()]


def proxy_acl_lines(policy: EgressPolicy) -> Sequence[str]:
    """Render the allowlist as filtering-proxy ACL lines (one ``ALLOW`` per host).

    The host-side egress proxy (e.g. a tinyproxy/squid sidecar on the
    ``dkmv-egress`` network) consumes these so the *enforcement* lives at the
    network layer. Everything not listed is denied by the proxy's default-deny.
    This keeps the allowlist single-sourced from :class:`EgressPolicy`.
    """
    return [f"Allow {host}" for host in sorted(policy._normalized)]


def audit_egress_denials(
    policy: EgressPolicy,
    hosts: Iterable[str],
    *,
    audit: AuditLog | None,
    run_id: str | None = None,
) -> list[str]:
    """Record each allowlist-denied host to the §8.6 audit trail; return the denied set.

    The seam the executor / the AT-Isolation release test (5.4) uses to turn the
    network-layer denial decision (:meth:`EgressPolicy.denied`) into a durable
    **audit** evidence line (AC-12 / INV-3): "the denial is logged + surfaced to the
    audit log". Each blocked host is recorded as an ``egress_denial`` kind (host name
    only — never a credential). ``audit=None`` is a graceful no-op (the denial still
    happens at the network layer; only its audit line is skipped). Returns the denied
    hosts so the caller can also log/raise as it already does.

    PRODUCTION-WIRING NOTE (slice 5.3 / FIX-2): a *live* egress denial is observable
    only at the **network/container layer** — the ``dkmv-egress`` internal network +
    the filtering-proxy sidecar enforce the allowlist (see
    :meth:`EgressPolicy.docker_egress_args` / :func:`proxy_acl_lines`); there is no
    in-process Python call site where a real outbound denial *surfaces* (Python only
    renders the proxy ACL). So this helper is intentionally left **ready but not
    production-wired here** — the production wiring (reading the proxy's deny log /
    the e2e exfil-attempt assertion) lands in **5.4's AT-Isolation** release test,
    which has the running container + proxy to observe a real denial. It is NOT faked
    from a Python decision: a synthetic ``is_allowed``-based call would record an
    audit line for a denial that never actually happened at the network layer.
    """
    denied = policy.denied(hosts)
    if audit is not None:
        for host in denied:
            audit.record_egress_denial(host=host, run_id=run_id)
    return denied
