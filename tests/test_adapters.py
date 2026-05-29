"""Vendor-neutral adapter tests (Constitution Article 2.3).

Guarantees:
  * roster availability is evidence-based and PATH-augmented (config.available),
    reporting per-agent True/False without ever raising;
  * a missing CLI degrades GRACEFULLY: the adapter returns a non-ok result with a
    127 exit code instead of crashing the orchestrator (Md.3 fallback);
  * the adapter layer has NO SDK / HTTP-key dependency — CLI subprocess only.

Runs against the REAL ``council.adapters`` / ``council.config``.
"""
from __future__ import annotations

import inspect
import os


from council.adapters import (
    GenericCLIAdapter,
    available,
    build_registry,
)
from council.config import ROLE_LEAD, Config, RosterEntry

_MISSING = "definitely-not-a-real-cli-xyz-9999"


# --------------------------------------------------------------------------- #
# config.available / re-export.                                                 #
# --------------------------------------------------------------------------- #

def test_available_missing_cli_is_false_not_an_exception():
    c = Config(agents=[RosterEntry("ghost", _MISSING, ROLE_LEAD)])
    assert available(c) == {"ghost": False}


def test_available_empty_roster_is_empty_dict():
    assert available(Config(agents=[])) == {}


def test_available_uses_extra_path(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    exe = fake_bin / "stubcli"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin")  # exclude fake_bin from the base PATH
    c = Config(
        agents=[RosterEntry("planted", "stubcli", ROLE_LEAD)],
        extra_path=str(fake_bin) + os.pathsep + "/usr/bin",
    )
    assert available(c) == {"planted": True}


def test_available_disabled_agent_is_false():
    c = Config(agents=[RosterEntry("off", _MISSING, ROLE_LEAD, enabled=False)])
    assert available(c) == {"off": False}


# --------------------------------------------------------------------------- #
# Adapter layer — graceful degradation on a missing CLI.                        #
# --------------------------------------------------------------------------- #

def test_missing_cli_returns_non_ok_result_not_an_exception():
    ad = GenericCLIAdapter(name="ghost", cli=_MISSING, cfg=Config())
    res = ad.run("hello", timeout=5)
    assert res.ok is False
    assert res.exit_code == 127             # FileNotFoundError → 127, not a crash
    assert res.agent == "ghost"
    assert isinstance(res.evidence_hash, str) and res.evidence_hash


def test_real_cli_runs_and_reports_ok(tmp_path):
    # A planted stub that echoes confirms exit-0 + non-empty stdout → ok=True.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    exe = fake_bin / "echocli"
    exe.write_text('#!/bin/sh\necho "council ok"\n', encoding="utf-8")
    exe.chmod(0o755)
    cfg = Config(extra_path=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
    # Use a logical name with no special builtin profile → plain "{cli} -p {prompt}".
    ad = GenericCLIAdapter(name="echo", cli="echocli", cfg=cfg)
    res = ad.run("ping", timeout=10)
    assert res.ok is True
    assert res.exit_code == 0
    assert "council ok" in res.text


def test_build_registry_only_enabled_agents():
    cfg = Config(agents=[
        RosterEntry("a", _MISSING, ROLE_LEAD),
        RosterEntry("b", _MISSING, ROLE_LEAD, enabled=False),
    ])
    reg = build_registry(cfg)
    assert set(reg) == {"a"}                # disabled agent gets no adapter
    assert isinstance(reg["a"], GenericCLIAdapter)


def test_no_sdk_or_http_dependency_in_adapter_module():
    # Article 2.3: dependency is CLI subprocess ONLY — no requests/httpx/SDK imports.
    import council.adapters as mod

    src = inspect.getsource(mod)
    for forbidden in ("import requests", "import httpx", "from openai", "import openai",
                      "from anthropic", "import anthropic"):
        assert forbidden not in src, f"adapter must not depend on an SDK/HTTP client: {forbidden!r}"
