# Changelog

All notable changes to persona-constitution-mcp. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
semantic versioning. Each release's section is what the release workflow
publishes as the release notes - a tag with no section here does not ship.

## [3.3.0] - 2026-08-20

The enterprise-hardening release: the version cannot drift, the trust
boundaries are bounded, two real denial-of-service defects found by the
new adversarial suite are fixed, and releases are now built once,
attested, and published from the same bytes.

### Fixed

- **Scanner hang on adversarial input (DoS).** The empty-catch rule's
  `/\*.*?\*/` scan was quadratic on unclosed `catch {/*` openers: an
  880 KB input - well under the admitted size - hung the scanner past
  measurable patience. The pattern is now bounded and unrolled with
  deterministic character classes; the same bomb scans in under a second,
  and the detection contract (bare, single-line-comment and
  multi-line-comment empty catches) is pinned by tests.
- **Scanner crash on CPython 3.12+ (DoS).** `ast.parse` raises
  `MemoryError` ("Parser stack overflowed") on pathologically deep
  expressions; all four parse sites caught only `(SyntaxError,
  ValueError)` and died. They now treat every parser refusal
  (`SyntaxError`, `ValueError`, `MemoryError`, `RecursionError`) the same
  way: not Python, degrade to the non-AST engines.
- Stale benchmark figures in code comments (the corpus is 37 cases:
  union 37/37 with the `ast` extra, 30/37 without).

### Added

- **Adversarial time-budget suite** (`tests/test_scan_budget.py`): six
  pathological payloads at admitted sizes must finish inside a hang-class
  budget; found both DoS defects above. Wall-clock checks self-disarm
  under a tracer, where timing is distortion rather than signal.
- **Input bounds at every trust boundary**: one stdio frame is capped
  (`MAX_MESSAGE_CHARS`, checked before parsing, transport survives),
  `review_patch` bounds its diff and files-map totals with instructions
  in the error, and the GitHub client rejects a missing token with
  `ValueError` (asserts are stripped under `python -O`).
- **Release pipeline** (`release.yml`): tag must match the declared
  version, full suite and benchmark run pre-build, artifacts are built
  once, provenance-attested, SBOM'd (CycloneDX), published as a GitHub
  Release with notes from this file, then to PyPI via OIDC trusted
  publishing - no stored tokens, and never rebuilt between steps.
- **CI depth**: macOS as a required check, Windows informational until it
  earns required status, and a first-party coverage floor (measured 87%,
  enforced at 86, ratchet only rises).
- Governance: `SECURITY.md` (resource-exhaustion inputs and detection
  bypasses are in-scope vulnerability classes here), `CONTRIBUTING.md`,
  `CODEOWNERS`, and Dependabot as the update feed for the now SHA-pinned
  actions supply chain (including the pin consumers inherit from
  `action.yml`).

### Changed

- **The version is declared once**, in `pyproject.toml`, and resolved at
  runtime through `persona_constitution/_version.py` (checkout wins over
  stale editable-install metadata; installed wheels use distribution
  metadata; a broken install refuses to start rather than guess). It was
  previously triplicated and had already drifted once.
- The `initialize` handshake echoes the client's `protocolVersion` only
  when this server actually implements it; unknown or malformed values
  are answered with the latest supported version instead of parroted.

## [3.2.0] - 2026-08-19

### Added

- Two-factor agentic PR review gate: the deterministic `review_patch`
  engine (diff parsing, changed-line attribution, C-03 test policy) plus
  the reviewing agent's judgement gates, shipped as a composite GitHub
  Action (`action.yml`) with fork-safe token handling, the
  `persona-pr-review` CLI, and the `.persona-review.json` shared policy.

### Fixed

- `tree-sitter-rust` pinned below 0.23.3, which ships grammar ABI 15 and
  is rejected by py-tree-sitter 0.23.x at load time.

## [3.1.0] - 2026-08-09

### Added

- CI (lint at a pinned ruff, tests on the 3.9 floor and 3.14 ceiling,
  both scanner configurations, packaging job that installs the built
  wheel in a clean venv and drives the console script over stdio).
- MIT license.

### Changed

- The constitution ships inside the package (`persona_constitution/data/`),
  so `pip install` produces a self-contained working server; the pre-3.1
  `<project root>/data` layout remains honoured as a fallback.

## [3.0.0] - 2026-08-09

### Added

- Initial public server: the constitution corpus with section/KA/rule
  tools over MCP stdio (newline-delimited JSON-RPC 2.0, stdlib only),
  and `scan_code_for_violations` backed by the vendored CodebaseCSI
  structural detector, the constitution prose rules, Python stdlib-AST
  analysis, and the optional tree-sitter engine tier.
- Scanner accuracy benchmark with an environment-aware regression
  baseline (`tools/benchmark_scanner.py`).

[3.3.0]: https://github.com/QuantmindSSI/CTO-MCP/compare/v3.2.0...v3.3.0
[3.2.0]: https://github.com/QuantmindSSI/CTO-MCP/compare/4d43eb0...v3.2.0
[3.1.0]: https://github.com/QuantmindSSI/CTO-MCP/compare/5c0160e...4d43eb0
[3.0.0]: https://github.com/QuantmindSSI/CTO-MCP/commits/5c0160e
