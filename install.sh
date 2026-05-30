#!/usr/bin/env sh
# Konsey installer — POSIX, idempotent, sudo-free (Constitution Article 0 & 19.4).
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

# --- UX kit + crash-resistance (S3) -------------------------------------------
# Capability is detected ONCE (detect_ui, after arg parsing). Until then these honest
# defaults keep every helper PLAIN, so a die() during arg parsing prints clean ASCII
# instead of tripping `set -u`. Pretty output is a pure ADDITION over plain text —
# it degrades to today's exact output on a dumb terminal / pipe / CI / NO_COLOR.
UI_COLOR=0; UI_UNICODE=0; UI_TTY=0; UI_WIDTH=80; SLEEP_TICK=1

# crash-resistance state (consumed by the EXIT/INT/TERM traps)
FAIL_REASON=""          # set by die(); empty => no specific message was shown
CURRENT_STEP="starting up"
PARTIAL_VENV=0          # 1 ONLY while creating a FRESH venv this run (scoped cleanup)

_ui_derive() {          # (re)build the palette + glyphs from the UI_* flags
    if [ "$UI_COLOR" -eq 1 ]; then
        C_RESET=$(printf '\033[0m'); C_BOLD=$(printf '\033[1m'); C_DIM=$(printf '\033[2m')
        C_RED=$(printf '\033[31m');  C_GRN=$(printf '\033[32m'); C_YEL=$(printf '\033[33m')
        C_CYN=$(printf '\033[36m')
    else
        C_RESET=; C_BOLD=; C_DIM=; C_RED=; C_GRN=; C_YEL=; C_CYN=
    fi
    if [ "$UI_UNICODE" -eq 1 ]; then
        G_OK='✔'; G_WARN='▲'; G_ERR='✖'; G_STEP='›'
    else
        G_OK='[OK]'; G_WARN='!!'; G_ERR='xx'; G_STEP='--'
    fi
}
_ui_derive              # plain defaults until detect_ui runs

say()  { printf '%s\n' "$*"; }
ok()   { printf '%s%s%s %s\n' "$C_GRN" "$G_OK" "$C_RESET" "$*"; }
warn() { printf '%s%s %s%s\n' "$C_YEL" "$G_WARN" "$*" "$C_RESET" >&2; }
# die() prints its (possibly multi-line) message AND records the stage; the EXIT trap
# then adds a short summary box pointing back at it — it never re-wraps the detail.
die()  { FAIL_REASON="$*"; printf '%s%s %s%s\n' "$C_RED" "$G_ERR" "$*" "$C_RESET" >&2; exit 1; }

STEP_TOTAL=6; STEP_NO=0
step() {  # step "Title" — numbered [n/N] header; also records the stage for the trap
    STEP_NO=$((STEP_NO + 1))
    CURRENT_STEP="$*"
    printf '\n%s%s[%d/%d]%s %s%s%s\n' \
        "$C_BOLD" "$C_CYN" "$STEP_NO" "$STEP_TOTAL" "$C_RESET" "$C_BOLD" "$*" "$C_RESET"
}

