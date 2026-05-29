<!--
Council PR template. Council's bar is evidence, not agreement (Article 2: evidence >
consensus). Fill in every section; an unchecked safety/leak box blocks merge.
-->

## What & why

<!-- One or two sentences: what does this change do, and why? Link any issue. -->

Closes #

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] New provider adapter (one config line / argv shape — NOT a new SDK dependency)
- [ ] New regulatory regime plugin (`regimes/*.toml` only — not in core)
- [ ] Docs / constitution (note the SemVer + header=body version rule, Article 18)
- [ ] Refactor / chore

## Evidence (required — Article 2.1 & 10.1)

> "Works on my machine" without output is not evidence. Paste the real terminal output.

```text
# e.g. pytest -q summary, ruff/mypy result, a reproduced exit code / HTTP status
```

- [ ] `pytest -q` run and **output pasted above** (no fake-green / mock-of-a-mock)
- [ ] `ruff check council tests` clean
- [ ] `mypy council` clean
- [ ] tests added/updated for the changed behavior (real imports, not mocks)

## Leak gate (required — Article 19.2; reviewer-enforced, gitleaks does NOT catch names)

- [ ] **No secret / key / token** in the diff or history (real or look-alive)
- [ ] **No real organization / product / person name** — placeholders only (`Acme Labs`, `${ORG}`)
- [ ] **No absolute home path** (`/Users/...`, `/home/...`, `C:\Users\...`)
- [ ] **No machine-specific value in a core module** — it belongs in `council.local` or as a `${variable}`
- [ ] No real / sensitive / patient data in tests, fixtures, or examples

## Immutable-core check (Article 18 — may tighten, never loosen)

- [ ] This PR does **not** weaken Article 2 (evidence/≥2 providers/CLI-only/producer≠verifier),
      Article 4 (PHI/PII/secret gate + endpoint block), Article 5 (approval gate invariant),
      Article 6.2 (EXECUTE safety boundary), Article 7 (confidence ceiling 0.6 / floor 0.7),
      or Article 11 (append-only audit)

## Vendor-neutrality check (if touching adapters/core)

- [ ] No SDK / HTTP-key dependency added to the adapter layer (CLI subprocess only, Article 2.3)
- [ ] No brand name hard-coded into a core module; roles stay generic and config-driven

## Reviewer notes

<!-- Anything a reviewer should focus on, known limitations, follow-ups. -->
