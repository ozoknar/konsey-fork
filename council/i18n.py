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

    ``cfg_or_locale`` may be a :class:`Config` (locale + an operator override dir taken
    from it), a bare locale string (bundled catalogs only), or ``None`` (English only).

    Resolution is a layered overlay, lowest → highest priority:

      1. bundled canonical English (``en.json`` shipped with the package) — the baseline;
      2. bundled locale (the shipped ``tr.json`` etc.) — so a translation that ships with
         the package is always available, regardless of where ``council_home`` points;
      3. operator override dir (``cfg.locales_dir()``): its ``en.json`` then its
         ``<locale>.json`` — lets a deployment patch or add strings without editing core.

    A key absent from a higher layer falls through to the layer below (per-key English
    fallback at the bottom). The bundled package locales are resolved relative to this
    module, so nothing here depends on a machine-specific path.
    """
    override_dir: Path | None = None
    if isinstance(cfg_or_locale, Config):
        locale = cfg_or_locale.locale
        override_dir = cfg_or_locale.locales_dir()
    else:
        locale = cfg_or_locale or _DEFAULT_LOCALE

    catalog = canonical_catalog(_BUNDLED_LOCALES_DIR)              # 1: bundled English baseline
    if locale != _DEFAULT_LOCALE:
        catalog.update(_read(_BUNDLED_LOCALES_DIR / f"{locale}.json"))  # 2: bundled locale
    if override_dir is not None and override_dir != _BUNDLED_LOCALES_DIR:
        catalog.update(_read(override_dir / f"{_DEFAULT_LOCALE}.json"))  # 3a: operator English
        if locale != _DEFAULT_LOCALE:
            catalog.update(_read(override_dir / f"{locale}.json"))      # 3b: operator locale
    return catalog


def t(catalog: Mapping[str, str] | None, key: str, /, **slots: object) -> str:
    """Resolve ``key`` from ``catalog`` then the canonical English baseline.

    Always returns a string: a key absent from both yields the key itself (a loud,
    debuggable marker — better than an empty string or KeyError in a degraded path).

    When ``**slots`` are supplied the resolved value is treated as a ``str.format``
    template and filled (``{slot}`` placeholders). With NO slots the value is returned
    verbatim — so a message containing literal ``{}`` is never accidentally formatted,
    and the no-slot byte-for-byte behaviour is preserved (the default-locale contract).
    A missing slot raises ``KeyError`` loudly: a template and its caller must agree.
    """
    if catalog is not None and key in catalog:
        value = catalog[key]
    else:
        value = canonical_catalog().get(key, key)
    return value.format(**slots) if slots else value
