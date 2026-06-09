#!/usr/bin/env bash
# Konsey kurulum — yerel veya uzak.
#   Yerel:  ./install.sh
#   Uzak:   curl -fsSL <repo-raw-url>/install.sh | bash
# Etkileşimsiz (CI): KONSEY_ASSUME_YES=1 ve istenirse KONSEY_SECURITY_LEVEL / KONSEY_TELEMETRY önceden set.
set -euo pipefail

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
    echo "Güvenlik seviyesi seçin (akışkanlık ↔ güvenlik):"
    echo "  1) strict  — secret+PHI bloklar, ≥2 sağlayıcı, insan onayı"
    echo "  2) medium  — secret bloklar, PHI uyarır (önerilen)"
    echo "  3) weak    — yalnız uyarır, max akışkanlık"
    read -rp "Seçim [2]: " s < /dev/tty; case "$s" in 1) LEVEL=strict;; 3) LEVEL=weak;; *) LEVEL=medium;; esac

    echo
    echo "Anonim kullanım verisi paylaşımı (opt-in) — ürünü geliştirmemize yardım eder."
    echo "Toplanan: yalnız anonim metadata (özellik kullanımı, hata kodu, sürüm)."
    echo "ASLA: görev içeriği, PHI, secret. Detay: PRIVACY.md. Reddetseniz de araç tam çalışır."
    read -rp "Paylaşımı açayım mı? [e/H]: " t < /dev/tty
    case "$t" in [eEyY]*) TELEM=on;; *) TELEM=off;; esac
  fi

  # .env'e yaz (idempotent: anahtar varsa değiştir, yoksa ekle)
  _set() { grep -q "^$1=" .env && sed -i.bak "s|^$1=.*|$1=$2|" .env || echo "$1=$2" >> .env; rm -f .env.bak; }
  _set KONSEY_SECURITY_LEVEL "$LEVEL"
  _set KONSEY_TELEMETRY "$TELEM"
  echo "▸ .env yazıldı (güvenlik=$LEVEL, telemetri=$TELEM)"
fi

echo
echo "✓ Kurulum tamam. Dene:"
echo "    ./bin/konsey-run \"ilk görevim\""
echo "    ./bin/konsey recent"
