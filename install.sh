#!/usr/bin/env sh
# Council installer — POSIX, idempotent, sudo-free (Constitution Article 0 & 19.4).
#
#   ./install.sh [--quick] [--no-init] [--prefix DIR] [--python PY]
#
# What it does (download–inspect–run friendly: read it before piping):
#   1. Detect OS + Python (>=3.12 required; the proven-working floor).
#   2. Create an isolated virtualenv under the repo (.venv) — never touches system Python.
#   3. Install pinned dependencies from requirements.txt.
#   4. Install this package (editable) so the `council` console-script exists.
#   5. Run `council init` (Article 0 Bootstrap) unless --no-init, then `council doctor`.
#
# Nothing machine-specific is written by this script: all machine-facts are
# collected by `council init` into council.local.toml (git-ignored). No brand
# name, no organization, no absolute home path is embedded here.
set -eu

# --- locate the repo root (script-relative; no absolute path embedded) --------
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT="$SCRIPT_DIR"

# --- defaults / args ----------------------------------------------------------
DO_INIT=1
INIT_FLAGS=""
VENV_DIR="$REPO_ROOT/.venv"
PYTHON_BIN=""

usage() {
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --quick)     INIT_FLAGS="$INIT_FLAGS --quick" ;;
        --no-init)   DO_INIT=0 ;;
        --prefix)    shift; VENV_DIR="$1" ;;
        --python)    shift; PYTHON_BIN="$1" ;;
        -h|--help)   usage 0 ;;
        *)           echo "unknown argument: $1" >&2; usage 1 ;;
    esac
    shift
done

say()  { printf '%s\n' "$*"; }
warn() { printf '!! %s\n' "$*" >&2; }
die()  { printf 'xx %s\n' "$*" >&2; exit 1; }

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

# --- 2. find a Python >= 3.12 -------------------------------------------------
find_python() {
    if [ -n "$PYTHON_BIN" ]; then
        command -v "$PYTHON_BIN" >/dev/null 2>&1 && { echo "$PYTHON_BIN"; return 0; }
        die "requested --python '$PYTHON_BIN' not found on PATH"
    fi
    for cand in python3.13 python3.12 python3 python; do
        if command -v "$cand" >/dev/null 2>&1; then
            if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)' 2>/dev/null; then
                echo "$cand"; return 0
            fi
        fi
    done
    return 1
}

PY="$(find_python)" || die "Python >= 3.12 is required (proven-working floor) but none was found.
   Install Python 3.12+ and re-run, or pass --python /path/to/python3.12"
PYVER="$("$PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
say "   python   : $PY ($PYVER)"

# --- 3. isolated virtualenv (idempotent) --------------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
    say "-- creating virtualenv: $VENV_DIR"
    "$PY" -m venv "$VENV_DIR" || die "venv creation failed (is python3-venv installed?)"
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

# Resolve the console-script (prefer the venv one; fall back to module form).
COUNCIL="$VENV_DIR/bin/council"
if [ -x "$COUNCIL" ]; then
    RUN_COUNCIL="$COUNCIL"
else
    RUN_COUNCIL="$VPY -m council.cli"
fi
say "   council  : $RUN_COUNCIL"

# --- 5. Bootstrap (Article 0) + evidence-based health -------------------------
if [ "$DO_INIT" -eq 1 ]; then
    say "-- council init (Article 0 Bootstrap)"
    # shellcheck disable=SC2086
    $RUN_COUNCIL init $INIT_FLAGS || warn "init reported a non-zero status; review above"
fi

say "-- council doctor (evidence-based health check)"
# doctor exits 1 on a critical failure; surface it but do not abort the script,
# so the user sees the full report and the exact remediation lines.
# shellcheck disable=SC2086
if $RUN_COUNCIL doctor; then
    say ""
    say "== Install complete. =="
else
    say ""
    warn "doctor found critical issues — fix the lines marked above, then re-run: $RUN_COUNCIL doctor"
fi

say "Activate the environment with:  . \"$VENV_DIR/bin/activate\""
say "Or call directly:               $RUN_COUNCIL run \"your task\""
