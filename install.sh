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

# --- Kurulum sihirbazı: ek sağlayıcı + mesaj connector'ları (opt-in) ---------
# /dev/tty ile sorar. tty yok / KONSEY_ASSUME_YES=1 / KONSEY_NO_WIZARD=1 → atlanır
# (varsayılan: hiçbir entegrasyon açılmaz — güvenli). Secret'lar .env'e yazılır
# (gitignore'lu); enable bayrakları connectors.toml / konsey.providers.toml'a.
# NOT: prompt'u stderr'e bas — fonksiyon $(...) içinde çağrılıyor; stdout yalnız cevabı taşımalı.
_ask()    { case "$_L" in tr) printf "%s" "$1" >&2;; *) printf "%s" "$2" >&2;; esac; local a; read -r  a < /dev/tty; printf '%s' "$a"; }
_secret() { case "$_L" in tr) printf "%s" "$1" >&2;; *) printf "%s" "$2" >&2;; esac; local a; read -rs a < /dev/tty; echo > /dev/tty; printf '%s' "$a"; }
_envset() { grep -q "^$1=" .env 2>/dev/null && sed -i.bak "s|^$1=.*|$1=$2|" .env || echo "$1=$2" >> .env; rm -f .env.bak; }

if [ -e /dev/tty ] && [ "${KONSEY_ASSUME_YES:-0}" != "1" ] && [ "${KONSEY_NO_WIZARD:-0}" != "1" ]; then
  case "$(_ask $'\nEk sağlayıcı/connector kuralım mı (yerel model, API key, Telegram, Notion, Slack, WhatsApp)? [e/H]: ' $'\nSet up extra providers/connectors (local model, API keys, Telegram, Notion, Slack, WhatsApp)? [y/N]: ')" in
  [eEyY]*)
    _need_conn=0

    # 1) Yerel model (Ollama) — cihazdan veri çıkmaz
    case "$(_ask '  • Yerel model (Ollama) ekleyeyim mi? [e/H]: ' '  • Add local model (Ollama)? [y/N]: ')" in [eEyY]*)
      _model="$(_ask '    model adı [llama3.1]: ' '    model name [llama3.1]: ')"; [ -n "$_model" ] || _model="llama3.1"
      [ -f konsey.providers.toml ] || cp konsey.providers.example.toml konsey.providers.toml 2>/dev/null || true
      export _KW_OLLAMA=1 _KW_OLLAMA_MODEL="$_model"
      command -v ollama >/dev/null 2>&1 || echo "    ⚠ 'ollama' yok — https://ollama.com kurup: ollama pull $_model"
    ;; esac

    # 2) API anahtarları (opsiyonel; CLI OAuth kullanıyorsa gerekmez) — gizli giriş
    case "$(_ask '  • API anahtarı eklemek ister misin? [e/H]: ' '  • Add API keys? [y/N]: ')" in [eEyY]*)
      for _kv in "ANTHROPIC_API_KEY:Anthropic" "OPENAI_API_KEY:OpenAI" "GOOGLE_API_KEY:Google"; do
        _val="$(_secret "    ${_kv##*:} key (boş=atla): " "    ${_kv##*:} key (empty=skip): ")"
        [ -n "$_val" ] && { _envset "${_kv%%:*}" "$_val"; echo "    ✓ ${_kv%%:*} .env'e yazıldı"; }
      done
    ;; esac

    # 3) Telegram (bugün çalışır)
    case "$(_ask '  • Telegram bağlayayım mı? [e/H]: ' '  • Enable Telegram? [y/N]: ')" in [eEyY]*)
      _t="$(_secret '    BotFather token: ' '    BotFather token: ')"
      [ -n "$_t" ] && { _envset TELEGRAM_BOT_TOKEN "$_t"; export _KW_TELEGRAM=1; _need_conn=1; echo "    ✓ Telegram ayarlandı"; }
    ;; esac

    # 4) Notion
    case "$(_ask '  • Notion bağlayayım mı? [e/H]: ' '  • Enable Notion? [y/N]: ')" in [eEyY]*)
      _nt="$(_secret '    Notion integration token: ' '    Notion integration token: ')"
      _nd="$(_ask    '    Notion database id: '       '    Notion database id: ')"
      [ -n "$_nt" ] && { _envset NOTION_TOKEN "$_nt"; _envset NOTION_DATABASE_ID "$_nd"; export _KW_NOTION=1; _need_conn=1; echo "    ✓ Notion ayarlandı"; }
    ;; esac

    # 5) Slack (slack_sdk gerekir)
    case "$(_ask '  • Slack bağlayayım mı? [e/H]: ' '  • Enable Slack? [y/N]: ')" in [eEyY]*)
      _sb="$(_secret '    SLACK_BOT_TOKEN: ' '    SLACK_BOT_TOKEN: ')"
      _sa="$(_secret '    SLACK_APP_TOKEN: ' '    SLACK_APP_TOKEN: ')"
      [ -n "$_sb" ] && { _envset SLACK_BOT_TOKEN "$_sb"; _envset SLACK_APP_TOKEN "$_sa"; export _KW_SLACK=1; _need_conn=1
        echo "    ✓ Slack ayarlandı"; "$PY" -m pip install --quiet slack_sdk 2>/dev/null && echo "    ✓ slack_sdk kuruldu" || echo "    ⚠ 'pip install slack_sdk' gerekebilir"; }
    ;; esac

    # 6) WhatsApp (Meta + public HTTPS webhook ister)
    case "$(_ask '  • WhatsApp bağlayayım mı? [e/H]: ' '  • Enable WhatsApp? [y/N]: ')" in [eEyY]*)
      _wt="$(_secret '    WHATSAPP_TOKEN: '        '    WHATSAPP_TOKEN: ')"
      _wp="$(_ask    '    WHATSAPP_PHONE_ID: '     '    WHATSAPP_PHONE_ID: ')"
      _wv="$(_secret '    WHATSAPP_VERIFY_TOKEN: ' '    WHATSAPP_VERIFY_TOKEN: ')"
      _ws="$(_secret '    WHATSAPP_APP_SECRET: '   '    WHATSAPP_APP_SECRET: ')"
      [ -n "$_wt" ] && { _envset WHATSAPP_TOKEN "$_wt"; _envset WHATSAPP_PHONE_ID "$_wp"; _envset WHATSAPP_VERIFY_TOKEN "$_wv"; _envset WHATSAPP_APP_SECRET "$_ws"
        export _KW_WHATSAPP=1; _need_conn=1; echo "    ✓ WhatsApp ayarlandı (public webhook'u Meta'ya ayrıca kaydedin)"; }
    ;; esac

    # connectors.toml hazırla (gerekirse) + enable bayraklarını güvenle ayarla (blok-içi)
    [ "$_need_conn" = "1" ] && [ ! -f connectors.toml ] && { cp connectors.example.toml connectors.toml 2>/dev/null || true; }
    "$PY" - <<'PYEOF'
