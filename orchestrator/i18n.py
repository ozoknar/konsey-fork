"""Hafif i18n — locale'e göre İngilizce/Türkçe. Varsayılan İngilizce; sistem dili `tr` ise Türkçe.

Davranış (kullanıcı isteği): Türkiye'den (locale tr) bağlanan Türkçe, başka dil İngilizce görür.
`KONSEY_LANG=tr|en` ile zorlanabilir. Yalnız kullanıcı-görünür CLI yüzeyleri için.
"""
from __future__ import annotations

import locale
import os

MESSAGES: dict[str, dict[str, str]] = {
    "doctor.title":     {"en": "Konsey Doctor - setup status", "tr": "Konsey Doctor — kurulum durumu"},
    "doctor.security":  {"en": "Security level : {level}",      "tr": "Güvenlik seviyesi : {level}"},
    "doctor.telemetry": {"en": "Telemetry      : {state}",      "tr": "Telemetri      : {state}"},
    "doctor.tel_on":    {"en": "ON (opt-in)",                   "tr": "AÇIK (opt-in)"},
    "doctor.tel_off":   {"en": "off",                           "tr": "kapalı"},
    "doctor.providers": {"en": "Providers (the AI products you use):",
                         "tr": "Sağlayıcılar (kullandığınız YZ ürünleri):"},
    "doctor.disabled":  {"en": "- disabled",                    "tr": "— devre dışı"},
    "doctor.no_cli":    {"en": "x no CLI ({cmd})",              "tr": "✗ CLI yok ({cmd})"},
    "doctor.no_auth":   {"en": "x missing auth ({env})",        "tr": "✗ auth eksik ({env})"},
    "doctor.ready":     {"en": "ready",                         "tr": "hazır"},
    "doctor.none":      {"en": "No provider ready - install an AI CLI (claude/codex/agy) "
                               "or edit konsey.providers.toml.",
                         "tr": "Hiç sağlayıcı hazır değil — bir YZ CLI kurun (claude/codex/agy) "
                               "veya konsey.providers.toml düzenleyin."},
    "doctor.solo":      {"en": "Solo mode (1 provider ready). 2+ recommended for cross-validation.",
                         "tr": "Solo mod (1 sağlayıcı hazır). Çapraz-doğrulama için 2+ önerilir."},
    "doctor.multi":     {"en": "{n} providers ready - full cross-validation possible.",
                         "tr": "{n} sağlayıcı hazır — tam çapraz-doğrulama mümkün."},
}


def current_lang() -> str:
    """tr | en. KONSEY_LANG > LC_ALL > LC_MESSAGES > LANG > sistem locale; tr ile başlarsa tr."""
    raw = (os.getenv("KONSEY_LANG") or os.getenv("LC_ALL") or os.getenv("LC_MESSAGES")
           or os.getenv("LANG") or "")
    if not raw:
        try:
            raw = locale.getlocale()[0] or ""
        except Exception:  # noqa: BLE001
            raw = ""
    return "tr" if raw.lower().startswith("tr") else "en"


def t(key: str, **kw) -> str:
    entry = MESSAGES.get(key, {})
    msg = entry.get(current_lang()) or entry.get("en") or key
    return msg.format(**kw) if kw else msg
