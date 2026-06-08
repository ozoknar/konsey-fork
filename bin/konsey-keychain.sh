#!/usr/bin/env bash
# Konsey credential yönetimi — macOS Keychain (Anayasa Madde 8.3)
# Secret asla argv/history/log'a düşmez: 'add' interaktif gizli prompt kullanır.
#
# Kullanım:
#   ./bin/konsey-keychain.sh add    <servis>     # gizli prompt, Keychain'e yazar
#   ./bin/konsey-keychain.sh get    <servis>     # değeri stdout'a (dikkatli kullan)
#   ./bin/konsey-keychain.sh check               # beklenen servislerin varlığı (değer GÖSTERİLMEZ)
#   ./bin/konsey-keychain.sh list                # konsey- ön ekli kayıtlar
#
# Örnek servis adları (kendi ihtiyacınıza göre):
#   konsey-anthropic  (örn. ANTHROPIC_API_KEY)
#   konsey-openai     (örn. OPENAI_API_KEY)
#   konsey-google     (örn. GEMINI_API_KEY)
# Not: Claude CLI / Codex / agy genelde abonelik/OAuth ile giriş yapar —
#      bunlar için ayrı API key gerekmeyebilir. EXPECTED listesini override:
#      KONSEY_KEYCHAIN_SERVICES="svc1 svc2" ortam değişkeni.

set -euo pipefail
ACCT="${USER}"
CMD="${1:-help}"
SVC="${2:-}"

read -ra EXPECTED <<< "${KONSEY_KEYCHAIN_SERVICES:-konsey-anthropic konsey-openai konsey-google}"

case "$CMD" in
  add)
    [ -z "$SVC" ] && { echo "servis adı gerekli: add <servis>"; exit 1; }
    # -w değeri verilmez → security gizli prompt açar (secret argv'ye girmez)
    security add-generic-password -U -a "$ACCT" -s "$SVC" -w
    echo "✓ Keychain'e yazıldı: $SVC"
    ;;
  get)
    [ -z "$SVC" ] && { echo "servis adı gerekli: get <servis>"; exit 1; }
    security find-generic-password -a "$ACCT" -s "$SVC" -w
    ;;
  check)
    echo "=== Beklenen credential durumu (değer gösterilmez) ==="
    for s in "${EXPECTED[@]}"; do
      if security find-generic-password -s "$s" >/dev/null 2>&1; then echo "✓ VAR : $s"; else echo "✗ yok : $s"; fi
    done
    ;;
  list)
    security dump-keychain 2>/dev/null | grep -o '"svce"<blob>="konsey-[^"]*"' | sort -u || echo "(konsey- kaydı yok)"
    ;;
  *)
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac
