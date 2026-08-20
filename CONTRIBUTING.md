# Contributing

This repository ships the gate it is judged by. Every change passes the
same Zero-Framework-Tolerance review the server performs for others, plus
the checks below. The bar is the constitution in
`persona_constitution/data/CONSTITUTION.md`; the short version: complete,
executable, correct - no placeholders, no stubs, no "left as an exercise".

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[ast,dev]"
```

The `ast` extra installs the pinned tree-sitter matrix (see the rationale
comments in `pyproject.toml` before touching those pins). Without it the
scanner still works with the stdlib engines - both configurations are
supported and both are tested in CI.

## Before you push

All of these must pass; CI runs exactly these:

```bash
.venv/bin/python -m unittest discover -s tests   # the suite (3.9 floor and 3.14 in CI)
.venv/bin/python tools/benchmark_scanner.py      # detection-rate regression gate
.venv/bin/ruff check .                           # lint, pinned version
.venv/bin/ruff format --check .                  # formatting
```

Rules that are enforced, so you may as well know them up front:

- **Tests ship with the change.** New behaviour without a test does not
  land (C-03). Bug fixes ship the test that would have caught the bug.
- **Coverage only rises.** CI enforces a floor on first-party coverage;
  if your change raises the measured number meaningfully, raise the floor
  in `.github/workflows/ci.yml` in the same PR. Never lower it.
- **Benchmark numbers are measured, not edited.** If you touch detection
  logic, rerun `tools/benchmark_scanner.py` and update any figures quoted
  in comments alongside the code that produced them.
- **Bounds are part of the contract.** Input caps, retry limits, and time
  budgets exist deliberately (`tests/test_scan_budget.py`,
  `tests/test_hardening.py`). If a change needs a bound moved, move it
  explicitly and say why in the commit message.
- **Vendored code stays vendored.** `codebase_csi/` is kept in upstream
  style for clean future syncs (provenance in `codebase_csi/VENDORED.md`);
  it is outside the lint regime and outside coverage. Fix upstream-worthy
  defects there in minimal diffs.
- **Actions stay SHA-pinned.** New workflow steps use full commit SHAs
  with the tag in a trailing comment. Dependabot maintains them.

## Commit style

Imperative summary line; a body that argues the change - what was wrong,
what is now true, and how that is known (measurements beat adjectives).
The existing `git log` is the style guide.

## Releasing

1. Bump `version` in `pyproject.toml` (the single declaration point - the
   handshake, `__version__`, and the wheel all derive from it).
2. Add the section to `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD`.
   The release workflow refuses to ship a tag with no changelog section.
3. Commit, then tag and push:

   ```bash
   git tag -a vX.Y.Z -m "persona-constitution-mcp X.Y.Z: <one line>"
   git push origin main --follow-tags
   ```

4. The `Release` workflow builds once, runs the full suite and benchmark,
   attests provenance for the exact artifacts, generates a CycloneDX
   SBOM, and creates the GitHub Release with notes extracted from the
   changelog. The tag must match the declared version or the build
   refuses.

### PyPI (one-time setup)

`publish-pypi` uses OIDC trusted publishing - no stored API tokens. It
fails cleanly until a maintainer registers the publisher on PyPI:
*Manage project → Publishing → Add a trusted publisher* with repository
`QuantmindSSI/CTO-MCP`, workflow `release.yml`, environment `pypi` - and
creates the `pypi` environment in the repository settings. The GitHub
Release and attestations do not depend on this job.

## Security

Vulnerability reports go through `SECURITY.md`, not the issue tracker.
Resource-exhaustion inputs and detection bypasses are security reports
here, not ordinary bugs.
