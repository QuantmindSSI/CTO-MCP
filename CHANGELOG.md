# Changelog

All notable changes to persona-constitution-mcp. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
semantic versioning. Each release's section is what the release workflow
publishes as the release notes - a tag with no section here does not ship.

## [3.5.0] - 2026-08-20

The interoperability release: findings speak the industry's language.
Every finding carries a MITRE CWE where a defensible mapping exists, and
the review renders as SARIF 2.1.0 for GitHub code scanning - so the gate's
output lands in the Security tab of every consuming repository, tagged by
weakness class, instead of living only in annotations and logs.

### Added

- **CWE tagging across all four engines.** Deferral prose and markers are
  CWE-546 (Suspicious Comment); empty function/loop bodies are CWE-1071
  (Empty Code Block); empty catch/except handling is CWE-1069 (Empty
  Exception Block); stubs that fake their contract (hardcoded returns,
  not-implemented throws, panic()/todo!() stubs) are CWE-684 (Incorrect
  Provision of Specified Functionality); unreachable code is CWE-561,
  constant conditions are CWE-570/571 selected by actual polarity, and
  the Po10 metrics are CWE-1121/1120. Engines attach identical IDs to
  byte-identical finding texts, so deduplication can never merge findings
  that disagree about their weakness class. Absence of `cwe` is a
  statement - no honest mapping exists (mock/fake/passthrough classes) -
  and tests pin both directions.
- **SARIF 2.1.0 output.** `to_sarif()` renders a review with stable
  ruleIds derived from the constitution failure classes, severity-mapped
  levels, real line coordinates, and CWE tags on rules and results.
  Skipped files and pre-existing debt contribute nothing: SARIF gates
  exactly what the verdict gates.
- **`--sarif-file PATH`** on the CLI (written before stdout output; an
  unwritable path is an operational error, exit 3, not a crash) and a
  **`sarif-file` input on the composite action**, which uploads to code
  scanning via SHA-pinned codeql-action - skipped automatically for fork
  PRs, whose tokens cannot upload. Dogfooded on this repository's own
  PR gate.

## [3.4.0] - 2026-08-20

The verification-depth release: the protocol boundary is conformance-
tested and fuzzed (and two spec deviations it found are fixed), the
entire first-party package is typed under strict mypy, the detector core
is mutation-tested nightly, and every release now carries the scanner
accuracy its own build measured.

### Fixed

- **Malformed id-less frames were silenced.** JSON-RPC 2.0's own examples
  answer `{"jsonrpc": "2.0", "method": 1}` with an id-null -32600; an
  invalid object cannot be trusted to be a notification, because the
  missing id may itself be the malformation. Silence is now reserved for
  well-formed notifications exactly.
- **notifications/\* with an id attached was silenced.** Anything
  carrying an id is a request and must be answered; unknown methods now
  uniformly produce METHOD_NOT_FOUND and only genuinely id-less frames
  are discarded. Found, like the above, by the new fuzz suite's first run.
- `handle_tools_call` answered an unhashable tool name with
  INTERNAL_ERROR (it crashed inside `dict.get`); a caller mistake is now
  INVALID_PARAMS. Forced by the type checker during strict-mypy adoption.

### Added

- **Protocol conformance and fuzz suite**
  (`tests/test_protocol_conformance.py`): pins the initialize,
  tools/list, and tools/call shapes; 600 seeded mutated frames against
  `dispatch()` under three invariants (never raises; exactly one response
  per request, id echoed, exactly one of result/error; silence for
  well-formed notifications); byte-level garbage against the stdio loop
  proving the transport survives and stdout stays pure JSON frames.
- **Debug diagnostics**: `--debug` flag or `PERSONA_CONSTITUTION_DEBUG`
  env enables one stderr line per frame - method, tool, frame/response
  sizes, wall-clock cost. Sizes only, never payload content; a test pins
  that a scanned secret cannot appear in the diagnostics.
- **Strict typing, gated**: every first-party module fully annotated,
  `mypy --strict` clean (3.9 target; vendored codebase_csi outside the
  regime with its symbols guarded at explicit boundaries), pinned mypy
  running as its own CI job. GitHub API responses are now shape-checked
  at the client boundary instead of trusted.
- **Nightly mutation testing** (`mutation.yml` + `[tool.mutmut]`):
  mutmut over the detector core (scanner, logic rules, ast bridge, diff
  parser, review engine), driving the existing unittest suite through
  pytest. Introduction baseline on logic_rules.py: 107/155 mutants
  killed (69%); survivors are the enumerated test gaps to close.
  `tests/conftest.py` scopes real-repository assertions (release
  integrity, wall-clock budgets, subprocess transport) out of the
  mutation sandbox where they are meaningless.
- **Measured accuracy in release notes**: the release build's benchmark
  summary (corpus size, per-tier and union detection rates) is appended
  to the GitHub Release notes and attached as an artifact - the rules
  are the product, so the number ships with it.

## [3.3.1] - 2026-08-20

### Fixed

- The release pipeline's SBOM step used `--outfile`; cyclonedx-bom 7.x
  spells it `--output-file`, so the v3.3.0 release build failed before
  publishing anything (the version-match, test, benchmark, wheel-content
  and twine gates had all passed). The flag is corrected and the tool is
  now pinned exactly, for the same reason ruff is: a release pipeline
  must not absorb upstream CLI changes as surprises. v3.3.0's tag remains
  where it was - tags are immutable here; the fix ships as a new version.

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

[3.5.0]: https://github.com/QuantmindSSI/CTO-MCP/compare/v3.4.0...v3.5.0
[3.4.0]: https://github.com/QuantmindSSI/CTO-MCP/compare/v3.3.1...v3.4.0
[3.3.1]: https://github.com/QuantmindSSI/CTO-MCP/compare/v3.3.0...v3.3.1
[3.3.0]: https://github.com/QuantmindSSI/CTO-MCP/compare/v3.2.0...v3.3.0
[3.2.0]: https://github.com/QuantmindSSI/CTO-MCP/compare/4d43eb0...v3.2.0
[3.1.0]: https://github.com/QuantmindSSI/CTO-MCP/compare/5c0160e...4d43eb0
[3.0.0]: https://github.com/QuantmindSSI/CTO-MCP/commits/5c0160e
