"""i18n catalog loader (single format: JSON catalogs in council/locales/).

TODO Phase 2: load ``locales/{locale}.json``, fall back to ``en``, expose ``t(key)``.
The default locale comes from ``Config.locale`` ("en").
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config

_DEFAULT_LOCALE = "en"


def load_catalog(cfg: Config) -> dict[str, str]:
    """Load the JSON catalog for cfg.locale, falling back to en. Missing → empty dict."""
    locales = cfg.locales_dir()
    for loc in (cfg.locale, _DEFAULT_LOCALE):
        path = locales / f"{loc}.json"
        if path.exists():
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
    return {}
