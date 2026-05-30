#!/usr/bin/env sh
# Council installer — POSIX, idempotent, sudo-free (Constitution Article 0 & 19.4).
#
#   ./install.sh [--quick] [--no-init] [--locale LANG] [--prefix DIR] [--python PY]
#
# What it does (download–inspect–run friendly: read it before piping):
#   1. Preflight: OS + toolchain (git / Xcode CLT on macOS) + Python (>=3.12 required;
#      the proven-working floor. CI pins 3.12; newer interpreters such as 3.14 run the
#      suite green but are not the CI baseline).
#   2. Create an isolated virtualenv under the repo (.venv) — never touches system Python.
#   3. Install pinned dependencies + this package (editable) so the `council` and `konsey`
#      console-scripts exist, then symlink them onto PATH (~/.local/bin) — no sudo.
#   4. Run `council init` (Article 0 Bootstrap) unless --no-init, then a `council doctor`
#      health report (advisory; it never gates install success).
set -eu

# --- locate the repo root (script-relative; no absolute path embedded) --------
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT="$SCRIPT_DIR"

# --- defaults / args ----------------------------------------------------------
DO_INIT=1
INIT_FLAGS=""
VENV_DIR="$REPO_ROOT/.venv"
PYTHON_BIN=""
LOCALE="${KONSEY_LOCALE:-}"

say()  { printf '%s\n' "$*"; }
warn() { printf '!! %s\n' "$*" >&2; }
die()  { printf 'xx %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

# Guard value-taking flags so `--locale` (etc.) with no value fails clearly instead of
# tripping `set -u` with "$1: unbound variable". $1 here is the remaining-arg count ($#).
need_val() { [ "$1" -ge 2 ] || die "option '$2' needs a value"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --quick)     INIT_FLAGS="$INIT_FLAGS --quick" ;;
        --no-init)   DO_INIT=0 ;;
        --locale)    need_val "$#" "$1"; shift; LOCALE="$1" ;;
        --prefix)    need_val "$#" "$1"; shift; VENV_DIR="$1" ;;
        --python)    need_val "$#" "$1"; shift; PYTHON_BIN="$1" ;;
        -h|--help)   usage 0 ;;
        *)           echo "unknown argument: $1" >&2; usage 1 ;;
    esac
    shift
done

# Validate the locale is a sane TAG (en, tr, es, ar, pt-BR, …) so it can never
# word-split / inject into the init flags. The wizard negotiates it against the shipped
# catalogs and falls back to en for an unknown tag — any jurisdiction/language welcome.
if [ -n "$LOCALE" ]; then
    case "$LOCALE" in *[!A-Za-z0-9_-]*) die "invalid --locale '$LOCALE' (letters/digits/-/_ only)" ;; esac
fi

# --- 1. OS detection (evidence, not assumption) -------------------------------
OS_NAME="$(uname -s 2>/dev/null || echo unknown)"
case "$OS_NAME" in
    Darwin)  PLATFORM="macos" ;;
    Linux)   PLATFORM="linux" ;;
    MINGW*|MSYS*|CYGWIN*)
        PLATFORM="windows"
        warn "Native Windows detected. Use WSL2 for a supported install; install.ps1 redirects there." ;;
    *)       PLATFORM="unknown"; warn "Unrecognized OS '$OS_NAME' — proceeding best-effort." ;;
esac
say "== Council installer =="
say "   repo     : $REPO_ROOT"
say "   platform : $PLATFORM ($OS_NAME)"

# --- 1b. toolchain preflight (messages only; NO auto-install — that is Faz 2) --
# The editable install builds a wheel and the docs assume `git clone`, so a missing
# compiler / git is clearer caught up front than failing cryptically mid-pip.
preflight_toolchain() {
    if [ "$PLATFORM" = "macos" ]; then
        if ! xcode-select -p >/dev/null 2>&1; then
            die "Xcode Command Line Tools are not installed (needed to build dependencies).
   Install them, then re-run:
       xcode-select --install
       ./install.sh"
        fi
    fi
    if ! command -v git >/dev/null 2>&1; then
        if [ "$PLATFORM" = "macos" ]; then
            die "git was not found. Install the Xcode Command Line Tools, then re-run:
       xcode-select --install
       ./install.sh"
        else
            die "git was not found. Install it, then re-run ./install.sh:
       sudo apt-get install -y git     # Debian/Ubuntu
       sudo dnf install -y git         # Fedora/RHEL"
        fi
    fi
}
preflight_toolchain

