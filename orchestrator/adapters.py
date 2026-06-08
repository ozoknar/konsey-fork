"""Vendor-neutral AgentAdapter katmanı — YAPILANDIRILABİLİR sağlayıcılar.

Kullanıcı hangi YZ ürünlerini kullandığını `konsey.providers.toml` ile tanımlar
(yoksa yerleşik claude/codex/google varsayılanları). Her sağlayıcı yalnız bir CLI'a
prompt verir, metin + exit code döndürür. Sağlayıcı eklemek/değiştirmek = config
değişir, orkestrasyon mantığı değil.

Komut şablonunda yer tutucular: ``{prompt}`` ve ``{timeout}``.
Auth: çoğu CLI kendi OAuth/aboneliğiyle girer (auth_env gereksiz). API-key gereken
sağlayıcı için ``auth_env`` ver → o env yoksa sağlayıcı "kullanılamaz" sayılır.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

HOME = os.path.expanduser("~")
_EXTRA_PATH = f"{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = _ROOT / "konsey.providers.toml"

# Yerleşik varsayılanlar (config yoksa). role: architect|critic|researcher|juror
DEFAULT_PROVIDERS: dict[str, dict] = {
    "claude": {"enabled": True, "role": "architect", "provider": "anthropic",
               "command": ["claude", "-p", "{prompt}"],
               "prompt_prefix": "Answer directly in plain text. Do not use any tools.\n\n"},
    "codex":  {"enabled": True, "role": "critic", "provider": "openai",
               "command": ["codex", "exec", "--skip-git-repo-check", "{prompt}"]},
    "google": {"enabled": True, "role": "researcher", "provider": "google",
               "command": ["agy", "--print-timeout", "{timeout}s", "-p", "{prompt}"]},
}


def _env() -> dict:
    return {**os.environ, "PATH": f"{_EXTRA_PATH}:{os.environ.get('PATH', '')}"}


def load_providers() -> dict[str, dict]:
    """konsey.providers.toml'u oku (varsa), yoksa yerleşik varsayılanlar.
    TOML kökünde [providers.x] veya doğrudan [x] tablolarını kabul eder."""
    if _CONFIG.exists() and tomllib is not None:
        try:
            data = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))
            provs = data.get("providers", data)
            # Şekil doğrula: yalnız dict-değerli (tablo) sağlayıcılar; bozuksa defaults.
            clean = {k: v for k, v in provs.items() if isinstance(v, dict) and v.get("command")}
            return clean or DEFAULT_PROVIDERS
        except Exception:
            return DEFAULT_PROVIDERS
    return DEFAULT_PROVIDERS


@dataclass
class AgentResult:
    agent: str
    text: str
    exit_code: int
    seconds: float
    ok: bool
    evidence_hash: str


def _run(agent: str, cmd: list[str], timeout: int) -> AgentResult:
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_env())
        out, err = (p.stdout or "").strip(), (p.stderr or "").strip()
        text = out if out else err
        ok, code = (p.returncode == 0 and bool(out)), p.returncode
    except subprocess.TimeoutExpired:
        text, ok, code = f"[TIMEOUT {timeout}s]", False, 124
    except FileNotFoundError:
        text, ok, code = f"[CLI bulunamadı: {cmd[0]}]", False, 127
    secs = round(time.time() - t0, 1)
    return AgentResult(agent, text, code, secs, ok, hashlib.sha256(text.encode()).hexdigest()[:16])


class ConfigAdapter:
    """Config tablosundan komut şablonu çalıştıran genel adapter."""

    def __init__(self, name: str, spec: dict):
        self.name = name
        self.spec = spec
        self.provider = spec.get("provider", name)
        self.role = spec.get("role", "")

    def run(self, prompt: str, timeout: int = 180) -> AgentResult:
        full = self.spec.get("prompt_prefix", "") + prompt
        tmpl = self.spec.get("command") or []
        cmd = [part.replace("{prompt}", full).replace("{timeout}", str(max(timeout - 10, 30)))
               for part in tmpl]
        if not cmd:
            return AgentResult(self.name, "[komut tanımsız]", 2, 0.0, False, "")
        return _run(self.name, cmd, timeout)


def _adapters() -> dict[str, ConfigAdapter]:
    return {n: ConfigAdapter(n, s) for n, s in load_providers().items() if s.get("enabled", True)}


# Orkestratör buradan seçer (config-driven, import-zamanı).
ADAPTERS: dict[str, ConfigAdapter] = _adapters()


def available() -> dict[str, bool]:
    """Her etkin sağlayıcı çağrılabilir mi? CLI PATH'te + (gerekiyorsa) auth_env dolu mu."""
    out: dict[str, bool] = {}
    for name, spec in load_providers().items():
        if not spec.get("enabled", True):
            out[name] = False
            continue
        cmd = spec.get("command") or []
        ok = bool(cmd) and shutil.which(cmd[0]) is not None
        auth_env = spec.get("auth_env")
        if ok and auth_env:
            ok = bool(os.getenv(auth_env))
        out[name] = ok
    return out


def pick(role: str, avail: dict[str, bool] | None = None, exclude: tuple = ()) -> str | None:
    """Verilen role'e uygun, kullanılabilir ilk sağlayıcı (exclude hariç). Yoksa None."""
    avail = avail if avail is not None else available()
    provs = load_providers()
    for name, spec in provs.items():
        if spec.get("role") == role and avail.get(name) and name not in exclude:
            return name
    # rol bulunamadı → kullanılabilir herhangi biri (exclude hariç)
    for name in provs:
        if avail.get(name) and name not in exclude:
            return name
    return None
