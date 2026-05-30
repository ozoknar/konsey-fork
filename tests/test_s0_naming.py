"""S0 — `konsey` is now the CANONICAL command; `council` is a kept-working but
DEPRECATED alias.

Evidence > consensus: these lock the owner-confirmed S0 contract against the real
pyproject, the real config/env resolution, the real capture/secrets env lookups,
and the real `_maybe_deprecation_notice`. Scope is deliberately USER-FACING only —
the internal package dir (`council/`), config filename (`council.local.toml`),
DuckDB tables and `cfg.council_home` are intentionally NOT renamed here (high-churn
+ live-user-data migration), so the backward-compat assertions below must keep
passing: every `COUNCIL_*` env var still works, it is merely no longer preferred.
"""
from __future__ import annotations

import io
import sys
import tomllib
from pathlib import Path

from council import capture, cli, config
from council import i18n
from council.config import Config
from council.platform.secrets import EnvFileStore

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# (1) console scripts — konsey is primary, council is a working alias          #
# --------------------------------------------------------------------------- #

def test_pyproject_konsey_is_canonical_council_is_alias():
    raw = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    data = tomllib.loads(raw)
    scripts = data["project"]["scripts"]
    # both still map to the same entry point (council stays fully working)
    assert scripts.get("konsey") == "council.cli:main"
    assert scripts.get("council") == "council.cli:main"
    # canonical = listed FIRST in the source (konsey before council)
    konsey_at = raw.index('konsey = "council.cli:main"')
    council_at = raw.index('council = "council.cli:main"')
    assert konsey_at < council_at, "konsey must be declared before council (canonical first)"


# --------------------------------------------------------------------------- #
# (2) prog name now falls back to konsey for `python -m` / tests               #
# --------------------------------------------------------------------------- #

