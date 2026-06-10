"""connectors.toml yükleyici — sağlayıcı config deseninin aynısı (opt-in + auth_env)."""
from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

_CONFIG = Path(__file__).resolve().parent.parent / "connectors.toml"


def load() -> dict:
    """connectors.toml'u oku (yoksa boş). [connectors.x] veya [x] tablolarını kabul eder."""
    if _CONFIG.exists() and tomllib is not None:
        try:
            data = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))
            conns = data.get("connectors", data)
            return {k: v for k, v in conns.items() if isinstance(v, dict)}
        except Exception:
            return {}
    return {}


def enabled_connectors() -> list[str]:
    """Etkin + auth'u tamam connector adları (auth_env yoksa graceful atlanır)."""
    out = []
    for name, spec in load().items():
        if not spec.get("enabled"):
            continue
        auth_env = spec.get("auth_env")
        if auth_env and not os.getenv(auth_env):
            continue
        out.append(name)
    return out
