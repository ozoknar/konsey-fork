"""i18n catalog loader — JSON catalogs in ``council/locales/``.

``en.json`` is the **canonical** catalog: it holds every translatable string in the
core (state prompts, advisory notice, …). Other locales (``tr.json``) are full mirrors.

``load_catalog`` always starts from the canonical English baseline and overlays the
requested locale on top, so a key missing from the requested locale **falls back to
English per-key** — never a blank or a KeyError. The default locale comes from
``Config.locale`` ("en").

Accepts either a :class:`~council.config.Config` (the orchestrator passes ``cfg``) or a
bare locale string, keeping ``i18n`` usable without a full config (e.g. tooling/tests).
No machine-specific paths: the bundled catalog dir is resolved relative to this module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Union

from .config import Config

_DEFAULT_LOCALE = "en"
# Bundled catalogs ship next to this module → portable, no ${HOME}/machine paths.
_BUNDLED_LOCALES_DIR = Path(__file__).resolve().parent / "locales"


def _read(path: Path) -> dict[str, str]:
    """Read one JSON catalog. Missing/invalid → empty dict (never raises)."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def canonical_catalog(locales_dir: Path | None = None) -> dict[str, str]:
    """The canonical English catalog — the per-key fallback contract."""
    return _read((locales_dir or _BUNDLED_LOCALES_DIR) / f"{_DEFAULT_LOCALE}.json")


def load_catalog(cfg_or_locale: Union[Config, str, None] = None) -> dict[str, str]:
    """Return the catalog for the requested locale, with English per-key fallback.

    ``cfg_or_locale`` may be a :class:`Config` (locale + bundled dir taken from it),
    a bare locale string (uses the bundled catalog dir), or ``None`` (English only).
    The result is ``canonical_en`` overlaid with the requested locale, so any key the
    locale omits resolves to its English value.
    """
    if isinstance(cfg_or_locale, Config):
        locale = cfg_or_locale.locale
        locales_dir = cfg_or_locale.locales_dir()
    else:
        locale = cfg_or_locale or _DEFAULT_LOCALE
        locales_dir = _BUNDLED_LOCALES_DIR

    catalog = canonical_catalog(locales_dir)
    if locale != _DEFAULT_LOCALE:
        catalog.update(_read(locales_dir / f"{locale}.json"))
    return catalog


def t(catalog: Mapping[str, str] | None, key: str) -> str:
    """Resolve ``key`` from ``catalog`` then the canonical English baseline.

    Always returns a string: a key absent from both yields the key itself (a loud,
    debuggable marker — better than an empty string or KeyError in a degraded path).
    """
    if catalog is not None and key in catalog:
        return catalog[key]
    return canonical_catalog().get(key, key)
