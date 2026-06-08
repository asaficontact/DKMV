"""Encrypted SecretStore round-trip + file-mount injection (INV-4 / AC-0.5-2)."""

from __future__ import annotations

import stat
from datetime import timedelta
from pathlib import Path

import pytest
from app.secrets.store import SecretStore, SecretStoreError


def _store() -> SecretStore:
    return SecretStore(key=SecretStore.generate_key())


def test_encrypt_decrypt_round_trip() -> None:
    store = _store()
    plaintext = "sk-ant-super-secret-value"
    ciphertext = store.encrypt(plaintext)
    # Ciphertext must NOT contain the plaintext (encrypt-at-rest).
    assert plaintext not in ciphertext
    assert store.decrypt(ciphertext) == plaintext


def test_wrong_key_cannot_decrypt() -> None:
    a = _store()
    b = _store()
    ciphertext = a.encrypt("secret")
    with pytest.raises(SecretStoreError):
        b.decrypt(ciphertext)


def test_tampered_ciphertext_rejected() -> None:
    store = _store()
    ciphertext = store.encrypt("secret")
    tampered = ciphertext[:-2] + ("AA" if not ciphertext.endswith("AA") else "BB")
    with pytest.raises(SecretStoreError):
        store.decrypt(tampered)


def test_missing_key_raises() -> None:
    with pytest.raises(SecretStoreError):
        SecretStore(key="")


async def test_inmemory_put_get_round_trip() -> None:
    store = _store()
    await store.put("api_key", "value-123")
    assert await store.get("api_key") == "value-123"
    assert await store.get("nope") is None


async def test_inmemory_ttl_is_persisted_but_expiry_enforced_by_db_path() -> None:
    # The in-memory path does not enforce TTL (the DB path does, via expires_at).
    store = _store()
    await store.put("k", "v", ttl=timedelta(hours=1))
    assert await store.get("k") == "v"


def test_write_mount_is_file_not_env(tmp_path: Path) -> None:
    store = _store()
    mounted = store.write_mount("github_token", "ghp-secret", mount_dir=tmp_path)
    # The secret is written to a FILE (not an env var) — §8.6 file-mount injection.
    assert mounted.host_path.exists()
    assert mounted.host_path.read_text() == "ghp-secret"
    # Container target is a file path under /run/secrets, and the docker arg is a
    # read-only bind MOUNT (never an `-e`/`--env`).
    assert mounted.container_path == "/run/secrets/github_token"
    arg = mounted.docker_mount_arg()
    assert "type=bind" in arg and "readonly" in arg
    assert "--env" not in arg and "-e " not in arg


def test_mounted_secret_file_is_0600(tmp_path: Path) -> None:
    store = _store()
    mounted = store.write_mount("k", "v", mount_dir=tmp_path)
    mode = stat.S_IMODE(mounted.host_path.stat().st_mode)
    assert mode == 0o600


def test_write_mounts_multiple(tmp_path: Path) -> None:
    store = _store()
    mounts = store.write_mounts(
        {"github_token": "g", "anthropic_key": "a"},
        mount_dir=tmp_path,
    )
    assert {m.name for m in mounts} == {"github_token", "anthropic_key"}
    for m in mounts:
        assert m.host_path.read_text() in {"g", "a"}