def test_prog_name_falls_back_to_konsey(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/usr/bin/python3", "-m", "council.cli"])
    assert cli._prog_name() == "konsey"          # was "council" before S0
    monkeypatch.setattr(sys, "argv", ["council", "doctor"])
    assert cli._prog_name() == "council"         # still reflects an explicit council invocation
    monkeypatch.setattr(sys, "argv", ["konsey"])
    assert cli._prog_name() == "konsey"


# --------------------------------------------------------------------------- #
# (3) KONSEY_* env vars are preferred; COUNCIL_* still works (backward compat) #
# --------------------------------------------------------------------------- #

def test_konsey_home_preferred_but_council_home_still_works(monkeypatch, tmp_path):
    k, c = tmp_path / "k", tmp_path / "c"
    k.mkdir()
    c.mkdir()
    monkeypatch.setenv("KONSEY_HOME", str(k))
    monkeypatch.setenv("COUNCIL_HOME", str(c))
    assert config._default_council_home() == k.resolve()      # KONSEY_HOME wins
    monkeypatch.delenv("KONSEY_HOME", raising=False)
    assert config._default_council_home() == c.resolve()      # COUNCIL_HOME still honored


def test_konsey_config_preferred_but_council_config_still_works(monkeypatch, tmp_path):
    a = tmp_path / "a.toml"
    a.write_text('owner = "from_konsey"\n', encoding="utf-8")
    b = tmp_path / "b.toml"
    b.write_text('owner = "from_council"\n', encoding="utf-8")
    monkeypatch.delenv("COUNCIL_HOME", raising=False)
    monkeypatch.setenv("KONSEY_CONFIG", str(a))
    monkeypatch.setenv("COUNCIL_CONFIG", str(b))
    assert config.load_config().owner == "from_konsey"        # KONSEY_CONFIG wins
    monkeypatch.delenv("KONSEY_CONFIG", raising=False)
    assert config.load_config().owner == "from_council"       # COUNCIL_CONFIG still honored


def test_konsey_regime_file_preferred_but_council_still_works(monkeypatch, tmp_path):
    kf = tmp_path / "k.toml"
    kf.write_text('regime = "x"\n', encoding="utf-8")
    cf = tmp_path / "c.toml"
    cf.write_text('regime = "x"\n', encoding="utf-8")
    cfg = Config(data_regime="hipaa")        # any regulated regime triggers the override lookup
    monkeypatch.setenv("KONSEY_REGIME_FILE", str(kf))
    monkeypatch.setenv("COUNCIL_REGIME_FILE", str(cf))
    assert capture._regime_plugin_path(cfg) == kf             # KONSEY_REGIME_FILE wins
    monkeypatch.delenv("KONSEY_REGIME_FILE", raising=False)
    assert capture._regime_plugin_path(cfg) == cf             # COUNCIL_REGIME_FILE still honored


def test_konsey_secrets_file_preferred_but_council_still_works(monkeypatch, tmp_path):
    kf, cf = tmp_path / "k.env", tmp_path / "c.env"
    monkeypatch.setenv("KONSEY_SECRETS_FILE", str(kf))
    monkeypatch.setenv("COUNCIL_SECRETS_FILE", str(cf))
    assert EnvFileStore()._path == kf                         # KONSEY_SECRETS_FILE wins
    monkeypatch.delenv("KONSEY_SECRETS_FILE", raising=False)
    assert EnvFileStore()._path == cf                         # COUNCIL_SECRETS_FILE still honored


# --------------------------------------------------------------------------- #
# (4) deprecation notice — fires ONLY for `council` on a TTY, silent otherwise #
# --------------------------------------------------------------------------- #

def _run_notice(monkeypatch, tmp_path, *, argv0, tty):
    """Invoke _maybe_deprecation_notice with a controlled argv0 + a fake-TTY stderr,
    isolated from any real council.local.toml, and return whatever hit stderr."""
    monkeypatch.setenv("COUNCIL_HOME", str(tmp_path))            # no profile here → defaults
    monkeypatch.setenv("COUNCIL_DATA_HOME", str(tmp_path / "d"))
    for v in ("KONSEY_CONFIG", "COUNCIL_CONFIG", "KONSEY_HOME"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(sys, "argv", [argv0, "doctor"])
    buf = io.StringIO()
    buf.isatty = lambda: tty            # type: ignore[method-assign]
    monkeypatch.setattr(sys, "stderr", buf)
    cli._maybe_deprecation_notice()
    return buf.getvalue()


def test_deprecation_notice_fires_for_council_on_tty(monkeypatch, tmp_path):
    out = _run_notice(monkeypatch, tmp_path, argv0="council", tty=True)
    low = out.lower()
    # locale-robust: BOTH names appear in the en AND tr notice text
    assert "konsey" in low and "council" in low
    assert out.strip(), "a council-on-TTY invocation must print a one-line notice"


def test_deprecation_notice_silent_for_konsey(monkeypatch, tmp_path):
    assert _run_notice(monkeypatch, tmp_path, argv0="konsey", tty=True) == ""


def test_deprecation_notice_silent_when_not_a_tty(monkeypatch, tmp_path):
    # piped/scripted council (e.g. install-time probes, CI) must stay quiet
    assert _run_notice(monkeypatch, tmp_path, argv0="council", tty=False) == ""


def test_deprecation_notice_silent_for_module_invocation(monkeypatch, tmp_path):
    # `python -m council.cli` → argv0 is the interpreter path, not "council" → silent
    assert _run_notice(monkeypatch, tmp_path, argv0="/usr/bin/python3", tty=True) == ""


# --------------------------------------------------------------------------- #
# (5) the new catalog key exists with en/tr parity                            #
# --------------------------------------------------------------------------- #

def test_council_deprecated_key_has_en_tr_parity():
    en = i18n.load_catalog("en")
    tr = i18n.load_catalog("tr")
    assert "cli.council_deprecated" in en
    assert "cli.council_deprecated" in tr
    # both mention konsey as the way forward
    assert "konsey" in en["cli.council_deprecated"].lower()
    assert "konsey" in tr["cli.council_deprecated"].lower()
