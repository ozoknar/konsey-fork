"""konsey-connectors girişi — etkin connector'ları çalıştır.

MVP: tek etkin connector'ı (genelde telegram) çalıştırır. Çoklu connector için
ileride thread/async. Hiç etkin yoksa net mesaj verir.
"""
from __future__ import annotations

import sys

from . import config


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    names = config.enabled_connectors()
    if argv:                       # ad açıkça verildiyse (örn. `konsey-connectors telegram`)
        names = [argv[0]]
    if not names:
        print("Etkin connector yok. connectors.toml'u düzenleyin "
              "(enabled=true + auth_env ortam değişkeni).")
        return
    name = names[0]
    spec = config.load().get(name, {})
    print(f"Connector başlatılıyor: {name}")
    if name == "telegram":
        from . import telegram
        telegram.run(allowed_chats=spec.get("allowed_chats"))
    else:
        print(f"Connector '{name}' henüz uygulanmadı "
              "(yol haritası: slack, notion, whatsapp). Bkz. CONNECTORS.md")


if __name__ == "__main__":
    main()