import os, re, pathlib
def enable(path, block, model=None):
    p = pathlib.Path(path)
    if not p.exists(): return
    out, inb, target = [], False, f"[{block}]"
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            inb = (s == target)
        if inb and re.match(r"\s*enabled\s*=", ln):
            ln = re.sub(r"(enabled\s*=\s*).*", r"\1true", ln)
        if inb and model and re.match(r"\s*command\s*=", ln):
            ln = re.sub(r'("run",\s*")[^"]*(")', lambda m: m.group(1)+model+m.group(2), ln)
        out.append(ln)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
if os.environ.get("_KW_OLLAMA"):
    enable("konsey.providers.toml", "providers.ollama", os.environ.get("_KW_OLLAMA_MODEL"))
for env, blk in [("_KW_TELEGRAM","connectors.telegram"),("_KW_NOTION","connectors.notion"),
                 ("_KW_SLACK","connectors.slack"),("_KW_WHATSAPP","connectors.whatsapp")]:
    if os.environ.get(env): enable("connectors.toml", blk)
PYEOF
    echo "▸ entegrasyonlar yapılandırıldı. Connector'ı başlatmak için: konsey-connectors"
  ;;
  esac
fi

# --- Global komut: konsey-* → PATH'teki yazılabilir dizine symlink -----------
# Amaç: kurulumdan sonra YENİ açılan terminalde (zsh/bash, source gerekmeden)
# `konsey` çalışsın. Tercih: zaten PATH'te olan bir bin dizinine symlink; o yoksa
# shell rc'sine PATH ekle (fallback). Atla: KONSEY_NO_PATH=1.
KONSEY_BIN="$(pwd)/bin"
_add_path=0
if [ "${KONSEY_NO_PATH:-0}" != "1" ]; then
  if [ "${KONSEY_ASSUME_YES:-0}" = "1" ]; then
    [ "${KONSEY_ADD_PATH:-0}" = "1" ] && _add_path=1
  elif [ -e /dev/tty ]; then
    case "$_L" in
      tr) printf "konsey komutları her yerden çalışsın mı? [E/h]: ";;
      *)  printf "Make konsey commands available everywhere? [Y/n]: ";;
    esac
    read -r _p < /dev/tty; case "$_p" in [hHnN]*) _add_path=0;; *) _add_path=1;; esac
  fi
