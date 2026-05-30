# Releasing `konsey-cli`

> **Status: PREPARE-only.** The infrastructure is in place (build, `twine check`, a
> gated release workflow, a Homebrew scaffold) but **nothing publishes automatically**.
> Every step below is a deliberate human action. Publishing to PyPI is **irreversible**
> (the `konsey-cli` name is claimed on first upload) and makes the project public —
> do not start until the owner has confirmed the repo is public-ready (patent review +
> the Apache-2.0 / CC-BY-4.0 dual-license check).

## What is already safe and automated (no publish)

The `build` job in `.github/workflows/release.yml` runs on PRs, manual dispatch, and
`v*` tags. It builds the sdist + wheel **from a clean checkout**, runs
`twine check --strict`, asserts no machine/doctrine file leaked into the sdist, and (on a
tag) asserts `council.__version__` equals the tag. It never uploads.

Local equivalent:

```bash
python -m build
twine check --strict dist/*
tar tzf dist/*.tar.gz | grep -E 'KONSEY_ANAYASASI|council.local.toml' && echo LEAK || echo clean
```

## A. One-time PyPI setup (Trusted Publisher — no API tokens, ever)

A "pending publisher" reserves **nothing** until the first successful publish.

1. On <https://pypi.org> → *Account settings* → *Publishing* → *Add a pending publisher*:
   - **PyPI Project Name:** `konsey-cli`
   - **Owner:** `eMediquality`  · **Repository:** `konsey`
   - **Workflow filename:** `release.yml`  · **Environment name:** `pypi-release`
2. (Optional dry-run) Repeat on <https://test.pypi.org> with environment `testpypi`.

## B. One-time GitHub setup

3. Repo *Settings → Environments* → create **`pypi-release`** (add required reviewers so a
   human must approve every upload).
4. In `.github/workflows/release.yml`, **uncomment** the
   `pypa/gh-action-pypi-publish@release/v1` step. **Never** add a `PYPI_TOKEN` secret —
   OIDC replaces it.

## C. Cut a release

5. Bump the version in **`council/__init__.py` only** (`pyproject.toml` is dynamic).
   Update `CHANGELOG.md`.
6. (Recommended) dry-run to TestPyPI first, then:
   `pipx install --index-url https://test.pypi.org/simple/ konsey-cli`.
7. `git tag vX.Y.Z && git push origin vX.Y.Z` — the `build` job runs and asserts
   `__version__ == tag`.
8. Approve the `pypi-release` environment → the upload runs via OIDC. **The name is
   claimed here, on the first publish.**
9. Create the GitHub Release for `vX.Y.Z` (the source tarball is attached automatically).

Recommended user install once live: `pipx install konsey-cli`.

## D. Homebrew (personal tap `eMediquality/homebrew-konsey`)

10. Get the tarball hash: `curl -sL <release-tarball-url> | shasum -a 256`.
11. In the tap's `Formula/konsey.rb` (copy from `packaging/konsey.rb`), fill `url` +
    `sha256`, then `brew update-python-resources Formula/konsey.rb` to generate the
    `resource` stanzas.
12. Verify: `brew install --build-from-source eMediquality/konsey/konsey`, then commit.

Move to homebrew-core only later, if the project gains a broad public user base.