# --- 2. find a Python >= 3.12 -------------------------------------------------
# find_python ECHOES a status token parsed by the caller — globals set inside a
# `$(...)` subshell would be LOST in the parent, so we never rely on them, and we
# never `die` from inside the subshell (that would only kill the subshell):
#   OK <cmd>          a runnable interpreter >= 3.12
#   OLD <cmd> <ver>   the newest interpreter found is older than the floor
#   NONE              no interpreter found at all
find_python() {
    _old_cmd=""; _old_ver=""
    for cand in python3.14 python3.13 python3.12 python3 python; do
        if command -v "$cand" >/dev/null 2>&1; then
            if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)' 2>/dev/null; then
                echo "OK $cand"; return 0
            fi
            _old_cmd="$cand"
            _old_ver="$("$cand" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null || echo '?')"
        fi
    done
    if [ -n "$_old_cmd" ]; then echo "OLD $_old_cmd $_old_ver"; else echo "NONE"; fi
    return 1
}

# Python >= 3.12 is required (the proven-working floor). All `die`s happen in the PARENT.
if [ -n "$PYTHON_BIN" ]; then
    command -v "$PYTHON_BIN" >/dev/null 2>&1 \
        || die "requested --python '$PYTHON_BIN' not found on PATH (pass a full path, e.g. --python /opt/homebrew/bin/python3.12)"
    PY="$PYTHON_BIN"
    # --python must ALSO satisfy the floor — `command -v` alone would let 3.11 through.
    "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)' 2>/dev/null \
        || die "requested --python '$PYTHON_BIN' is older than the floor — Python >= 3.12 is required. Pass a 3.12+ interpreter."
else
    _FP="$(find_python)" || true
    _ST="${_FP%% *}"
    if [ "$_ST" = "OK" ]; then
        PY="${_FP#OK }"
    else
        if [ "$_ST" = "OLD" ]; then
            _rest="${_FP#OLD }"; _oc="${_rest%% *}"; _ov="${_rest#* }"
            _detail="Found '$_oc' ($_ov), older than the 3.12 floor."
        else
            _detail="No Python interpreter was found on PATH."
        fi
        if [ "$PLATFORM" = "macos" ]; then
            die "Python >= 3.12 is required (proven-working floor). $_detail
   Install 3.12+ (Homebrew or uv), then re-run with that interpreter:
       brew install python@3.12 && ./install.sh --python \"\$(brew --prefix python@3.12)/bin/python3.12\"
       uv python install 3.12   && ./install.sh --python \"\$(uv python find 3.12)\""
        else
            die "Python >= 3.12 is required (proven-working floor). $_detail
   Install 3.12+, then re-run with that interpreter:
       uv python install 3.12  && ./install.sh --python \"\$(uv python find 3.12)\"
       sudo apt-get install -y python3.12 python3.12-venv   # Debian/Ubuntu
       sudo dnf install -y python3.12                       # Fedora/RHEL
   then: ./install.sh --python /full/path/to/python3.12"
        fi
    fi
fi
PYVER="$("$PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
say "   python   : $PY ($PYVER)"

# Informational only — does NOT gate the install. 3.12 is the floor *and* the CI
# baseline (.github/workflows/ci.yml); 3.13/3.14 are known to run the suite green but
# are not the pinned CI version. Flag anything newer so the user knows it is untested-in-CI.
PYMINOR="$("$PY" -c 'import sys;print(sys.version_info[1])')"
if [ "$PYMINOR" -gt 12 ] 2>/dev/null; then
    say "   note     : Python 3.$PYMINOR is newer than the CI baseline (3.12). It is expected"
    say "              to work, but CI is pinned to 3.12 — if anything looks off, reproduce on"
    say "              3.12 before filing."
fi

# --- 3. isolated virtualenv (idempotent) --------------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
    say "-- creating virtualenv: $VENV_DIR"
    if ! "$PY" -m venv "$VENV_DIR"; then
        if [ "$PLATFORM" = "macos" ]; then
            die "venv creation failed. Reinstall Python 3.12 (Homebrew/uv), then re-run:
       brew install python@3.12 && ./install.sh --python \"\$(brew --prefix python@3.12)/bin/python3.12\""
        else
            die "venv creation failed (is the venv module installed?):
       sudo apt-get install -y python3.12-venv   # Debian/Ubuntu"
        fi
    fi
else
    say "-- reusing virtualenv: $VENV_DIR"
fi
VPY="$VENV_DIR/bin/python"
[ -x "$VPY" ] || die "virtualenv python missing at $VPY"

say "-- upgrading pip (quiet)"
"$VPY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || warn "pip upgrade skipped (offline?)"

# --- 4. pinned dependencies + package (editable, idempotent) ------------------
if [ -f "$REPO_ROOT/requirements.txt" ]; then
    say "-- installing pinned dependencies (requirements.txt)"
    "$VPY" -m pip install --quiet -r "$REPO_ROOT/requirements.txt" || die "dependency install failed"
fi
say "-- installing council (editable)"
"$VPY" -m pip install --quiet -e "$REPO_ROOT" || die "package install failed"

