"""konsey doctor — kurulum, sağlayıcı, auth, güvenlik ve telemetri durumunu gösterir.

Kullanıcı "gerçekten kuruldu mu, hangi YZ ürünlerim hazır?" sorusunu tek bakışta yanıtlar.
"""
from __future__ import annotations

import os
import shutil

from . import telemetry
from .adapters import available, load_providers


def report() -> str:
    lines = ["Konsey Doctor — kurulum durumu", "=" * 34]
    lines.append(f"Güvenlik seviyesi : {os.getenv('KONSEY_SECURITY_LEVEL', 'medium')}")
    lines.append(f"Telemetri         : {'AÇIK (opt-in)' if telemetry.enabled() else 'kapalı'}")
    lines.append("")
    lines.append("Sağlayıcılar (kullandığınız YZ ürünleri):")

    provs = load_providers()
    avail = available()
    for name, spec in provs.items():
        cmd0 = (spec.get("command") or ["?"])[0]
        auth_env = spec.get("auth_env")
        if not spec.get("enabled", True):
            status = "— devre dışı"
        elif shutil.which(cmd0) is None:
            status = f"✗ CLI yok ({cmd0})"
        elif auth_env and not os.getenv(auth_env):
            status = f"✗ auth eksik ({auth_env})"
        else:
            status = "✓ hazır"
        lines.append(f"  {name:12s} [{spec.get('role', ''):10s}] {status}")

    n_ok = sum(1 for v in avail.values() if v)
    lines.append("")
    if n_ok == 0:
        lines.append("⚠ Hiç sağlayıcı hazır değil — bir YZ CLI kurun (claude/codex/agy) "
                     "veya konsey.providers.toml düzenleyin.")
    elif n_ok == 1:
        lines.append("ℹ Solo mod (1 sağlayıcı hazır). Çapraz-doğrulama için 2+ önerilir.")
    else:
        lines.append(f"✓ {n_ok} sağlayıcı hazır — tam çapraz-doğrulama mümkün.")
    return "\n".join(lines)


def main() -> None:
    print(report())


if __name__ == "__main__":
    main()
