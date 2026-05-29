"""Scheduler backends — ``launchd`` | ``systemd`` | ``schtasks`` | ``cron`` | ``NullScheduler`` (default).

Selected by ``Config.scheduler``. Background automation is opt-in and **default OFF**
(Article 0.7 / 14): the default ``NullScheduler`` installs nothing, so a fresh
install never registers a launch agent, timer, scheduled task, or crontab entry.

These backends only *describe / register* a periodic ``council dispatch tick``.
They deliberately do not run anything themselves and require an explicit, consented
``install()`` call (``council enable capture`` / ``council init`` opt-in step).
``uninstall()`` makes the whole thing reversible (Article 12 — reversibility).

Article 15.3 contract:
  * **single tick-contract** — every backend schedules the same command
    (``_TICK_ARGS``); no backend invents its own entrypoint.
  * **label/path from the profile** — the scheduler ``label`` and working dir come
    from ``Config`` (``scheduler_label`` / ``council_home``), never a hard-coded
    institution tag. The portable default label is generic (``council-tick``).
  * **idempotent** — ``register`` re-writes its own unit/task/line in place; running
    it twice leaves exactly one entry.
  * **reversible** — ``unregister`` removes exactly what this backend created and
    nothing else.

Each backend separates *rendering* (pure, side-effect-free string/argv builders that
are unit-testable WITHOUT a live daemon) from *registration* (the ``subprocess``
calls that touch ``systemctl`` / ``schtasks``). The render methods are what the
tests assert against; ``register``/``unregister`` wrap them with the OS calls.
"""
from __future__ import annotations

import os
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

# How often the tick fires when a real backend is installed (seconds). Conservative;
# the tick itself is cheap and single-instance-locked (dispatch.tick flock).
DEFAULT_INTERVAL_S = 300

# The command a backend schedules. Resolved at install time; never hard-codes a path.
# This is THE single tick-contract (Art. 15.3): launchd/systemd/schtasks/cron all
# schedule exactly this argv after the python interpreter.
_TICK_ARGS = ["-m", "council.dispatch", "tick"]

# Portable, institution-neutral default label. Used when no profile label is given.
# Contains no org/machine name (Art. 15.3 — sabit kurum-etiketi yasak).
DEFAULT_LABEL = "council-tick"

# A scheduler label has to be a safe filesystem / unit / task-name token. We accept a
# conservative charset and fall back to the portable default on anything unexpected so a
# profile string can never inject shell/path separators into a unit file or task name.
_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_label(label: str | None) -> str:
    """Coerce a profile-supplied label into a safe scheduler token.

    Strips anything outside ``[A-Za-z0-9._-]`` (path separators, spaces, shell
    metacharacters) and falls back to :data:`DEFAULT_LABEL` if nothing safe remains.
    Keeps the label portable and injection-free (Art. 15.1/15.3)."""
    raw = (label or "").strip()
    cleaned = _LABEL_RE.sub("", raw).strip("._-")
    return cleaned or DEFAULT_LABEL


def label_from_config(cfg: object | None) -> str:
    """Resolve the scheduler label from a profile (``Config``) without importing it.

    Reads an optional ``scheduler_label`` attribute; absent/empty → portable default.
    Decoupled via ``getattr`` so the platform layer never hard-depends on ``config``."""
    return sanitize_label(getattr(cfg, "scheduler_label", None) if cfg is not None else None)


def _home_from_config(cfg: object | None) -> Path | None:
    home = getattr(cfg, "council_home", None) if cfg is not None else None
    return Path(home) if home else None


class Scheduler(ABC):
    """One OS scheduler backend. ``install`` registers a periodic tick; ``uninstall``
    removes it. Backends are best-effort and report success/failure, never raise.

    ``label`` (from the profile) names the unit/task/agent so two installs of the same
    backend with the same label are idempotent and an uninstall removes exactly its own."""

    name = "base"

    def __init__(self, label: str | None = None) -> None:
        self.label = sanitize_label(label)

    @abstractmethod
    def install(self, *, python: str | None = None, council_home: Path | None = None,
                interval_s: int = DEFAULT_INTERVAL_S) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    # ``register`` is the Art. 15.3 verb; ``install`` is kept as the historical alias.
    def register(self, *, python: str | None = None, council_home: Path | None = None,
                 interval_s: int = DEFAULT_INTERVAL_S) -> bool:
        return self.install(python=python, council_home=council_home, interval_s=interval_s)

    @abstractmethod
    def uninstall(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def unregister(self) -> bool:
        return self.uninstall()

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


def _resolve_cwd(council_home: Path | None) -> str:
    return str(Path(council_home).resolve()) if council_home else os.getcwd()


class LaunchdScheduler(Scheduler):
    """macOS launchd user agent (``~/Library/LaunchAgents/<label>.plist``).

    Most battle-tested backend. Writes a StartInterval agent that runs the tick.
    The label defaults to ``com.<label>`` so it reads as a reverse-DNS launchd label."""

    name = "launchd"

    @property
    def _LABEL(self) -> str:  # noqa: N802 - kept for backward-compat with callers/tests
        return f"com.{self.label}"

    def _plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self._LABEL}.plist"

    def render_plist(self, *, python: str | None = None, council_home: Path | None = None,
                     interval_s: int = DEFAULT_INTERVAL_S) -> str:
        """Pure: the plist XML this backend would write. Unit-testable without launchd."""
        py = _resolve_python(python)
        cwd = _resolve_cwd(council_home)
        args = "".join(f"\n        <string>{a}</string>" for a in [py, *_TICK_ARGS])
        return (
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

    def install(self, *, python=None, council_home=None, interval_s=DEFAULT_INTERVAL_S) -> bool:
        plist = self.render_plist(python=python, council_home=council_home, interval_s=interval_s)
        path = self._plist_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(plist, encoding="utf-8")  # idempotent: overwrites in place
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
    """Linux systemd user timer (``~/.config/systemd/user/<label>.{service,timer}``).

    Generates a ``oneshot`` service running the single tick-contract and a timer that
    re-arms every ``interval_s``. The unit basename is the profile label."""

    name = "systemd"

    @property
    def _UNIT(self) -> str:  # noqa: N802 - kept for backward-compat with callers/tests
        return self.label

    def _dir(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user"

    def service_path(self) -> Path:
        return self._dir() / f"{self._UNIT}.service"

    def timer_path(self) -> Path:
        return self._dir() / f"{self._UNIT}.timer"

    def render_service(self, *, python: str | None = None, council_home: Path | None = None) -> str:
        """Pure: the ``.service`` unit text. Unit-testable without systemd."""
        py = _resolve_python(python)
        cwd = _resolve_cwd(council_home)
        return (
            "[Unit]\nDescription=Council dispatch tick\n\n"
            "[Service]\nType=oneshot\n"
            f"WorkingDirectory={cwd}\n"
            f"ExecStart={py} {' '.join(_TICK_ARGS)}\n"
        )

    def render_timer(self, *, interval_s: int = DEFAULT_INTERVAL_S) -> str:
        """Pure: the ``.timer`` unit text. Unit-testable without systemd."""
        secs = max(1, int(interval_s))
        return (
            "[Unit]\nDescription=Council dispatch tick timer\n\n"
            f"[Timer]\nOnBootSec={secs}\nOnUnitActiveSec={secs}\n"
            "Persistent=false\n\n[Install]\nWantedBy=timers.target\n"
        )

    def install(self, *, python=None, council_home=None, interval_s=DEFAULT_INTERVAL_S) -> bool:
        d = self._dir()
        service = self.render_service(python=python, council_home=council_home)
        timer = self.render_timer(interval_s=interval_s)
        try:
            d.mkdir(parents=True, exist_ok=True)
            # Idempotent: writing the same basenames overwrites the previous units.
            self.service_path().write_text(service, encoding="utf-8")
            self.timer_path().write_text(timer, encoding="utf-8")
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=15)
            r = subprocess.run(["systemctl", "--user", "enable", "--now", f"{self._UNIT}.timer"],
                               capture_output=True, timeout=15)
            return r.returncode == 0
        except Exception:
            return False

    def uninstall(self) -> bool:
        try:
            subprocess.run(["systemctl", "--user", "disable", "--now", f"{self._UNIT}.timer"],
                           capture_output=True, timeout=15)
            self.service_path().unlink(missing_ok=True)
            self.timer_path().unlink(missing_ok=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=15)
            return True
        except Exception:
            return False

    def is_installed(self) -> bool:
        return self.timer_path().exists()


class SchtasksScheduler(Scheduler):
    """Windows Task Scheduler (``schtasks``). Registers a per-minute-multiple task.

    The task name is the profile label (with ``/`` -> backslash forbidden by the
    sanitizer). ``/F`` makes ``register`` idempotent (force-overwrites an existing task)."""

    name = "schtasks"

    @property
    def _TASK(self) -> str:  # noqa: N802 - kept for backward-compat with callers/tests
        return self.label

    def render_command(self, *, python: str | None = None) -> str:
        """Pure: the ``/TR`` command string (python + single tick-contract)."""
        py = _resolve_python(python)
        return f'"{py}" {" ".join(_TICK_ARGS)}'

    def render_create_argv(self, *, python: str | None = None,
                           interval_s: int = DEFAULT_INTERVAL_S) -> list[str]:
        """Pure: the full ``schtasks /Create`` argv. Unit-testable without Windows.

        ``/F`` forces overwrite → idempotent register; ``/SC MINUTE /MO <n>`` re-fires
        every ``n`` minutes (>=1)."""
        minutes = max(1, int(interval_s) // 60)
        return [
            "schtasks", "/Create", "/F",
            "/SC", "MINUTE", "/MO", str(minutes),
            "/TN", self._TASK,
            "/TR", self.render_command(python=python),
        ]

    def render_delete_argv(self) -> list[str]:
        """Pure: the ``schtasks /Delete`` argv that reverses exactly this task."""
        return ["schtasks", "/Delete", "/F", "/TN", self._TASK]

    def render_query_argv(self) -> list[str]:
        """Pure: the ``schtasks /Query`` argv used by ``is_installed``."""
        return ["schtasks", "/Query", "/TN", self._TASK]

    def install(self, *, python=None, council_home=None, interval_s=DEFAULT_INTERVAL_S) -> bool:
        try:
            r = subprocess.run(
                self.render_create_argv(python=python, interval_s=interval_s),
                capture_output=True, timeout=20,
            )
            return r.returncode == 0
        except Exception:
            return False

    def uninstall(self) -> bool:
        try:
            subprocess.run(self.render_delete_argv(), capture_output=True, timeout=20)
            return True
        except Exception:
            return False

    def is_installed(self) -> bool:
        try:
            r = subprocess.run(self.render_query_argv(), capture_output=True, timeout=20)
            return r.returncode == 0
        except Exception:
            return False


class CronScheduler(Scheduler):
    """POSIX crontab fallback. Appends a single guarded line (tagged with a marker
    comment) so ``uninstall`` can remove exactly its own entry, leaving the rest intact."""

    name = "cron"

    @property
    def _MARKER(self) -> str:  # noqa: N802 - kept for backward-compat with callers/tests
        return f"# {self.label} (managed; do not edit)"

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

    def render_line(self, *, python: str | None = None, council_home: Path | None = None,
                    interval_s: int = DEFAULT_INTERVAL_S) -> str:
        """Pure: the single guarded crontab line. Unit-testable without a crontab."""
        py = _resolve_python(python)
        cwd = _resolve_cwd(council_home)
        minutes = max(1, int(interval_s) // 60)
        return f"*/{minutes} * * * * cd {cwd} && {py} {' '.join(_TICK_ARGS)}  {self._MARKER}"

    def install(self, *, python=None, council_home=None, interval_s=DEFAULT_INTERVAL_S) -> bool:
        line = self.render_line(python=python, council_home=council_home, interval_s=interval_s)
        # Idempotent: drop any prior managed line before re-adding exactly one.
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


def get_scheduler(name: str | None, *, label: str | None = None, cfg: object | None = None) -> Scheduler:
    """Resolve a scheduler backend by name; unknown / None → ``NullScheduler`` (no automation).

    The label comes from the profile (Art. 15.3): an explicit ``label`` wins, else
    ``cfg.scheduler_label``, else the portable :data:`DEFAULT_LABEL`. ``NullScheduler``
    ignores the label (it schedules nothing)."""
    backend = _BACKENDS.get((name or "null").strip().lower(), NullScheduler)
    resolved_label = label if label is not None else label_from_config(cfg)
    return backend(label=resolved_label)
