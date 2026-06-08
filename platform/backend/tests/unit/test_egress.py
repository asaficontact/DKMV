"""Egress allowlist policy (INV-3 / AC-0.5-1)."""

from __future__ import annotations

from app.executor.egress import (
    EGRESS_NETWORK_NAME,
    EgressPolicy,
    proxy_acl_lines,
)


def _policy() -> EgressPolicy:
    return EgressPolicy(hosts=("api.github.com", "github.com", "api.anthropic.com"))


def test_allowlisted_host_is_allowed() -> None:
    policy = _policy()
    assert policy.is_allowed("api.github.com")
    assert policy.is_allowed("api.anthropic.com")


def test_subdomain_of_allowlisted_host_is_allowed() -> None:
    policy = _policy()
    # DNS-label-boundary subdomain match (codeload.github.com under github.com).
    assert policy.is_allowed("codeload.github.com")


def test_non_allowlisted_host_is_blocked() -> None:
    policy = _policy()
    assert not policy.is_allowed("evil.example.com")
    assert not policy.is_allowed("attacker.net")


def test_lookalike_suffix_is_not_a_bypass() -> None:
    policy = _policy()
    # A naive endsWith allowlist would wrongly allow this — the label-boundary
    # match must NOT (this is the §8.6 "endsWith bypass" the PRD calls out).
    assert not policy.is_allowed("evilgithub.com")
    assert not policy.is_allowed("github.com.attacker.net")


def test_default_deny_on_empty_host() -> None:
    policy = _policy()
    assert not policy.is_allowed("")
    assert not policy.is_allowed("   ")


def test_from_settings_empty_allowlist_falls_back_not_allow_all() -> None:
    class _Settings:
        egress_hosts: list[str] = []

    policy = EgressPolicy.from_settings(_Settings())
    # Default-on: an empty allowlist must NOT become allow-all.
    assert not policy.is_allowed("evil.example.com")
    assert policy.is_allowed("api.github.com")


def test_docker_egress_args_confine_network_and_pin_dns() -> None:
    policy = _policy()
    args = policy.docker_egress_args()
    assert f"--network={EGRESS_NETWORK_NAME}" in args
    assert any(a.startswith("--dns=") for a in args)


def test_denied_lists_blocked_hosts() -> None:
    policy = _policy()
    blocked = policy.denied(["api.github.com", "evil.example.com", "api.anthropic.com"])
    assert blocked == ["evil.example.com"]


def test_proxy_acl_lines_single_source_from_policy() -> None:
    policy = _policy()
    lines = proxy_acl_lines(policy)
    assert "Allow github.com" in lines
    assert all(line.startswith("Allow ") for line in lines)