# run_step "Title" -- cmd args...   — a long step with live feedback (spinner on a
# TTY, a plain "... OK/xx" line otherwise). The wrapped command's REAL output is
# captured and SURFACED on failure (indented to stderr) — never hidden behind the UI.
run_step() {
    _rs_title=$1; shift
    [ "${1:-}" = "--" ] && shift
    _rs_log=$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/konsey_step.$$")
    if [ "$UI_TTY" -ne 1 ]; then
        printf '   %s %s ... ' "$G_STEP" "$_rs_title"
        if "$@" >"$_rs_log" 2>&1; then printf '%s\n' "$G_OK"; rm -f "$_rs_log"; return 0; fi
        printf '%s\n' "$G_ERR"; sed 's/^/     /' "$_rs_log" >&2; rm -f "$_rs_log"; return 1
    fi
    "$@" >"$_rs_log" 2>&1 &
    _rs_pid=$!
    _rs_frames="|/-\\"                # ASCII frames (\\ → one literal \); single-byte so cut -c is safe
    printf '%s' "$C_DIM"
    while kill -0 "$_rs_pid" 2>/dev/null; do
        _rs_i=1
        while [ "$_rs_i" -le 4 ]; do
            _rs_f=$(printf '%s' "$_rs_frames" | cut -c "$_rs_i")
            printf '\r   %s %s ' "$_rs_f" "$_rs_title"
            _rs_i=$((_rs_i + 1))
            sleep "$SLEEP_TICK" 2>/dev/null || sleep 1
            kill -0 "$_rs_pid" 2>/dev/null || break
        done
    done
    if wait "$_rs_pid"; then _rs_rc=0; else _rs_rc=$?; fi
    printf '\r%s' "$C_RESET"
    if [ "$_rs_rc" -eq 0 ]; then
        printf '\r   %s%s%s %s\n' "$C_GRN" "$G_OK" "$C_RESET" "$_rs_title"; rm -f "$_rs_log"; return 0
    fi
    printf '\r   %s%s%s %s\n' "$C_RED" "$G_ERR" "$C_RESET" "$_rs_title"
    sed 's/^/     /' "$_rs_log" >&2; rm -f "$_rs_log"; return "$_rs_rc"
}

box() {  # box ok|warn|err  line...   — bordered panel; unicode box-draw → ASCII fallback
    case "$1" in ok) _bx_c=$C_GRN ;; warn) _bx_c=$C_YEL ;; *) _bx_c=$C_RED ;; esac
    shift
    if [ "$UI_UNICODE" -eq 1 ]; then _bx_tl='╭'; _bx_tr='╮'; _bx_bl='╰'; _bx_br='╯'; _bx_h='─'; _bx_v='│'
    else _bx_tl='+'; _bx_tr='+'; _bx_bl='+'; _bx_br='+'; _bx_h='-'; _bx_v='|'; fi
    _bx_w=$UI_WIDTH; [ "$_bx_w" -gt 72 ] && _bx_w=72
    _bx_rule=""; _bx_i=2
    while [ "$_bx_i" -lt "$_bx_w" ]; do _bx_rule="$_bx_rule$_bx_h"; _bx_i=$((_bx_i + 1)); done
    printf '%s%s%s%s%s\n' "$_bx_c" "$_bx_tl" "$_bx_rule" "$_bx_tr" "$C_RESET"
    for _bx_ln in "$@"; do printf '%s%s%s %s\n' "$_bx_c" "$_bx_v" "$C_RESET" "$_bx_ln"; done
    printf '%s%s%s%s%s\n' "$_bx_c" "$_bx_bl" "$_bx_rule" "$_bx_br" "$C_RESET"
}

# --- crash-resistance traps (POSIX EXIT + explicit INT/TERM; NOT the bash-only ---
# `trap ERR` / `set -o pipefail`). Guarantees a friendly, actionable summary +
# SCOPED, idempotent cleanup on ANY non-zero exit or Ctrl-C — never on success.
on_exit() {
    _ex_rc=$?
    trap - EXIT
    [ "$_ex_rc" -eq 0 ] && exit 0          # success: the trap is silent
    # remove ONLY a venv we were mid-creating THIS run (never a reused/complete one)
    if [ "$PARTIAL_VENV" -eq 1 ] && [ -n "${VENV_DIR:-}" ] && [ -d "$VENV_DIR" ]; then
        rm -rf "$VENV_DIR" 2>/dev/null || true
    fi
    printf '\n' >&2
    if [ -n "$FAIL_REASON" ]; then
        box err "${C_BOLD}Install did not complete.${C_RESET}" \
                "Stage : $CURRENT_STEP" \
                "Detail: see the message(s) above." \
                "Next  : fix it, then re-run ./install.sh — safe to run again (idempotent)." >&2
    else
        box err "${C_BOLD}Install did not complete.${C_RESET}" \
                "Stage : $CURRENT_STEP" \
                "Reason: unexpected error (no specific message captured)." \
                "Next  : re-run ./install.sh (idempotent), or ./install.sh --help." >&2
    fi
    exit "$_ex_rc"
}
trap on_exit EXIT

