"""Secret store backends — ``keychain`` | ``secret-tool`` | ``wincred`` | ``envfile`` | ``NullStore`` (default).

Selected by ``Config.secret_backend``. The core never persists or prints secret
material (Article 2 / Constitution: "no secret in cleartext to env/log/prompt").
Every backend reads on demand from the OS keystore; nothing is cached in memory
longer than the call, and no value is ever logged.

The default ``NullStore`` returns ``None`` for everything — the orchestrator then
relies on the ambient environment / provider CLIs' own auth, exactly as today.
"""
from __future__ import annotations

import os
import stat
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path


class SecretStore(ABC):
    """One secret backend. ``get`` returns the secret string or ``None``; never raises."""

    name = "base"

    @abstractmethod
    def get(self, key: str) -> str | None:  # pragma: no cover - interface
        raise NotImplementedError


class NullStore(SecretStore):
    """Default: no managed secret store. The orchestrator uses ambient auth."""

    name = "null"

    def get(self, key: str) -> str | None:
        return None


class KeychainStore(SecretStore):
    """macOS Keychain (``security find-generic-password``). The service namespace
    is fixed to ``council`` so entries are self-contained and discoverable."""

    name = "keychain"
    _SERVICE = "council"

    def get(self, key: str) -> str | None:
        try:
            p = subprocess.run(
                ["security", "find-generic-password", "-s", self._SERVICE, "-a", key, "-w"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return None
        if p.returncode != 0:
            return None
        val = (p.stdout or "").strip()
        return val or None


class SecretToolStore(SecretStore):
    """Linux libsecret (``secret-tool lookup``). Same fixed namespace attribute."""

    name = "secret-tool"
    _SERVICE = "council"

    def get(self, key: str) -> str | None:
        try:
            p = subprocess.run(
                ["secret-tool", "lookup", "service", self._SERVICE, "account", key],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return None
        if p.returncode != 0:
            return None
        # secret-tool emits the secret without a trailing newline; do not strip inner whitespace.
        val = (p.stdout or "").rstrip("\n")
        return val or None


class WinCredStore(SecretStore):
    """Windows Credential Manager via PowerShell (best-effort). Returns ``None`` when
    the CredentialManager module is unavailable rather than raising."""

    name = "wincred"
    _TARGET_PREFIX = "council:"

    def get(self, key: str) -> str | None:
        import shutil
        if shutil.which("powershell") is None:
            return None
        target = self._TARGET_PREFIX + key
        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "if (Get-Module -ListAvailable -Name CredentialManager) { "
                 f"(Get-StoredCredential -Target '{target}').GetNetworkCredential().Password }}"],
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            return None
        if p.returncode != 0:
            return None
        val = (p.stdout or "").strip()
        return val or None


class EnvFileStore(SecretStore):
    """0600 ``KEY=value`` file fallback for hosts without an OS keystore.

    The file path comes from ``$COUNCIL_SECRETS_FILE`` or ``~/.config/council/secrets.env``.
    A world/group-readable file is refused (returns ``None``) — secrets must not sit
    in a loosely-permissioned file. Values are never logged."""

    name = "envfile"

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        env = path or os.environ.get("KONSEY_SECRETS_FILE") or os.environ.get("COUNCIL_SECRETS_FILE")
        self._path = Path(env).expanduser() if env else (
            Path.home() / ".config" / "council" / "secrets.env"
        )

    def _readable_secure(self) -> bool:
        try:
            mode = self._path.stat().st_mode
        except OSError:
            return False
        # refuse if group/other have any permission bit set (must be 0600 or stricter)
        return not (mode & (stat.S_IRWXG | stat.S_IRWXO))

    def get(self, key: str) -> str | None:
        if not self._path.exists() or not self._readable_secure():
            return None
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip().strip('"').strip("'") or None
        except OSError:
            return None
        return None


_BACKENDS: dict[str, type[SecretStore]] = {
    "null": NullStore,
    "keychain": KeychainStore,
    "secret-tool": SecretToolStore,
    "wincred": WinCredStore,
    "envfile": EnvFileStore,
}


def get_secret_store(name: str | None) -> SecretStore:
    """Resolve a secret backend by name; unknown / None → ``NullStore``."""
    return _BACKENDS.get((name or "null").strip().lower(), NullStore)()
