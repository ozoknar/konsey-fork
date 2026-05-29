"""Config bootstrap tests — the single injection point (Constitution Article 0 & 2.3).

These run against the REAL ``council.config`` module (no stub, no mock): the dataclass,
``by_role`` / ``verifier(exclude=...)``, ``load_config`` (TOML round-trip), and the
PATH-augmented ``available`` health probe. Evidence > consensus: every assertion is a
real call, not a description of intended behaviour.
"""
from __future__ import annotations

import textwrap


from council.config import (
    CONFIDENCE_CAP_NOXVAL,
    CONFIDENCE_FLOOR,
    KILL_TOOL_FAILURES,
    MAX_VERIFY_RETRIES,
    ROLE_DISTILLER,
    ROLE_LEAD,
    ROLE_VERIFIER,
    Config,
    ProjectEntry,
    RosterEntry,
    available,
    load_config,
)


# --------------------------------------------------------------------------- #
# Safe defaults (no profile present → never $USER, advisory single-agent mode) #
# --------------------------------------------------------------------------- #

def test_defaults_are_safe():
    c = load_config("/nonexistent/council.local.toml")
    assert c.owner == "operator"          # NEVER the machine username ($USER)
    assert c.org == ""
    assert c.node_name == ""
    assert c.locale == "en"
    assert c.data_regime == "standard"
    assert c.autocapture_enabled is False
    assert c.bridge_dir is None           # None → autocapture stays inert
    assert c.secret_backend == "null"
    assert c.scheduler == "null"
    assert c.notifier == "null"
    assert c.exec_sandbox == "off"
    assert c.agents == []
    assert c.projects == []


def test_module_thresholds_match_constitution():
    # Article 6/7/9 numeric invariants — wired as Config defaults, overridable.
    assert MAX_VERIFY_RETRIES == 2
    assert KILL_TOOL_FAILURES == 3
    assert CONFIDENCE_FLOOR == 0.7
    assert CONFIDENCE_CAP_NOXVAL == 0.6
    c = Config()
    assert c.max_verify_retries == MAX_VERIFY_RETRIES
    assert c.kill_tool_failures == KILL_TOOL_FAILURES
    assert c.confidence_floor == CONFIDENCE_FLOOR
    assert c.confidence_cap_noxval == CONFIDENCE_CAP_NOXVAL


def test_extra_path_keeps_homebrew_arm_default():
    # Critique §2: a Homebrew-installed CLI must not be silently missed.
    c = Config()
    assert "/opt/homebrew/bin" in c.extra_path


def test_path_helpers_are_xdg_derived():
    c = Config()
    assert c.db_path().name == "council.duckdb"
    assert c.db_path().parent == c.data_home
    assert c.config_path().name == "council.local.toml"
    assert c.config_path().parent == c.council_home
    assert c.logs_dir() == c.data_home / "logs"
    assert c.sessions_dir() == c.data_home / "sessions"
    assert c.locales_dir() == c.council_home / "council" / "locales"


# --------------------------------------------------------------------------- #
# by_role / verifier — kills the hard-coded ("claude","codex","google") tuple   #
# and the literal verifier="google" branch (graph.py:105/126/166).              #
# --------------------------------------------------------------------------- #

def _three_node() -> Config:
    return Config(agents=[
        RosterEntry("claude", "claude", ROLE_LEAD),
        RosterEntry("codex", "codex", "critic"),
        RosterEntry("google", "agy", ROLE_VERIFIER),
    ])


def test_by_role_returns_enabled_in_roster_order():
    c = Config(agents=[
        RosterEntry("a", "a", ROLE_LEAD),
        RosterEntry("b", "b", ROLE_LEAD, enabled=False),
        RosterEntry("c", "c", ROLE_LEAD),
        RosterEntry("d", "d", "critic"),
    ])
    assert c.by_role(ROLE_LEAD) == ["a", "c"]   # disabled "b" dropped; order preserved
    assert c.by_role("critic") == ["d"]
    assert c.by_role(ROLE_DISTILLER) == []


def test_verifier_prefers_verifier_role_and_excludes_producer():
    c = _three_node()
    # the verifier role exists and is not the producer → use it
    assert c.verifier(exclude="claude") == "google"
    assert c.verifier(exclude="codex") == "google"


