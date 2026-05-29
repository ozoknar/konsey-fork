"""Scheduler backends — ``launchd`` | ``systemd`` | ``schtasks`` | ``cron`` | ``NullScheduler`` (default).

Selected by ``Config.scheduler``. Background automation is opt-in and **default OFF**
(Article 0.7 / 14): the default ``NullScheduler`` installs nothing, so a fresh
install never registers a launch agent, timer, scheduled task, or crontab entry.

These backends only *describe / register* a periodic ``council dispatch tick``.
They deliberately do not run anything themselves and require an explicit, consented
``install()`` call (``council enable capture`` / ``council init`` opt-in step).
``uninstall()`` makes the whole thing reversible (Article 12 — reversibility).
"""
from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

# How often the tick fires when a real backend is installed (seconds). Conservative;
# the tick itself is cheap and single-instance-locked (dispatch.tick flock).
DEFAULT_INTERVAL_S = 300

# The command a backend schedules. Resolved at install time; never hard-codes a path.
_TICK_ARGS = ["-m", "council.dispatch", "tick"]


class Scheduler(ABC):
    """One OS scheduler backend. ``install`` registers a periodic tick; ``uninstall``
    removes it. Backends are best-effort and report success/failure, never raise."""

    name = "base"

    @abstractmethod
    def install(self, *, python: str | None = None, council_home: Path | None = None,
                interval_s: int = DEFAULT_INTERVAL_S) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    @abstractmethod
    def uninstall(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def is_installed(self) -> bool:  # pragma: no cover - default
        return False


class NullScheduler(Scheduler):
    """Default: no background service. The core runs fully on-demand without any timer."""

    name = "null"

    def install(self, *, python=None, council_home=None, interval_s=DEFAULT_INTERVAL_S) -> bool:
        # Intentional no-op: opt-in automation is OFF by default (Article 0.7 / 14).
        return False

    def uninstall(self) -> bool:
        return True

    def is_installed(self) -> bool:
        return False


def _resolve_python(python: str | None) -> str:
    import sys
    return python or sys.executable or "python3"


class LaunchdScheduler(Scheduler):
    """macOS launchd user agent (``~/Library/LaunchAgents/com.council.tick.plist``).

    Most battle-tested backend. Writes a StartInterval agent that runs the tick."""

    name = "launchd"
    _LABEL = "com.council.tick"

    def _plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self._LABEL}.plist"

    def install(self, *, python=None, council_home=None, interval_s=DEFAULT_INTERVAL_S) -> bool:
        py = _resolve_python(python)
        cwd = str(Path(council_home).resolve()) if council_home else os.getcwd()
        args = "".join(f"\n        <string>{a}</string>" for a in [py, *_TICK_ARGS])
        plist = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            f'    <key>Label</key><string>{self._LABEL}</string>\n'
            f'    <key>ProgramArguments</key><array>{args}\n    </array>\n'
            f'    <key>WorkingDirectory</key><string>{cwd}</string>\n'
            f'    <key>StartInterval</key><integer>{int(interval_s)}</integer>\n'
            '    <key>RunAtLoad</key><false/>\n'
            '</dict></plist>\n'
        )
        path = self._plist_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(plist, encoding="utf-8")
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True, timeout=15)
            r = subprocess.run(["launchctl", "load", str(path)], capture_output=True, timeout=15)
            return r.returncode == 0
        except Exception:
            return False

    def uninstall(self) -> bool:
        path = self._plist_path()
        try:
            if path.exists():
                subprocess.run(["launchctl", "unload", str(path)], capture_output=True, timeout=15)
                path.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def is_installed(self) -> bool:
        return self._plist_path().exists()