on_sig() {  # $1 = INT|TERM : narrate, scoped cleanup, then RE-RAISE (default disposition)
    trap - INT TERM EXIT
    warn "interrupted ($1) during: $CURRENT_STEP"
    if [ "$PARTIAL_VENV" -eq 1 ] && [ -n "${VENV_DIR:-}" ] && [ -d "$VENV_DIR" ]; then
        rm -rf "$VENV_DIR" 2>/dev/null || true
    fi
    kill -s "$1" $$          # re-raise so the shell reports the conventional 130/143
}
trap 'on_sig INT'  INT
trap 'on_sig TERM' TERM

# --- capability detection (run ONCE; sets UI_* then re-derives the palette) ----
detect_ui() {
    [ -t 1 ] && UI_TTY=1
    # CI systems are non-interactive even when they allocate a TTY — their logs capture
    # \r spinner frames as noise. Treat CI as non-TTY (animation OFF, auto-color OFF);
    # FORCE_COLOR still opts color back in below, NO_COLOR still vetoes.
    [ -n "${CI:-}" ] && UI_TTY=0
    if [ -n "${NO_COLOR:-}" ]; then UI_COLOR=0                 # NO_COLOR is an absolute veto
    elif [ -n "${FORCE_COLOR:-}" ] || [ -n "${CLICOLOR_FORCE:-}" ]; then UI_COLOR=1
    elif [ "$UI_TTY" -eq 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
        if command -v tput >/dev/null 2>&1; then
            _ui_colors=$(tput colors 2>/dev/null || echo 0)
            case "$_ui_colors" in *[!0-9]*|'') _ui_colors=0 ;; esac
            [ "$_ui_colors" -ge 8 ] && UI_COLOR=1
        else
            case "$TERM" in
                xterm*|rxvt*|urxvt*|screen*|tmux*|vt100|vt220|linux|ansi|*color*) UI_COLOR=1 ;;
            esac
        fi
    fi
    case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
        *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) [ "$UI_TTY" -eq 1 ] && UI_UNICODE=1 ;;
    esac
    if [ "$UI_TTY" -eq 1 ]; then
        if [ -n "${COLUMNS:-}" ]; then _ui_w=$COLUMNS
        elif command -v tput >/dev/null 2>&1 && _ui_w=$(tput cols 2>/dev/null); then :
        elif command -v stty >/dev/null 2>&1 && _ui_w=$(stty size 2>/dev/null | cut -d' ' -f2); then :
        else _ui_w=80; fi
        case "$_ui_w" in *[!0-9]*|'') _ui_w=80 ;; esac
        [ "$_ui_w" -ge 20 ] && UI_WIDTH=$_ui_w
    fi
    [ -n "${KONSEY_NO_UI:-}" ] && { UI_COLOR=0; UI_UNICODE=0; }   # explicit plain escape hatch
    if sleep 0.1 2>/dev/null; then SLEEP_TICK=0.1; else SLEEP_TICK=1; fi
    _ui_derive
}

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

# Detect terminal capabilities now that args are parsed (KONSEY_NO_UI honored).
detect_ui

# --- UX self-test hook (testing only; never part of a real install) -----------
# `KONSEY_UI_SELFTEST=1 sh install.sh` prints the detected capability state + a
# sample of each UX primitive, then exits WITHOUT installing. `=die` exercises the
# failure trap. This is how CI proves the kit degrades correctly across a TTY/
# NO_COLOR/FORCE_COLOR/locale matrix without running a real install.
if [ -n "${KONSEY_UI_SELFTEST:-}" ]; then
    printf 'UI_COLOR=%s UI_UNICODE=%s UI_TTY=%s UI_WIDTH=%s\n' \
        "$UI_COLOR" "$UI_UNICODE" "$UI_TTY" "$UI_WIDTH"
    case "$KONSEY_UI_SELFTEST" in
        die) CURRENT_STEP="selftest stage"; die "selftest forced failure" ;;
        *)   step "selftest step"; ok "ok line"; warn "warn line"; box ok "summary line"; exit 0 ;;
    esac
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
say "== Konsey installer =="
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
step "Preflight — OS & toolchain"
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