fi

_linked=0; _hint_rc=""
if [ "$_add_path" = "1" ]; then
  # 1) PATH'te yazılabilir standart bir bin dizini bul ve symlink'le.
  _dir=""
  for d in "${HOMEBREW_PREFIX:-/opt/homebrew}/bin" /usr/local/bin "$HOME/.local/bin"; do
    [ -d "$d" ] && [ -w "$d" ] && { _dir="$d"; break; }
  done
  if [ -n "$_dir" ]; then
    for f in "$KONSEY_BIN"/*; do
      case "$(basename "$f")" in *.*) continue;; esac   # .sh/.py yardımcıları atla
      [ -x "$f" ] || continue
      ln -sf "$f" "$_dir/$(basename "$f")" && _linked=$((_linked+1))
    done
    [ "$_linked" -gt 0 ] && echo "▸ $_linked komut bağlandı → $_dir"
  fi
  # 2) Symlink olmadıysa (yazılabilir PATH dizini yok): shell rc'ye PATH ekle.
  if [ "$_linked" -eq 0 ]; then
    case "${SHELL##*/}" in
      zsh)  _rc="$HOME/.zshrc" ;;
      bash) [ -f "$HOME/.bash_profile" ] && _rc="$HOME/.bash_profile" || _rc="$HOME/.bashrc" ;;
      *)    _rc="$HOME/.profile" ;;
    esac
    grep -qs "konsey/bin" "$_rc" 2>/dev/null || \
      printf '\n# Konsey CLI\nexport PATH="%s:$PATH"\n' "$KONSEY_BIN" >> "$_rc"
    _hint_rc="$_rc"
    echo "▸ PATH eklendi ($_rc)."
  fi
fi

echo
msg done
if [ "$_add_path" = "1" ]; then
  # NOT: hâlihazırda açık olan kabuk değişikliği göremez (Unix). Yeni terminal aç.
  if [ -n "$_hint_rc" ]; then
    case "$_L" in
      tr) echo "  ⚠ Yeni terminal aç (ya da: source $_hint_rc), sonra:";;
      *)  echo "  ⚠ Open a new terminal (or: source $_hint_rc), then:";;
    esac
  else
    case "$_L" in
      tr) echo "  ⚠ Yeni terminal aç (ya da bu terminalde: hash -r), sonra:";;
      *)  echo "  ⚠ Open a new terminal (or run 'hash -r' here), then:";;
    esac
  fi
  echo "    konsey-run \"my first task\""
  echo "    konsey recent"
else
  echo "    ./bin/konsey-run \"my first task\""
  echo "    ./bin/konsey recent"
fi
