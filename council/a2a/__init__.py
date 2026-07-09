"""A2A (Agent2Agent, Google/Linux Foundation) — deliberately NOT implemented here.

Konsey orchestrates 3 LOCAL CLI subprocesses (claude/codex/agy) on one machine. A2A is
designed for networked, cross-org remote-agent delegation — HTTP/gRPC/JSON-RPC transport,
"Agent Card" discovery at a well-known URL, OAuth2/OIDC/mTLS auth — i.e. calling an
independently-hosted agent service. There is no remote service to discover or authenticate
to here, so a real A2A client/server would solve a problem konsey does not have.

If local-CLI-to-CLI orchestration is ever revisited, the Agent Client Protocol (ACP, Zed
Industries + JetBrains — a DIFFERENT, unrelated standard despite the shared "ACP" acronym
IBM once also used) is the better-fitting one: it is explicitly a client-drives-agent-CLI
model over JSON-RPC/stdio, and both Codex CLI and Gemini CLI already ship official ACP-agent
support. Claude Code has no native outbound ACP client (Anthropic closed
anthropics/claude-code#6686 as NOT_PLANNED), so the only practical bridge today is a
third-party headless ACP client (e.g. `acpx`) — which is alpha-stage. Adopting it as the
core call mechanism for the codex/agy nodes would trade a working (if unstructured)
subprocess call for an unproven dependency in the critical path — the same class of risk
this session already declined once for claude's own isolation (see KNOWN_ISSUES.md).

Decision (evidence-based architecture review, 2026-07): defer both A2A and ACP. Peers stay
empty by default (inert) until acpx matures out of alpha or Claude Code ships a native ACP
client. See KNOWN_ISSUES.md for the full evidence trail."""
