"""Connector ortak çekirdeği — gate + council köprüsü."""
from __future__ import annotations

ALLOWED_AUTO = {"public", "internal"}   # otomatik kanal tavanı (Md.13.7 ile hizalı)


def run_council(task: str, project_hint: str = "") -> str:
    """Görevi risk-gate'ten geçir; izinliyse council çalıştır, yanıt metni döndür.

    phi/production/secret/blocked → council çağrılmaz, insan-onayı mesajı döner.
    Ağır importlar lazy (connector import'u ucuz kalsın).
    """
    from orchestrator.gateway import preflight
    gw = preflight(task, project_hint)
    if gw.blocked or gw.risk not in ALLOWED_AUTO:
        reason = gw.block_reason or f"risk={gw.risk} otomatik kanal tavanının üstünde (≤internal)"
        return f"⛔ Otomatik çalıştırılmadı: {reason}\nİnsan onayı gerekiyor (interaktif /konsey)."
    from orchestrator.graph import build
    final = build().invoke({"task": task, "project_hint": project_hint},
                           config={"recursion_limit": 60})
    return (final.get("report") or "(rapor üretilmedi)")[:3500]   # platform mesaj limiti


class Connector:
    """Tüm connector'lar bunu uygular."""
    name = "base"

    def run(self) -> None:  # pragma: no cover
        raise NotImplementedError
