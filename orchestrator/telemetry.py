"""Opt-in anonim telemetri — yalnız metadata, ASLA görev içeriği/PHI/secret.

Etkin olması için kullanıcı AÇIK RIZA vermeli: ``KONSEY_TELEMETRY=on`` (kurulumda sorulur).
Kapalıysa (varsayılan) hiçbir şey gönderilmez. Best-effort: ana akışı asla bloklamaz.

Toplanan : olay tipi, komut, süre, hata kodu, sürüm, OS/python, anonim kurulum ID,
           güvenlik seviyesi, risk sınıfı, sağlayıcı sayısı.
Toplanmayan: görev metni, model çıktısı, dosya/yol, PII, secret, kişisel kimlik.

Tasarım kuralı: yalnız `_ALLOWED` alanları gider; string alanlar kısaltılır ve gateway
secret-tarayıcısı son güvenlik ağı olarak çalışır (eşleşirse alan `[redacted]` olur).
"""
from __future__ import annotations

import json
import os
import platform
import urllib.request
import uuid
from pathlib import Path

from .gateway import scan_secrets

VERSION = "0.1.0"
# Varsayılan ingest uçnoktası (opt-in ise buraya gider). Kendi backend'iniz için override edin.
DEFAULT_ENDPOINT = "https://telemetry.emediquality.com/v1/events"
_ROOT = Path(__file__).resolve().parent.parent
_ID_FILE = _ROOT / ".konsey_id"

# Gönderilebilecek TEK alanlar (allowlist). Başka anahtar sessizce atılır.
_ALLOWED = {"event", "command", "duration_ms", "exit_code", "error_type",
            "risk_class", "providers_count", "security_level", "status"}


def enabled() -> bool:
    """Yalnız kullanıcı açıkça rıza verdiyse True (varsayılan kapalı)."""
    return os.getenv("KONSEY_TELEMETRY", "off").lower() in ("on", "1", "true", "yes")


def _install_id() -> str:
    """Anonim, rastgele kurulum kimliği (kişi/cihaz tanımlamaz). Bir kez üretilir."""
    if _ID_FILE.exists():
        return _ID_FILE.read_text(encoding="utf-8").strip()
    iid = str(uuid.uuid4())
    try:
        _ID_FILE.write_text(iid, encoding="utf-8")
    except OSError:
        pass
    return iid


def _safe(value):
    """String'leri kısalt + secret içeriyorsa düşür (redaksiyon güvenlik ağı)."""
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    s = str(value)
    if scan_secrets(s):
        return "[redacted]"
    return s[:64]


def emit(event: str, **fields) -> None:
    """Anonim metadata olayı gönder. Rıza yoksa veya endpoint yoksa no-op.
    Hata daima yutulur — telemetri ana akışı ASLA bozmaz."""
    if not enabled():
        return
    endpoint = os.getenv("KONSEY_TELEMETRY_ENDPOINT", DEFAULT_ENDPOINT).strip()
    if not endpoint:
        return
    payload = {
        "event": str(event)[:48],
        "install_id": _install_id(),
        "konsey_version": VERSION,
        "os": platform.system(),
        "py": platform.python_version(),
    }
    for k, v in fields.items():
        if k in _ALLOWED:
            payload[k] = _safe(v)
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).close()
    except Exception:
        pass  # best-effort
