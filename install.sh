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

# --- Python 3.12+ tespiti + (gerekirse) otomatik kurulum ---------------------
# Önce uygun bir yorumlayıcı aranır (sürüm>=3.12 ve venv/ensurepip çalışır);
# bulunamazsa platforma göre otomatik kurulur ve tekrar aranır.
# KONSEY_ASSUME_YES=1 → onay sormadan kurar; KONSEY_NO_AUTOINSTALL=1 → kapatır.
MIN_PY="3.12"

# $1 yorumlayıcı sürüm>=3.12 ve venv/ensurepip gerçekten import edilebiliyorsa 0 döner.
_py_ok() {
  command -v "$1" >/dev/null 2>&1 || return 1
  "$1" - <<'PY' >/dev/null 2>&1
import sys, venv, ensurepip  # venv/ensurepip yoksa ImportError
sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)
PY
}

# Aday yorumlayıcılardan uygun ilkini stdout'a yazar; bulursa 0 döner.
_find_py() {
  local c
  for c in "${PYTHON:-}" python3.13 python3.12 python3 python; do
    [ -n "$c" ] || continue
    if _py_ok "$c"; then echo "$c"; return 0; fi
  done
  return 1
}

# Platforma göre Python 3.12 kurmayı dener (macOS: brew, Linux: apt/dnf/pacman/apk).
_install_py() {
  local os; os="$(uname -s)"
  case "$os" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        echo "▸ Homebrew ile python@3.12 kuruluyor..."
        # curl|bash'te stdin script gövdesidir; brew onu tüketmesin diye </dev/null.
        brew install python@3.12 </dev/null || return 1
        local pfx; pfx="$(brew --prefix python@3.12 2>/dev/null || true)"
        [ -n "$pfx" ] && export PATH="$pfx/bin:$pfx/libexec/bin:$PATH"
        return 0
      fi
      echo "✗ Homebrew bulunamadı. Önce kurun: https://brew.sh — sonra tekrar deneyin."
      return 1 ;;
    Linux)
      local SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"
      if command -v apt-get >/dev/null 2>&1; then
        echo "▸ apt ile Python 3.12 kuruluyor..."
        $SUDO apt-get update -qq || true
        if ! apt-cache show python3.12 >/dev/null 2>&1; then  # eski sürümlerde deadsnakes gerekir
          $SUDO apt-get install -y -qq software-properties-common || true
          $SUDO add-apt-repository -y ppa:deadsnakes/ppa || true
          $SUDO apt-get update -qq || true
        fi
        $SUDO apt-get install -y -qq python3.12 python3.12-venv </dev/null || return 1; return 0
      elif command -v dnf >/dev/null 2>&1; then
        echo "▸ dnf ile Python 3.12 kuruluyor..."; $SUDO dnf install -y python3.12 </dev/null || return 1; return 0
      elif command -v pacman >/dev/null 2>&1; then
        echo "▸ pacman ile Python kuruluyor..."; $SUDO pacman -Sy --noconfirm python </dev/null || return 1; return 0
      elif command -v apk >/dev/null 2>&1; then
        echo "▸ apk ile Python kuruluyor..."; $SUDO apk add --no-cache python3 </dev/null || return 1; return 0
      fi
      echo "✗ Desteklenen paket yöneticisi yok (apt/dnf/pacman/apk). Python ${MIN_PY}+ elle kurun."
      return 1 ;;
    *)
      echo "✗ Otomatik kurulum bu platformda ($os) desteklenmiyor. Python ${MIN_PY}+ elle kurun."
      return 1 ;;
  esac
}

PY="$(_find_py || true)"
if [ -z "$PY" ]; then
  echo "✗ Python ${MIN_PY}+ bulunamadı (venv/ensurepip dahil)."
  if [ "${KONSEY_NO_AUTOINSTALL:-0}" = "1" ]; then
    echo "  Otomatik kurulum kapalı (KONSEY_NO_AUTOINSTALL=1). Python ${MIN_PY}+ kurup tekrar deneyin."; exit 1
  fi
  # curl|bash'te stdin script'tir → onayı /dev/tty üzerinden sor.
  if [ -e /dev/tty ] && [ "${KONSEY_ASSUME_YES:-0}" != "1" ]; then
    printf "Python %s otomatik kurulsun mu? [E/h]: " "$MIN_PY"; read -r _ans < /dev/tty
    case "$_ans" in [hHnN]*) echo "✗ İptal. Python ${MIN_PY}+ kurup tekrar deneyin."; exit 1;; esac
  fi
  echo "▸ Python ${MIN_PY} otomatik kurulumu deneniyor..."
  _install_py || { echo "✗ Otomatik kurulum başarısız. Python ${MIN_PY}+ elle kurun."; exit 1; }
  hash -r 2>/dev/null || true
  PY="$(_find_py || true)"
  [ -n "$PY" ] || { echo "✗ Kurulum sonrası da uygun Python bulunamadı. PATH'i kontrol edin."; exit 1; }
fi
echo "▸ Python: $("$PY" --version) ($PY)"

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

# --- PATH: konsey komutlarını global yap (opt-in, idempotent) ---
# Atla: KONSEY_NO_PATH=1. CI/non-interaktif: yalnız KONSEY_ADD_PATH=1 ile ekler.
KONSEY_BIN="$(pwd)/bin"
_add_path=0
if [ "${KONSEY_NO_PATH:-0}" != "1" ]; then
  if [ "${KONSEY_ASSUME_YES:-0}" = "1" ]; then
    [ "${KONSEY_ADD_PATH:-0}" = "1" ] && _add_path=1
  elif [ -e /dev/tty ]; then
    case "$_L" in
      tr) printf "konsey komutlarını PATH'e ekleyeyim mi (her yerden çalışsın)? [E/h]: ";;
      *)  printf "Add konsey commands to PATH (run from anywhere)? [Y/n]: ";;
    esac
    read -r _p < /dev/tty; case "$_p" in [hHnN]*) _add_path=0;; *) _add_path=1;; esac
  fi
fi
if [ "$_add_path" = "1" ]; then
  case "${SHELL##*/}" in
    zsh)  _rc="$HOME/.zshrc" ;;
    bash) [ -f "$HOME/.bash_profile" ] && _rc="$HOME/.bash_profile" || _rc="$HOME/.bashrc" ;;
    *)    _rc="$HOME/.profile" ;;
  esac
  if grep -qs "konsey/bin" "$_rc" 2>/dev/null; then
    echo "▸ PATH zaten ekli ($_rc)."
  else
    printf '\n# Konsey CLI\nexport PATH="%s:$PATH"\n' "$KONSEY_BIN" >> "$_rc"
    echo "▸ PATH güncellendi ($_rc) → yeni terminal aç ya da: source $_rc"
  fi
fi

echo
msg done
if [ "$_add_path" = "1" ]; then
  echo "    konsey-run \"my first task\""
  echo "    konsey recent"
else
  echo "    ./bin/konsey-run \"my first task\""
  echo "    ./bin/konsey recent"
fi
