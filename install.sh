#!/usr/bin/env bash
# Konsey kurulum — yerel veya uzak.
#   Yerel:  ./install.sh
#   Uzak:   curl -fsSL <repo-raw-url>/install.sh | bash
# Etkileşimsiz (CI): KONSEY_ASSUME_YES=1 ve istenirse KONSEY_SECURITY_LEVEL / KONSEY_TELEMETRY önceden set.
set -euo pipefail

# i18n: sistem locale tr ise Türkçe, değilse İngilizce (KONSEY_LANG override).
case "${KONSEY_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}}" in tr*|TR*) _L=tr;; *) _L=en;; esac
msg() { case "$1:$_L" in
  done:tr)       echo "✓ Kurulum tamam. Dene:";;
  done:*)        echo "✓ Install complete. Try:";;
  sec.head:tr)   echo "Güvenlik seviyesi seçin (akışkanlık ↔ güvenlik):";;
  sec.head:*)    echo "Choose a security level (fluidity ↔ safety):";;
  sec.s:tr)      echo "  1) strict  — secret+PHI bloklar, ≥2 sağlayıcı, insan onayı";;
  sec.s:*)       echo "  1) strict  — blocks secret+PHI, ≥2 providers, human approval";;
  sec.m:tr)      echo "  2) medium  — secret bloklar, PHI uyarır (önerilen)";;
  sec.m:*)       echo "  2) medium  — blocks secret, warns on PHI (recommended)";;
  sec.w:tr)      echo "  3) weak    — yalnız uyarır, max akışkanlık";;
  sec.w:*)       echo "  3) weak    — warn only, max fluidity";;
  sec.pick:tr)   printf "Seçim [2]: ";;     sec.pick:*) printf "Choice [2]: ";;
  tel.intro:tr)  echo "Anonim kullanım verisi paylaşımı (opt-in) — ürünü geliştirmemize yardım eder.";;
  tel.intro:*)   echo "Share anonymous usage data (opt-in) — helps us improve the product.";;
  tel.what:tr)   echo "Toplanan: yalnız anonim metadata. ASLA görev içeriği/PHI/secret. Detay: PRIVACY.md.";;
  tel.what:*)    echo "Collected: anonymous metadata only. NEVER task content/PHI/secrets. See PRIVACY.md.";;
  tel.ask:tr)    printf "Paylaşımı açayım mı? [e/H]: ";; tel.ask:*) printf "Enable sharing? [y/N]: ";;
esac; }

REPO_URL="${KONSEY_REPO_URL:-https://github.com/eMediquality/konsey.git}"

# --- Uzak bootstrap: repo yoksa klonla ---
if [ ! -f "schema.sql" ] || [ ! -d "orchestrator" ]; then
  REF="${KONSEY_REF:-master}"
  echo "▸ Konsey klonlanıyor ($REPO_URL @ $REF)..."
  command -v git >/dev/null || { echo "git gerekli."; exit 1; }
  git clone --depth 1 --branch "$REF" "$REPO_URL" konsey
  cd konsey
fi

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "✗ '$PY' bulunamadı. Python 3.12+ kurun veya PYTHON=... verin."; exit 1; }
echo "▸ Python: $($PY --version)"

# Python >= 3.12 + venv/ensurepip preflight (net hata, kriptik fail değil)
PYVER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)"
case "$PYVER" in
  3.1[2-9]|3.[2-9][0-9]|[4-9].*) : ;;
  *) echo "✗ Python 3.12+ gerekli (bulunan: $PYVER). 'python3.12' kurup PYTHON=python3.12 ./install.sh deneyin."; exit 1;;
esac
"$PY" -c 'import venv, ensurepip' 2>/dev/null || {
  echo "✗ Python 'venv'/'ensurepip' yok. Debian/Ubuntu: sudo apt install python3-venv"; exit 1; }

echo "▸ venv (.venv) + bağımlılıklar..."
"$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -e .

echo "▸ audit DB şeması (idempotent)..."
python - <<'PY'
import duckdb, os, pathlib
db = os.getenv("KONSEY_DB", "council.duckdb")
duckdb.connect(db).execute(pathlib.Path("schema.sql").read_text(encoding="utf-8"))
print(f"  şema hazır: {db}")
PY

chmod +x bin/* install.sh 2>/dev/null || true

# --- Yapılandırma: .env (interaktif consent) ---
if [ ! -f .env ]; then
  cp .env.example .env
  LEVEL="${KONSEY_SECURITY_LEVEL:-medium}"
  TELEM="${KONSEY_TELEMETRY:-off}"

  # curl|bash'te stdin script'tir → /dev/tty üzerinden sor (yoksa varsayılanlar).
  if [ -e /dev/tty ] && [ "${KONSEY_ASSUME_YES:-0}" != "1" ]; then
    echo
    msg sec.head; msg sec.s; msg sec.m; msg sec.w
    msg sec.pick; read -r s < /dev/tty; case "$s" in 1) LEVEL=strict;; 3) LEVEL=weak;; *) LEVEL=medium;; esac

    echo
    msg tel.intro; msg tel.what
    msg tel.ask; read -r t < /dev/tty
    case "$t" in [eEyY]*) TELEM=on;; *) TELEM=off;; esac
  fi

  # .env'e yaz (idempotent: anahtar varsa değiştir, yoksa ekle)
  _set() { grep -q "^$1=" .env && sed -i.bak "s|^$1=.*|$1=$2|" .env || echo "$1=$2" >> .env; rm -f .env.bak; }
  _set KONSEY_SECURITY_LEVEL "$LEVEL"
  _set KONSEY_TELEMETRY "$TELEM"
  echo "▸ .env yazıldı (güvenlik=$LEVEL, telemetri=$TELEM)"
fi

echo
msg done
echo "    ./bin/konsey-run \"my first task\""
echo "    ./bin/konsey recent"
