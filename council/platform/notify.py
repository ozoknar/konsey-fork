"""Notifier backends — ``osascript`` | ``notify-send`` | ``win-toast`` | ``NullNotifier`` (default).

Selected by ``Config.notifier``. The core never depends on a desktop notification:
``NullNotifier`` is the default and a failure here never stops a workflow (Article 14).

Security note (carried from the legacy ``dispatch._notify`` F9 fix): every string
that reaches a shell-adjacent backend is escaped before interpolation. The
``osascript`` backend in particular builds an AppleScript literal, so quotes,
backslashes, newlines, ``$`` and backticks are stripped to prevent script injection.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from abc import ABC, abstractmethod

# F9: strip characters that could break out of an AppleScript / shell string literal.
_UNSAFE = re.compile(r'[\\"\n\r`$]')
_MAX_LEN = 120


def _safe(s: object) -> str:
    """Neutralise injection characters and bound the length (F9)."""
    return _UNSAFE.sub(" ", str(s))[:_MAX_LEN]


class Notifier(ABC):
    """One desktop-notification backend. Implementations must never raise."""

    name = "base"

    @abstractmethod
    def notify(self, title: str, body: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class NullNotifier(Notifier):
    """Default: no notification. Core works fully without any desktop integration."""

    name = "null"

    def notify(self, title: str, body: str) -> None:
        return None


class OsascriptNotifier(Notifier):
    """macOS ``osascript display notification``. Best-tested backend."""

    name = "osascript"

    def notify(self, title: str, body: str) -> None:
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{_safe(body)}" with title "Council" '
                 f'subtitle "{_safe(title)}"'],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass  # notification is optional; failure never stops the flow


class NotifySendNotifier(Notifier):
    """Linux ``notify-send`` (libnotify). Arguments are passed as argv, not a shell
    string, so escaping is bound-only; still trimmed for length."""

    name = "notify-send"

    def notify(self, title: str, body: str) -> None:
        try:
            subprocess.run(
                ["notify-send", _safe(f"Council — {title}"), _safe(body)],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass


class WinToastNotifier(Notifier):
    """Windows toast via PowerShell BurntToast if present, else a no-op.

    PowerShell is invoked with ``-Command`` so the same escaping discipline applies."""

    name = "win-toast"

    def notify(self, title: str, body: str) -> None:
        if shutil.which("powershell") is None:
            return
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "if (Get-Module -ListAvailable -Name BurntToast) { "
                 f'New-BurntToastNotification -Text "{_safe(f"Council — {title}")}", '
                 f'"{_safe(body)}" }}'],
                capture_output=True, timeout=15,
            )
        except Exception:
            pass


_BACKENDS: dict[str, type[Notifier]] = {
    "null": NullNotifier,
    "osascript": OsascriptNotifier,
    "notify-send": NotifySendNotifier,
    "win-toast": WinToastNotifier,
}


def get_notifier(name: str | None) -> Notifier:
    """Resolve a notifier backend by name; unknown / None → ``NullNotifier``."""
    return _BACKENDS.get((name or "null").strip().lower(), NullNotifier)()
