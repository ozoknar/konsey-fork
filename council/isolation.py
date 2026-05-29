"""Host AI-environment detection (Constitution Article 2.6 — Node Execution Isolation).

When the council shells out to a provider CLI (claude / codex / agy), that CLI loads
the **host machine's own AI configuration**: global instruction files (``CLAUDE.md``,
``AGENTS.md``, ``GEMINI.md``), settings / hooks, and MCP servers. Inherited into a
node, this host config

  (a) injects the *same machine's* instructions into every provider at once — which
      collapses the cross-provider independence that Article 2.2 requires (all nodes
      end up sharing one machine's biases / persona / doctrine), and
  (b) can break or block a run (a host hook intercepts a command, a slow/failing MCP
      server burns the node budget, a stray global directive rewrites the answer).

This module performs **detection only** — it reports the host AI-config footprint so
``council init`` can warn at install time and ``council doctor`` can surface it as
*evidence* (Article 2.1), not assumption. Enforcement (isolated argv / env allow-list /
clean CWD) lives in the adapter layer and is governed by the same article.

Pure + portable: callers pass ``home`` / ``cwd`` explicitly (this module never reads
``Path.home()`` or the environment during a scan), so the result is deterministic and
unit-testable, with no machine-specific path baked into the core (Article 2.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Stable provider ordering for summaries (logical roster names, not brand rules — the
# same generic names used by config roster / adapters). "all" = leaks into every node.
_NODE_ORDER: tuple[str, ...] = ("claude", "codex", "google", "all")


@dataclass(frozen=True)
class HostConfigFinding:
    """One pre-existing host AI-config artefact that would leak into a node subprocess.

    ``label``    human-readable description (e.g. "global Claude memory");
    ``path``     the file that actually exists on the host;
    ``pollutes`` which node it would leak into — a logical roster name or "all";
    ``kind``     "instructions" | "settings" | "mcp" | "hooks".
    """
    label: str
    path: Path
    pollutes: str
    kind: str


# Signatures resolved relative to the user's HOME — global, machine-wide AI config.
# (label, home-relative path, pollutes, kind)
_HOME_SIGNATURES: tuple[tuple[str, str, str, str], ...] = (
    ("global Claude memory", ".claude/CLAUDE.md", "claude", "instructions"),
    ("global Claude settings/hooks", ".claude/settings.json", "claude", "hooks"),
    ("global Codex instructions", ".codex/AGENTS.md", "codex", "instructions"),
    ("global Codex config", ".codex/config.toml", "codex", "settings"),
    ("global Gemini memory", ".gemini/GEMINI.md", "google", "instructions"),
    ("global Gemini settings", ".gemini/antigravity-cli/settings.json", "google", "settings"),
    ("global Gemini MCP config", ".gemini/antigravity-cli/mcp_config.json", "google", "mcp"),
)

# Signatures resolved relative to the CWD — project-local AI config that CLIs pick up by
# walking the working directory (and, for some, every parent up to the repo root).
# (label, cwd-relative path, pollutes, kind)
_CWD_SIGNATURES: tuple[tuple[str, str, str, str], ...] = (
    ("project Claude memory", "CLAUDE.md", "claude", "instructions"),
    ("project Claude settings/hooks", ".claude/settings.json", "claude", "hooks"),
    ("project Codex instructions", "AGENTS.md", "codex", "instructions"),
    ("project Gemini memory", "GEMINI.md", "google", "instructions"),
    ("project Cursor rules", ".cursorrules", "all", "instructions"),
)


def scan_host_ai_config(home: Path, cwd: Path) -> list[HostConfigFinding]:
    """Return the host AI-config files that exist and would leak into a node.

    Deterministic: only *regular files* that actually exist are reported (a directory
    or broken symlink named ``CLAUDE.md`` does not leak, so ``is_file`` — not
    ``exists`` — is the test). ``home`` and ``cwd`` are supplied by the caller (never
    read from the environment here) so the scan is unit-testable and carries no
    machine-specific assumption (Article 2.3).

    Project-level config is discovered by walking ``cwd`` **and every parent up to the
    filesystem root**, because provider CLIs traverse the working directory upward
    (verified: ``codex`` injects every ``AGENTS.md`` from the repo root down to the
    cwd). Findings are de-duplicated by *resolved* path, so a file reached both as a
    HOME signature and via the parent walk — or through two symlinks — is counted once.
    """
    findings: list[HostConfigFinding] = []
    seen: set[Path] = set()

    def _add(label: str, path: Path, pollutes: str, kind: str) -> None:
        try:
            if not path.is_file():   # follows symlinks; dir / broken-link → not a leak
                return
            key = path.resolve()
        except OSError:              # permission / symlink loop on hostile host fs → skip
            return
        if key in seen:
            return
        seen.add(key)
        findings.append(HostConfigFinding(label, path, pollutes, kind))

    # Global, HOME-level config.
    for label, rel, pollutes, kind in _HOME_SIGNATURES:
        _add(label, home / rel, pollutes, kind)
    # Project-level config: cwd + every ancestor (CLIs walk upward).
    for directory in (cwd, *cwd.parents):
        for label, rel, pollutes, kind in _CWD_SIGNATURES:
            _add(label, directory / rel, pollutes, kind)
    return findings


def summarize(findings: list[HostConfigFinding]) -> str:
    """A stable ``node:count`` summary, e.g. ``"claude:2 codex:1"`` (empty → "")."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.pollutes] = counts.get(f.pollutes, 0) + 1
    return " ".join(f"{n}:{counts[n]}" for n in _NODE_ORDER if n in counts)