class SystemdScheduler(Scheduler):
    """Linux systemd user timer (``~/.config/systemd/user/council-tick.{service,timer}``)."""

    name = "systemd"
    _UNIT = "council-tick"

    def _dir(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user"

    def install(self, *, python=None, council_home=None, interval_s=DEFAULT_INTERVAL_S) -> bool:
        py = _resolve_python(python)
        cwd = str(Path(council_home).resolve()) if council_home else os.getcwd()
        d = self._dir()
        service = (
            "[Unit]\nDescription=Council dispatch tick\n\n"
            "[Service]\nType=oneshot\n"
            f"WorkingDirectory={cwd}\n"
            f"ExecStart={py} {' '.join(_TICK_ARGS)}\n"
        )
        timer = (
            "[Unit]\nDescription=Council dispatch tick timer\n\n"
            f"[Timer]\nOnBootSec={int(interval_s)}\nOnUnitActiveSec={int(interval_s)}\n"
            "Persistent=false\n\n[Install]\nWantedBy=timers.target\n"
        )
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{self._UNIT}.service").write_text(service, encoding="utf-8")
            (d / f"{self._UNIT}.timer").write_text(timer, encoding="utf-8")
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=15)
            r = subprocess.run(["systemctl", "--user", "enable", "--now", f"{self._UNIT}.timer"],
                               capture_output=True, timeout=15)
            return r.returncode == 0
        except Exception:
            return False

    def uninstall(self) -> bool:
        d = self._dir()
        try:
            subprocess.run(["systemctl", "--user", "disable", "--now", f"{self._UNIT}.timer"],
                           capture_output=True, timeout=15)
            for suffix in ("service", "timer"):
                (d / f"{self._UNIT}.{suffix}").unlink(missing_ok=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=15)
            return True
        except Exception:
            return False

    def is_installed(self) -> bool:
        return (self._dir() / f"{self._UNIT}.timer").exists()


class SchtasksScheduler(Scheduler):
    """Windows Task Scheduler (``schtasks``). Registers a per-minute-multiple task."""

    name = "schtasks"
    _TASK = "CouncilTick"

    def install(self, *, python=None, council_home=None, interval_s=DEFAULT_INTERVAL_S) -> bool:
        py = _resolve_python(python)
        minutes = max(1, int(interval_s) // 60)
        cmd = f'"{py}" {" ".join(_TICK_ARGS)}'
        try:
            r = subprocess.run(
                ["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(minutes),
                 "/TN", self._TASK, "/TR", cmd],
                capture_output=True, timeout=20,
            )
            return r.returncode == 0
        except Exception:
            return False

    def uninstall(self) -> bool:
        try:
            subprocess.run(["schtasks", "/Delete", "/F", "/TN", self._TASK],
                           capture_output=True, timeout=20)
            return True
        except Exception:
            return False


class CronScheduler(Scheduler):
    """POSIX crontab fallback. Appends a single guarded line (tagged with a marker
    comment) so ``uninstall`` can remove exactly its own entry, leaving the rest intact."""

    name = "cron"
    _MARKER = "# council-tick (managed; do not edit)"

    def _current(self) -> list[str]:
        try:
            p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15)
        except Exception:
            return []
        if p.returncode != 0:
            return []
        return (p.stdout or "").splitlines()

    def _write(self, lines: list[str]) -> bool:
        try:
            p = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n",
                               capture_output=True, text=True, timeout=15)
            return p.returncode == 0
        except Exception:
            return False

    def install(self, *, python=None, council_home=None, interval_s=DEFAULT_INTERVAL_S) -> bool:
        py = _resolve_python(python)
        cwd = str(Path(council_home).resolve()) if council_home else os.getcwd()
        minutes = max(1, int(interval_s) // 60)
        line = f"*/{minutes} * * * * cd {cwd} && {py} {' '.join(_TICK_ARGS)}  {self._MARKER}"
        lines = [ln for ln in self._current() if self._MARKER not in ln]
        lines.append(line)
        return self._write(lines)

    def uninstall(self) -> bool:
        lines = [ln for ln in self._current() if self._MARKER not in ln]
        return self._write(lines)

    def is_installed(self) -> bool:
        return any(self._MARKER in ln for ln in self._current())


_BACKENDS: dict[str, type[Scheduler]] = {
    "null": NullScheduler,
    "launchd": LaunchdScheduler,
    "systemd": SystemdScheduler,
    "schtasks": SchtasksScheduler,
    "cron": CronScheduler,
}


def get_scheduler(name: str | None) -> Scheduler:
    """Resolve a scheduler backend by name; unknown / None → ``NullScheduler`` (no automation)."""
    return _BACKENDS.get((name or "null").strip().lower(), NullScheduler)()