step "Python — locate an interpreter >= 3.12"
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
step "Virtualenv — isolated .venv (never touches system Python)"
if [ ! -x "$VENV_DIR/bin/python" ]; then
    say "-- creating virtualenv: $VENV_DIR"
    PARTIAL_VENV=1                       # a half-built venv here is OURS to clean on failure
    if ! "$PY" -m venv "$VENV_DIR"; then
        if [ "$PLATFORM" = "macos" ]; then
            die "venv creation failed. Reinstall Python 3.12 (Homebrew/uv), then re-run:
       brew install python@3.12 && ./install.sh --python \"\$(brew --prefix python@3.12)/bin/python3.12\""
        else
            die "venv creation failed (is the venv module installed?):
       sudo apt-get install -y python3.12-venv   # Debian/Ubuntu"
        fi
    fi
    PARTIAL_VENV=0                       # venv is complete now — a later failure must NOT delete it
else
    say "-- reusing virtualenv: $VENV_DIR"
fi
VPY="$VENV_DIR/bin/python"
[ -x "$VPY" ] || die "virtualenv python missing at $VPY"

step "Dependencies — pinned requirements + editable package"
say "-- upgrading pip (quiet)"
"$VPY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || warn "pip upgrade skipped (offline?)"

# --- 4. pinned dependencies + package (editable, idempotent) ------------------
if [ -f "$REPO_ROOT/requirements.txt" ]; then
    run_step "Installing pinned dependencies" -- \
        "$VPY" -m pip install --quiet -r "$REPO_ROOT/requirements.txt" || die "dependency install failed"
fi
run_step "Installing konsey (editable)" -- \
    "$VPY" -m pip install --quiet -e "$REPO_ROOT" || die "package install failed"

step "Link & init — console-scripts on PATH + Bootstrap"
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
    say "-- konsey init (Article 0 Bootstrap)"
    if [ -n "$LOCALE" ]; then
        export KONSEY_LOCALE="$LOCALE"            # honored even in a piped (non-TTY) run
        INIT_FLAGS="$INIT_FLAGS --locale $LOCALE"
    fi
    # shellcheck disable=SC2086
    $RUN_COUNCIL init $INIT_FLAGS || warn "init reported a non-zero status; review above"
fi

step "Verify — install success vs provider health"
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
say "-- konsey doctor (advisory health report; does not gate install)"
DOCTOR_RC=0
# shellcheck disable=SC2086
$RUN_COUNCIL doctor || DOCTOR_RC=$?

# (d) the verdict — a FAIL routes through die() → the EXIT trap's red summary box.
if [ "$INSTALL_OK" -eq 0 ]; then
    die "the package did not import or the command did not run (see the warnings above)"
fi

# success path — a bordered summary panel (degrades to ASCII/plain off-TTY)
if [ "$REACH" -eq 1 ] && [ "$BIN_ON_PATH" -eq 1 ]; then
    _next="Try it:  konsey doctor"
elif [ "$REACH" -eq 1 ]; then
    _next="Open a new shell (or run the PATH export above), then:  konsey doctor"
else
    _next="Activate the venv:  . \"$VENV_DIR/bin/activate\"   # then: konsey doctor"
fi
say ""
box ok \
    "${C_BOLD}Install complete${C_RESET} — konsey and council are installed." \
    "$_next"
if [ "$DOCTOR_RC" -ne 0 ]; then
    warn "doctor flagged a health item (NOT an install failure):"
    say  "    - 0 providers? install a provider CLI (claude / codex / gemini), then: $RUN_COUNCIL doctor"
    say  "    - used --no-init? run $RUN_COUNCIL init first"
else
    ok "doctor: health checks passed (advisory vs full mode in the report above)."
fi
