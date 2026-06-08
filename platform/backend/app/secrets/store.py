"""Encrypted ``SecretStore`` + file-mount injection (INV-4 / §8.6).

Secrets are **encrypted at rest** (Fernet / AES-128-CBC + HMAC, authenticated)
so the ciphertext in the ``secrets`` table (or on disk) is useless without the
host key, and are injected into a sandbox via a **file mount, never an env var**
(PRD §8.6: "Prefer file mounts over env vars — keeps secrets out of
``docker inspect`` / crash logs"). File-mount injection is *log-hygiene*, not
containment (the agent shares the container) — it is combined with the egress
allowlist + repo-scoped token, which are the actual exfiltration controls.

The store is deliberately backend-agnostic: it persists ciphertext through the
:class:`~app.db.repository.Repository` (the ``secrets`` table) so the
SQLite→Postgres seam holds. A symmetric key is loaded from
``DKMV_SECRET_KEY`` (a Fernet urlsafe-base64 key); in real deployments this comes
from the OS keychain / a sealed secret, not plain env (§8.6). For dev/tests a
key can be generated with :meth:`SecretStore.generate_key`.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.repository import Repository

#: Env var holding the host symmetric key (urlsafe-base64 Fernet key). In prod
#: this is sourced from the OS keychain / sealed secret, not plain env (§8.6).
SECRET_KEY_ENV = "DKMV_SECRET_KEY"

#: Default TTL for the GitHub run token — ≤1 hr (INV-4 / NFR-SEC-1).
GITHUB_TOKEN_TTL = timedelta(hours=1)

#: Restrictive mode for a file-mounted secret (owner read/write only).
_SECRET_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0o600


class SecretStoreError(RuntimeError):
    """Raised on a missing key, undecryptable ciphertext, or a missing secret."""


@dataclass(frozen=True, slots=True)
class MountedSecret:
    """A secret materialized to a file for sandbox **file-mount** injection.

    ``host_path`` is the 0600 file written on the host; ``container_path`` is the
    intended in-container mount target. The executor turns this into a Docker
    ``--mount`` (or volume) — secrets are injected via this file mount, **not**
    as an environment variable (§8.6).
    """

    name: str
    host_path: Path
    container_path: str

    def docker_mount_arg(self) -> str:
        """The read-only Docker bind-mount flag for this file-mounted secret."""
        return f"--mount=type=bind,source={self.host_path},target={self.container_path},readonly"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SecretStore:
    """Encrypt-at-rest secret storage + file-mount injection (INV-4).

    Args:
        repository: The DB seam used to persist ciphertext to the ``secrets``
            table. Optional — an in-memory store (no persistence) is used when
            ``None`` (handy for the pure encrypt/decrypt round-trip test).
        key: The Fernet key (urlsafe-base64 bytes/str). Defaults to the
            ``DKMV_SECRET_KEY`` env var; raises if neither is provided.
    """

    def __init__(
        self,
        repository: Repository | None = None,
        *,
        key: bytes | str | None = None,
    ) -> None:
        raw_key = key if key is not None else os.environ.get(SECRET_KEY_ENV)
        if not raw_key:
            raise SecretStoreError(
                f"no encryption key: pass key= or set {SECRET_KEY_ENV} "
                "(generate one with SecretStore.generate_key())"
            )
        try:
            self._fernet = Fernet(raw_key if isinstance(raw_key, bytes) else raw_key.encode())
        except (ValueError, TypeError) as exc:
            raise SecretStoreError("invalid encryption key (must be a Fernet urlsafe key)") from exc
        self._repository = repository
        # In-memory ciphertext cache when no repository is wired (tests / dev).
        self._mem: dict[str, str] = {}

    @staticmethod
    def generate_key() -> str:
        """Generate a fresh urlsafe-base64 Fernet key (host key bootstrap)."""
        return Fernet.generate_key().decode()

    # ── encrypt / decrypt (the at-rest boundary) ──────────────────────────────

    def encrypt(self, plaintext: str) -> str:
        """Return the authenticated ciphertext (urlsafe-base64 str) for ``plaintext``."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ``ciphertext`` back to plaintext; raises on tamper/wrong key."""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretStoreError(
                "ciphertext failed authentication (tampered or wrong key)"
            ) from exc

    # ── persisted store API (ciphertext only ever touches the DB) ─────────────

    async def put(self, key: str, value: str, *, ttl: timedelta | None = None) -> None:
        """Encrypt ``value`` and persist its ciphertext under ``key``.

        Only ciphertext is written to the ``secrets`` table — the plaintext never
        leaves this process. ``ttl`` sets ``expires_at`` (e.g. the ≤1 hr GitHub
        token; INV-4).
        """
        ciphertext = self.encrypt(value)
        expires_at = (_utc_now() + ttl).isoformat() if ttl is not None else None
        if self._repository is not None:
            await self._repository.put_secret(key, ciphertext, expires_at=expires_at)
        else:
            self._mem[key] = ciphertext

    async def get(self, key: str) -> str | None:
        """Decrypt and return the secret under ``key``, or ``None`` if absent/expired."""
        if self._repository is not None:
            row = await self._repository.get_secret(key)
            if row is None:
                return None
            ciphertext, expires_at = row
            if expires_at is not None and _is_expired(expires_at):
                return None
        else:
            ciphertext = self._mem.get(key, "")
            if not ciphertext:
                return None
        return self.decrypt(ciphertext)

    # ── file-mount injection (NOT env vars — §8.6) ────────────────────────────

    def write_mount(
        self,
        name: str,
        value: str,
        *,
        mount_dir: Path,
        container_dir: str = "/run/secrets",
    ) -> MountedSecret:
        """Materialize ``value`` to a 0600 file under ``mount_dir`` for injection.

        Returns a :class:`MountedSecret` the executor binds into the sandbox as a
        **read-only file mount** — secrets are injected via file mount, never as
        an environment variable (keeps them out of ``docker inspect`` / crash
        logs, §8.6). The host file is created with owner-only ``0600`` perms.
        """
        mount_dir.mkdir(parents=True, exist_ok=True)
        host_path = mount_dir / name
        # Write with restrictive perms from the start (open with the mode, then
        # chmod to be sure on platforms that honor umask differently).
        fd = os.open(host_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _SECRET_FILE_MODE)
        try:
            os.write(fd, value.encode())
        finally:
            os.close(fd)
        os.chmod(host_path, _SECRET_FILE_MODE)
        return MountedSecret(
            name=name,
            host_path=host_path,
            container_path=f"{container_dir.rstrip('/')}/{name}",
        )

    def write_mounts(
        self,
        secrets: Mapping[str, str],
        *,
        mount_dir: Path,
        container_dir: str = "/run/secrets",
    ) -> list[MountedSecret]:
        """Write multiple secrets as file mounts (see :meth:`write_mount`)."""
        return [
            self.write_mount(name, value, mount_dir=mount_dir, container_dir=container_dir)
            for name, value in secrets.items()
        ]


def _is_expired(expires_at_iso: str) -> bool:
    """True if the ISO-8601 ``expires_at`` is in the past (UTC)."""
    try:
        expires = datetime.fromisoformat(expires_at_iso)
    except ValueError:  # pragma: no cover - malformed timestamps treated as expired
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= _utc_now()
