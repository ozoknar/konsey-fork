"""Secret-scan gate tests (Constitution Article 4.2) — fail-safe, generic FORMAT
signatures only, brand-independent.

A known ``sk-ant-...`` style token MUST be caught; obvious placeholders
(``your_...``, ``${...}``, ``xxxx``, ``example``, ``process.env.*``) MUST be skipped
so the gate does not cry wolf on docs/examples. Secrets are scanned on EVERY channel
(prompt AND project_hint), per Md.4.2.

Runs against the REAL ``council.gateway``.
"""
from __future__ import annotations

import pytest

from council.gateway import preflight, scan_secrets

# Synthetic, NON-real token material (pattern fixtures, never live credentials).
FAKE_ANTHROPIC = "sk-ant-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FAKE_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
FAKE_GH_PAT = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"
FAKE_OPENAI = "sk-proj-" + "abcdefghij0123456789ABCDEFGHIJ"
FAKE_STRIPE = "sk_live_" + "abcdefghij0123456789ABCD"
FAKE_BEARER = "Bearer " + "abcdefghijklmnopqrstuvwxyz123456"
# header.payload.signature — each segment ≥ 8 chars after the eyJ prefix (regex shape).
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.S1g3K9d2Lm4N5p6Q7r8"


def test_anthropic_format_token_is_caught():
    found = scan_secrets(f"here is my key {FAKE_ANTHROPIC} do not leak it")
    assert found, "an sk-ant-* format token must be detected"
    assert "anthropic" in found


@pytest.mark.parametrize("blob,why", [
    (f"AWS access key {FAKE_AWS}", "aws"),
    (f"github token {FAKE_GH_PAT}", "github pat"),
    (f"openai key {FAKE_OPENAI}", "openai project key"),
    (f"stripe {FAKE_STRIPE}", "stripe live key"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----", "private key"),
    (f"Authorization: {FAKE_BEARER}", "bearer"),
    (f"token {FAKE_JWT}", "jwt"),
    ('api_key = "Ab12Cd34Ef56Gh78"', "secret_kv"),
])
def test_multiple_secret_formats_are_caught(blob, why):
    assert scan_secrets(blob), f"expected a secret ({why}) in: {blob[:40]!r}"


@pytest.mark.parametrize("placeholder", [
    "API_KEY=your_api_key_here",
    "token: ${SECRET_TOKEN}",
    "password = xxxxxxxxxxxx",
    "client_secret = <example>",
    "api_key = placeholder",
    "secret = process.env.SECRET",
    "key = import.meta.env.VITE_KEY",
    "Refactor the auth module and add tests.",        # no secret at all
    "Summarize the architecture docs.",
    "",
])
def test_placeholders_and_clean_text_are_not_flagged(placeholder):
    assert scan_secrets(placeholder) == [], (
        f"placeholder/clean text must not be flagged: {placeholder!r}"
    )


def test_scan_handles_empty_without_raising():
    assert scan_secrets("") == []


def test_preflight_scans_project_hint_channel_too():
    # Md.4.2: project_hint is also sent to the model, so it is scanned as well.
    res = preflight("a perfectly innocent task", project_hint=FAKE_ANTHROPIC)
    assert res.secrets_found, "a secret in project_hint must be detected"
    assert res.blocked is True


def test_preflight_clean_task_is_not_blocked_by_secrets():
    res = preflight("Summarize the architecture docs", project_hint="docs/site")
    assert res.secrets_found == []
