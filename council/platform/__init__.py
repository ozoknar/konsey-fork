"""OS abstraction layer — Null* fallbacks; core works without any of these.

Backends are selected by ``Config.notifier`` / ``Config.secret_backend`` /
``Config.scheduler`` and resolved through the ``get_*`` factories below. The
defaults (``null``) install nothing and emit nothing, so a fresh install has no
background services and no desktop integration until the operator opts in.
"""
from __future__ import annotations

from .notify import Notifier, NullNotifier, get_notifier
from .scheduler import DEFAULT_INTERVAL_S, NullScheduler, Scheduler, get_scheduler
from .secrets import NullStore, SecretStore, get_secret_store

__all__ = [
    "Notifier", "NullNotifier", "get_notifier",
    "SecretStore", "NullStore", "get_secret_store",
    "Scheduler", "NullScheduler", "get_scheduler", "DEFAULT_INTERVAL_S",
]