# --- 4b. put the console-scripts on PATH (sudo-free, idempotent symlinks) ------
# pipx / uv tool install would reinstall from PyPI (undoing the editable install) and are
# often absent on a fresh box — so symlink the venv wrappers into ~/.local/bin instead.
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
link_script() {  # $1 = console-script name (only the two we declare)
    src="$VENV_DIR/bin/$1"; dst="$BIN_DIR/$1"
    [ -x "$src" ] || { warn "console-script '$1' missing in venv (skipped)"; return 1; }
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
        say "   on PATH  : $dst (already linked)"
    elif [ -e "$dst" ] && [ ! -L "$dst" ]; then
        warn "$dst exists and is not a symlink — leaving it untouched; call directly: $src"
    else
        ln -sf "$src" "$dst"; say "   linked   : $dst -> $src"
    fi
}
link_script council || true
link_script konsey  || true

# PATH membership — do NOT edit the user's shell profile; just print the exact line.
case ":$PATH:" in
    *":$BIN_DIR:"*) BIN_ON_PATH=1 ;;
    *)              BIN_ON_PATH=0 ;;
esac
if [ "$BIN_ON_PATH" -eq 0 ]; then
    warn "$BIN_DIR is not on your PATH. Add it (zsh):"
    say  "    echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc && exec zsh"
    say  "  (bash users: append the same line to ~/.bashrc)"
fi

# Resolve the console-script for this script's own init/doctor calls.
COUNCIL="$VENV_DIR/bin/council"
if [ -x "$COUNCIL" ]; then
    RUN_COUNCIL="$COUNCIL"
else
    RUN_COUNCIL="$VPY -m council.cli"
fi
say "   council  : $RUN_COUNCIL"

# --- 5. Bootstrap (Article 0) -------------------------------------------------
if [ "$DO_INIT" -eq 1 ]; then
    say "-- council init (Article 0 Bootstrap)"
    if [ -n "$LOCALE" ]; then
        export KONSEY_LOCALE="$LOCALE"            # honored even in a piped (non-TTY) run
        INIT_FLAGS="$INIT_FLAGS --locale $LOCALE"
    fi
    # shellcheck disable=SC2086
    $RUN_COUNCIL init $INIT_FLAGS || warn "init reported a non-zero status; review above"
fi

# --- 6. honest verdict: install success is SEPARATE from provider health ------
# (a) Did the package actually install and the command run?
INSTALL_OK=1
"$VPY" -c 'import council.cli' >/dev/null 2>&1 || { INSTALL_OK=0; warn "package import failed (council.cli)"; }
if [ -x "$COUNCIL" ]; then
    "$COUNCIL" --help >/dev/null 2>&1 || { INSTALL_OK=0; warn "console-script did not run (council --help)"; }
else
    "$VPY" -m council.cli --help >/dev/null 2>&1 || { INSTALL_OK=0; warn "module entry did not run (python -m council.cli --help)"; }
fi
# The verdict claims "konsey and council are installed", so PROVE konsey too (its
# link_script failure was deliberately non-fatal — don't let a broken alias slip through).
KONSEY_BIN="$VENV_DIR/bin/konsey"
if [ -x "$KONSEY_BIN" ]; then
    "$KONSEY_BIN" --help >/dev/null 2>&1 || { INSTALL_OK=0; warn "console-script did not run (konsey --help)"; }
else
    INSTALL_OK=0; warn "konsey console-script missing in venv ($KONSEY_BIN)"
fi

# (b) Are the commands reachable as names? (prepend BIN_DIR so it resolves this run.)
REACH=1
for c in konsey council; do
    PATH="$BIN_DIR:$PATH" command -v "$c" >/dev/null 2>&1 || { REACH=0; warn "not yet reachable as a command: $c"; }
done

# (c) doctor is an ADVISORY health report — its exit code NEVER gates install success.
say "-- council doctor (advisory health report; does not gate install)"
DOCTOR_RC=0
# shellcheck disable=SC2086
$RUN_COUNCIL doctor || DOCTOR_RC=$?

# (d) the verdict
if [ "$INSTALL_OK" -eq 0 ]; then
    die "Install FAILED: the package did not import or the command did not run (see the !! lines above). Re-run ./install.sh after fixing."
fi
say ""
say "== Install complete. konsey and council are installed. =="
if [ "$REACH" -eq 1 ] && [ "$BIN_ON_PATH" -eq 1 ]; then
    say "Try:  konsey doctor"
elif [ "$REACH" -eq 1 ]; then
    say "Open a new shell (or run the export above), then:  konsey doctor"
    say "Right now you can call it directly:  $VENV_DIR/bin/konsey doctor"
else
    warn "Console-scripts are not reachable via $BIN_DIR. Fallback — activate the venv:"
    say  "    . \"$VENV_DIR/bin/activate\"   # then: konsey doctor"
fi
if [ "$DOCTOR_RC" -ne 0 ]; then
    warn "doctor reported a health item (this is NOT an install failure):"
    say  "    - if it says 0 providers: install a provider CLI (claude / codex / gemini), then: $RUN_COUNCIL doctor"
    say  "    - if you used --no-init: run $RUN_COUNCIL init first"
else
    say "doctor: health checks passed (see the report above for advisory vs full mode)."
fi
