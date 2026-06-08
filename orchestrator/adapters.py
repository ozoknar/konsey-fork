"""Vendor-neutral AgentAdapter katmanı (Anayasa Madde 2.3).

Her düğüm yalnızca bir CLI'ya prompt verir, metin + exit code döndürür.
Sağlayıcı değişimi = burada bir adapter değişir, orkestrasyon mantığı değil.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass

HOME = os.path.expanduser("~")
_EXTRA_PATH = f"{HOME}/.local/bin:/opt/homebrew/bin:/usr/bin:/bin"


def _env() -> dict:
    # Çağrı anında oku (import-zamanı snapshot DEĞİL) — KONSEY_DISTILL gibi guard
    # env'leri alt sürece geçsin (recursion guard). PATH garanti altında.
    return {**os.environ, "PATH": f"{_EXTRA_PATH}:{os.environ.get('PATH', '')}"}


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
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        text = out if out else err
        ok = p.returncode == 0 and bool(out)
        code = p.returncode
    except subprocess.TimeoutExpired:
        text, ok, code = f"[TIMEOUT {timeout}s]", False, 124
    except FileNotFoundError:
        text, ok, code = f"[CLI bulunamadı: {cmd[0]}]", False, 127
    secs = round(time.time() - t0, 1)
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return AgentResult(agent, text, code, secs, ok, h)


class AgentAdapter:
    name = "base"
    provider = "base"

    def run(self, prompt: str, timeout: int = 180) -> AgentResult:  # pragma: no cover
        raise NotImplementedError


class ClaudeAdapter(AgentAdapter):
    name, provider = "claude", "anthropic"

    def run(self, prompt: str, timeout: int = 180) -> AgentResult:
        # Salt-metin reasoning; araç kullanımı istemiyoruz (headless determinism)
        prompt = "Answer directly in plain text. Do not use any tools.\n\n" + prompt
        return _run(self.name, ["claude", "-p", prompt], timeout)


class CodexAdapter(AgentAdapter):
    name, provider = "codex", "openai"

    def run(self, prompt: str, timeout: int = 240) -> AgentResult:
        return _run(self.name, ["codex", "exec", "--skip-git-repo-check", prompt], timeout)


class GoogleAdapter(AgentAdapter):
    name, provider = "google", "google"

    def run(self, prompt: str, timeout: int = 240) -> AgentResult:
        return _run(self.name, ["agy", "--print-timeout", f"{timeout - 10}s", "-p", prompt], timeout)


# Kayıt — orkestratör buradan seçer. agy yoksa GoogleAdapter çağrısı ok=False döner (graceful).
ADAPTERS: dict[str, AgentAdapter] = {
    "claude": ClaudeAdapter(),
    "codex": CodexAdapter(),
    "google": GoogleAdapter(),
}


def available() -> dict[str, bool]:
    """Hangi CLI'lar PATH'te? (En az 2 sağlayıcı şart — Madde 2.7)"""
    import shutil
    return {
        "claude": shutil.which("claude") is not None,
        "codex": shutil.which("codex") is not None,
        "google": shutil.which("agy") is not None,
    }