def test_verifier_falls_back_when_role_holder_is_the_producer():
    # If the only verifier-role agent IS the producer, fall back to another enabled
    # agent (producer != verifier invariant, Article 2.4).
    c = _three_node()
    v = c.verifier(exclude="google")
    assert v is not None
    assert v != "google"


def test_verifier_none_in_single_agent_advisory_mode():
    c = Config(agents=[RosterEntry("solo", "solo", ROLE_LEAD)])
    # no second independent provider → None → advisory mode, confidence capped (Md.7.1)
    assert c.verifier(exclude="solo") is None


def test_disabled_agents_excluded_from_verifier():
    c = Config(agents=[
        RosterEntry("claude", "claude", ROLE_LEAD),
        RosterEntry("google", "agy", ROLE_VERIFIER, enabled=False),
    ])
    assert c.verifier(exclude="claude") is None   # disabled verifier cannot be picked


# --------------------------------------------------------------------------- #
# load_config — real TOML round-trip from a temp profile                         #
# --------------------------------------------------------------------------- #

def test_load_config_parses_real_toml(tmp_path):
    profile = tmp_path / "council.local.toml"
    profile.write_text(textwrap.dedent("""
        owner = "operator"
        org = "Acme Labs"
        node_name = "acme-dev-01"
        locale = "tr"
        data_regime = "kvkk"
        autocapture_enabled = false

        [[agents]]
        name = "claude"
        cli = "claude"
        role = "lead"

        [[agents]]
        name = "google"
        cli = "agy"
        role = "verifier"
        enabled = false

        [[projects]]
        match = "infra/*"
        risk = "production"
    """), encoding="utf-8")

    c = load_config(profile)
    assert c.owner == "operator"
    assert c.org == "Acme Labs"
    assert c.node_name == "acme-dev-01"
    assert c.locale == "tr"
    assert c.data_regime == "kvkk"
    assert c.by_role("lead") == ["claude"]
    assert c.by_role("verifier") == []           # disabled → not surfaced
    assert c.projects == [ProjectEntry(match="infra/*", risk="production")]


def test_load_config_malformed_toml_degrades_to_defaults(tmp_path):
    # Fail-open on *config* (the security gate fails CLOSED elsewhere, in gateway.py).
    bad = tmp_path / "council.local.toml"
    bad.write_text("this is = = not valid toml [[[", encoding="utf-8")
    c = load_config(bad)
    assert c.owner == "operator"
    assert c.agents == []


def test_load_config_env_var_resolution(tmp_path, monkeypatch):
    profile = tmp_path / "custom.toml"
    profile.write_text('owner = "operator"\norg = "Acme Labs"\n', encoding="utf-8")
    monkeypatch.setenv("COUNCIL_CONFIG", str(profile))
    c = load_config()                              # no explicit path → env var wins
    assert c.org == "Acme Labs"


# --------------------------------------------------------------------------- #
# available() — PATH-augmented per-agent health, graceful on missing CLI         #
# --------------------------------------------------------------------------- #

def test_available_reports_missing_cli_gracefully():
    c = Config(agents=[RosterEntry("ghost", "definitely-not-a-real-cli-xyz", ROLE_LEAD)])
    assert available(c) == {"ghost": False}       # missing CLI → False, never raises


def test_available_disabled_agent_is_false():
    c = Config(agents=[
        RosterEntry("on", "definitely-not-a-real-cli-xyz", ROLE_LEAD),
        RosterEntry("off", "definitely-not-a-real-cli-xyz", ROLE_LEAD, enabled=False),
    ])
    out = available(c)
    assert out == {"on": False, "off": False}


def test_available_finds_cli_on_augmented_path(tmp_path, monkeypatch):
    # Plant a fake executable in extra_path only; PATH itself does not contain it.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    exe = fake_bin / "fakecli"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin")        # deliberately exclude fake_bin
    import os
    c = Config(agents=[RosterEntry("planted", "fakecli", ROLE_LEAD)],
               extra_path=str(fake_bin) + os.pathsep + "/usr/bin")
    assert available(c) == {"planted": True}
