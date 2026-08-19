# CTO-MCP — `persona-constitution` MCP Server + Agentic PR Review

An MCP (Model Context Protocol) server that serves the **Oluwaferanmi Oluwagbamila Agentic Engineering Persona — LLM Operational Constitution v3.0.0** to any MCP-capable coding agent, and a **PR review gate** that enforces the constitution's Zero-Framework-Tolerance rules on pull requests — as an MCP tool, a CLI, a reusable GitHub Action, and an opencode agent.

Grounded in **SWEBOK v4.0** (18 Knowledge Areas), the **NASA/JPL Power of 10**, and **Zero Framework Tolerance**.

The constitution exists to counteract a specific, structural LLM failure mode: producing code that has the *shape* of a solution but none of the substance — skeletons, `TODO`s, stubs, and "you can extend this to…". This server makes the constitution queryable, ships a scanner that mechanically detects those violations in generated code, and turns that scanner into a diff-aware pull-request reviewer.

> **The Supreme Law** — Every code output must be complete, executable, and correct. Not a scaffold. Not a pattern. Not a direction. Code that runs. Logic that is correct. Implementation that is done.

---

## Requirements

- Python **3.9+** — the test suite is run against CPython 3.9.6 and 3.14.6.
- **Zero runtime dependencies.** [CodebaseCSI](https://github.com/Thundastormgod/CodebaseCSI)
  (MIT), which backs the scanner, is vendored at `codebase_csi/` — provenance, pinned upstream
  revision, and the local-modification ledger live in `codebase_csi/VENDORED.md`.
- Optional `[ast]` extra: tree-sitter grammars that upgrade the scanner from regex to real AST
  analysis for JavaScript, TypeScript, Java, Go, Rust, Ruby, C and C++. Without it the scanner
  still runs and says so in its `engines` output. The pins are an ABI compatibility matrix
  verified on the 3.9 floor — see the comment block in `pyproject.toml`.

---

## Layout

```
CTO-MCP/
├── persona_constitution/
│   ├── __init__.py          Package API re-exports
│   ├── scanner.py           Detection engine: CodebaseCSI + prose rules + Python AST
│   ├── ast_bridge.py        constitution-xast: tree-sitter engine for brace languages
│   ├── logic_rules.py       Deep logic rules: Po10 metrics, empty loops, identical
│   │                        branches, constant conditions, unreachable code
│   ├── server.py            MCP server: JSON-RPC 2.0 over stdio
│   ├── review/
│   │   ├── diff.py          Unified diff parser (git-quoted paths, hunk edge cases)
│   │   ├── engine.py        Diff-aware review: attribution, C-03 policy, exclusions
│   │   ├── config.py        .persona-review.json: one policy for both gate factors
│   │   ├── report.py        Renderers: text, Actions annotations, GitHub review payload
│   │   ├── github_client.py Stdlib GitHub REST client (bounded retries)
│   │   └── cli.py           persona-pr-review: --staged/--diff/--git/--github/--install-hook
│   └── data/                Ships inside the package, so an installed copy works
│       ├── CONSTITUTION.md  Full constitution (the served corpus)
│       └── DIRECTIVES.md    Distilled directives for system-prompt injection
├── codebase_csi/            Vendored CodebaseCSI (MIT) — see VENDORED.md
├── .persona-review.json     This repository's own review policy (dogfood)
├── .opencode/
│   ├── agent/pr-review.md   Factor-2 agent: business-logic test research + G1-G5
│   └── command/review-staged.md  /review-staged: both factors before committing
├── .github/workflows/
│   ├── ci.yml               Lint, tests (3.9/3.14 x with/without [ast]), packaging
│   └── pr-review.yml        Dogfood: this repo's PRs pass through its own gate
├── action.yml               Reusable composite GitHub Action for any repository
├── tests/                   Unit, engine, review, two-factor integration, smoke, e2e
├── tools/
│   └── benchmark_scanner.py Adversarial accuracy benchmark (regression gate)
├── LICENSE
├── pyproject.toml
└── README.md
```

---

## Setup

From the repo root:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[ast]"   # or plain `.` to skip the tree-sitter tier
```

`.venv/bin/python` is then the interpreter your MCP client must launch. Starting the
server with an interpreter that cannot import the vendored `codebase_csi` exits `1` with an
explanatory message on stderr — it will not fall back to a weaker scanner and report
misleadingly clean results.

---

## Install into opencode

Two mechanisms, used together. The instructions file injects the constitution into the system
prompt of every session, for every configured model; the MCP server provides on-demand
structured lookup and mechanical verification.

Injection is not enforcement. `instructions` is system-prompt text, and whether a model
*follows* it is a property of that model, not of this repo — only the MCP scanner performs a
mechanical check. Two caveats worth knowing before you rely on it:

- **Small-context models can choke on the payload.** `DIRECTIVES.md` is a substantial system
  prompt; on a 16k-context deployment (tested: Azure Phi-4) sessions hung rather than degrading
  gracefully. Prefer models with a large context window, or trim `DIRECTIVES.md` for small ones.
- **Compliance is per-model and worth spot-checking.** Verified by direct observation on
  OpenAI- and Anthropic-adapter models, which reproduced gate and law text verbatim on request.
  That is a sample, not a proof across every provider — re-verify on yours.

Add to `~/.config/opencode/opencode.json` (or `opencode.jsonc`), replacing `<REPO>` with the absolute path to this clone:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",

  "instructions": ["<REPO>/persona_constitution/data/DIRECTIVES.md"],

  "mcp": {
    "persona-constitution": {
      "type": "local",
      "command": ["<REPO>/.venv/bin/python", "<REPO>/persona_constitution/server.py"],
      "enabled": true
    }
  }
}
```

`instructions` is global opencode config, so the directives are injected into the system
prompt of **every** model and provider you have configured — there is no per-model setup.
Note that the directives consume context: models with small context windows may struggle.

Restart opencode afterwards — config is loaded once at startup and is not hot-reloaded.

### Install into other MCP clients

Any client that speaks MCP over stdio works. Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "persona-constitution": {
      "command": "<REPO>/.venv/bin/python",
      "args": ["<REPO>/persona_constitution/server.py"]
    }
  }
}
```

---

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `get_constitution` | `section` (optional) | Table of contents + Supreme Law by default; any named section; or `full` for the whole document |
| `get_knowledge_area` | `ka` (1–18, or a name) | One SWEBOK v4.0 Knowledge Area with its LLM operational discipline; omit `ka` to list all 18 |
| `get_power_of_10` | `rule` (1–10, optional) | One Power of 10 rule with code / architecture / organisational applications, or all ten |
| `get_verification_gates` | none | The G1–G5 pre-emission gates and the prohibited-marker checklist |
| `scan_code_for_violations` | `code` (required), `language` (optional) | JSON verdict `PASS` / `REVIEW` / `FAIL` with line-numbered findings |
| `review_patch` | `diff` (required), `files` (optional map path → content), `exclude` (optional globs), `require_tests` (`off`/`warn`/`fail`), `test_globs` (optional globs) | Diff-aware review JSON: per-file findings attributed to changed lines, pre-existing debt counted separately, C-03 test-presence policy, verdict `PASS` / `REVIEW` / `FAIL` |

### `section` values for `get_constitution`

`toc` · `preamble` · `identity` · `anti-deception` · `intelligence-architecture` · `t-shape` · `swebok` · `consensus-protocol` · `iteration-protocol` · `agentic-pathway` · `power-of-10` · `operational-directives` · `knowledge-graph` · `invariants` · `references` · `full`

(`hive-mind` is still accepted as a deprecated alias for `consensus-protocol`.)

### The scanner

`scan_code_for_violations` is a union of five engines, because no one of them is adequate alone:

| Engine | Contributes |
|---|---|
| **CodebaseCSI** `MockCodeDetector` | Structural stubs, mock implementations, always-success functions, print-only bodies, fake data, pass-through functions, TODO markers. `docstring_todo` hits are verified against real docstring spans via the AST (regex cannot decide triple-quote parity) |
| **Constitution prose rules** | Class 2 / Class 5 narrative deferral, and empty-body / unimplemented-stub detection for JavaScript, TypeScript, Java, Go and Rust |
| **Python AST analysis** | Suppresses markers inside ordinary string literals; distinguishes genuine stubs from legitimate abstract declarations; classifies bare vs. typed `except: pass` |
| **constitution-logic** (Python) | Deep logic shape, all warnings: Po10 Rule 1 (cyclomatic > 10) and Rule 4 (function > 50 lines), empty loop bodies, identical if/else arms, constant `if` conditions (`while True:` event loops exempt), unreachable code after terminal statements |
| **constitution-xast** (`[ast]` extra) | Tree-sitter parse of JavaScript, TypeScript, Java, Go, Rust, Ruby, C and C++; judges hardcoded-return stubs (including `const f = (x) => { return null; }` declarator bindings), empty bodies, empty catch blocks, not-implemented throws, empty loops, identical branches, and per-function Po10 metrics on real AST nodes. Deliberately exempts anonymous callbacks, expression-bodied arrows, noop-default `const f = () => {}` bindings, and constructors; reports itself inactive rather than guessing on unparseable input |

Verdict philosophy: mechanical certainties (stubs, scaffold markers) are **violations** and FAIL; judgement calls (metrics, logic shape, test presence) are **warnings** and REVIEW - the agent layer adjudicates them, never silently.

Coverage by failure class:

- **Class 1 — Framework Generation:** `TODO`, `FIXME`, `XXX`, "your code here", "implement … here/later", `raise NotImplementedError`, `todo!()`, `unimplemented!()`, `panic("not implemented")`, empty function and method bodies, and bodies consisting only of `pass` or `...`
- **Class 2 — Scaffold Deception:** "rest of the implementation", "follows the same pattern", "omitted for brevity", "and so on for the rest", "similar for the others"
- **Class 3 — Confidence Mismatch:** empty `catch {}` blocks, bare `except: pass`, always-success functions
- **Class 5 — Iteration Deferral:** "left as an exercise", "you can extend this", "this is a starting point", "you would want to add", "the full implementation would", "in production you would"

Verdicts: `FAIL` if any *violation* fires, `REVIEW` if only *warnings* fire, `PASS` otherwise.

#### Measured accuracy

Measured against a 37-case adversarial corpus — 24 real violations across seven languages, plus
13 pieces of legitimate code specifically constructed to resemble violations (a linter that
matches on the string `"TODO"`, a `typing.Protocol` whose methods are `...`, a documented
`except OSError: pass`, a React `placeholder=` attribute, an anonymous no-op callback, an empty
Java constructor, a noop-default arrow binding, a busy-wait loop):

| Configuration | Correct verdicts |
|---|---|
| CodebaseCSI alone | 15/37 — 40% |
| Constitution prose + structural rules alone | 22/37 — 59% |
| **Union without the `[ast]` extra** | **30/37 — 81%** |
| **Union with the `[ast]` extra** | **37/37** |

The engines fail on largely disjoint inputs, which is why the union beats each: CodebaseCSI
misses every non-Python structural stub and every prose deferral; the prose rules miss
Python-semantic stubs such as always-true and print-only functions; and seven corpus cases
(`function getUser(id) { return null; }`, a bare `UnsupportedOperationException`, a
template-literal `` throw new Error(`not implemented`) ``, a braceless empty Ruby method, a Go
`return nil` stub, and stubs bound through `const name = (args) => {...}` declarators) are
decidable only on a real syntax tree. Both baselines are enforced in CI across both
configurations.

Reproduce with:

```bash
.venv/bin/python tools/benchmark_scanner.py
```

**Read these numbers with suspicion.** The corpus is small and was written by the same author as
the rules, which biases the result upward. It is a regression guard, not a general accuracy claim.

**A `PASS` is necessary but not sufficient.** Static analysis proves the absence of placeholder
markers — it cannot prove executability, correctness, or dependency honesty. The G1–G5 gates still apply.

---

## Two-factor review

The scanner generalises to a **two-factor review gate** through
`persona_constitution/review/`: the same deterministic engine judges the change at two moments
— **factor 1a when files are staged** (pre-commit hook, contents read from the git index so
what is judged is exactly what would be committed) and **factor 1b at PR time** (Action / CLI /
MCP tool). **Factor 2** is the agent layer, which at both moments researches the project's
business-logic tests before exercising judgement. Findings are **attributed to the lines the
change introduces**; pre-existing debt in touched files is counted and surfaced but never gates
the merge.

One policy file, `.persona-review.json` at the repository root, drives every surface (both
factors, the Action, and the agent), so a rule can never be enforced at one gate and forgotten
at the other:

```json
{
  "exclude": ["tests/*", "vendor/*"],
  "require_tests": "warn",
  "min_test_trigger_lines": 5,
  "test_globs": ["qa/*"],
  "business_logic": {
    "description": "what this system's correctness actually means",
    "critical_paths": ["billing/*"],
    "business_logic_tests": ["tests/test_billing.py"],
    "test_commands": ["python -m unittest discover -s tests"]
  }
}
```

`require_tests` is the C-03 policy (non-trivial code ships with tests): when a diff changes at
least `min_test_trigger_lines` of production logic and touches **zero** test files, every such
file is flagged — `warn` surfaces it for adjudication, `fail` gates the merge. The deterministic
policy is deliberately diff-global; mapping *which* tests cover *which* changed behaviour is the
agent's business-logic research, not a glob matcher's.

Delivery surfaces, one engine:

**0. Staged gate (factor 1a)** — install once per clone:

```bash
persona-pr-review --install-hook          # writes .git/hooks/pre-commit (refuses to clobber
                                          # a foreign hook without --force)
persona-pr-review --staged --json         # what the hook runs: git diff --cached, contents
                                          # from `git show :0:path` (the index, not the worktree)
```

A commit with staged violations is blocked; bypassing with `git commit --no-verify` is loud and
still lands in front of factor 1b and the agent.

**1. MCP tool** — `review_patch` (table above). The server stays offline and deterministic: the
agent brings the diff (`gh pr diff`), the tool returns structured findings.

**2. CLI** — installed as `persona-pr-review`:

```bash
# local working tree against a base
persona-pr-review --git origin/main...HEAD --root . --json

# an existing diff file, annotated for GitHub Actions
persona-pr-review --diff change.diff --annotate

# a GitHub PR, posting REQUEST_CHANGES/COMMENT with inline comments
GITHUB_TOKEN=... persona-pr-review --github owner/repo#42 --post \
    --require-tests fail --exclude 'vendor/*'
```

Flags override `.persona-review.json`; `--exclude` appends to it. Exit codes: `0` PASS (or
REVIEW), `1` FAIL (or REVIEW with `--fail-on-review`), `3` operational error (including a
malformed policy file — a broken policy stops the gate rather than silently weakening it). The
GitHub client is stdlib `urllib` with bounded retries; the reviewer never emits `APPROVE` — a
scanner can prove the absence of markers, not the presence of correctness.

**3. Reusable GitHub Action** — the composite action at the repo root:

```yaml
permissions:
  contents: read
  pull-requests: write
steps:
  - uses: actions/checkout@v5
  - uses: QuantmindSSI/CTO-MCP@main   # pin a tag/sha in production
    with:
      exclude: "vendor/*"        # appended to the repo's .persona-review.json
      require-tests: "warn"      # C-03; empty = use the repo's config
      fail-on-review: "false"
```

Violations become `::error` annotations on the changed lines and a posted review that
`REQUEST_CHANGES`; fork PRs are automatically downgraded to annotations-only so the token never
serves untrusted code. This repository dogfoods the action on its own PRs
(`.github/workflows/pr-review.yml`).

**4. opencode agent (factor 2)** — `.opencode/agent/pr-review.md` defines the agentic layer.
Its protocol is layered and ordered: **Layer 0** reads `.persona-review.json` and researches
the project's test landscape (which layers exist — unit, integration, e2e, smoke, regression —
and which tests reference the changed symbols, via `git grep` over the test tree); **Layer 1**
runs the deterministic gate through the MCP tool (its FAIL verdict cannot be overridden);
**Layer 2** judges business-logic coverage — changed behaviour vs. covering tests found,
updated or not, with test-command runs as evidence; **Layer 3** applies gates G1–G5 and the
nine review dimensions. Deterministic findings are supreme; agent judgement is additive only;
never APPROVE.

**5. /review-staged command** — `.opencode/command/review-staged.md` runs the full two-factor
flow on the staged index before a commit: the deterministic staged gate first, then the same
agent protocol, concluding "COMMIT" or "DO NOT COMMIT" with file:line-anchored required fixes.

---

## The five verification gates

Run before emitting any code. All five must pass; if any fails, regenerate from the problem statement rather than patching.

| Gate | Question |
|---|---|
| **G1 Executability** | Copy-pasted into a blank file with the stated dependencies, does it run without modification? |
| **G2 Completeness** | Does every function contain a real implementation? Any placeholder, TODO, or empty body? |
| **G3 Correctness** | Execution traced for the happy path, the primary error paths, and the stated edge cases? |
| **G4 Dependency Honesty** | Does every import, call, and referenced module exist in this output or a verified dependency? |
| **G5 Problem Fit** | Does this solve the stated problem, at the stated scale, under the stated constraints — not a simpler adjacent one? |

---

## Configuration

| Variable | Effect |
|---|---|
| `PERSONA_CONSTITUTION_PATH` | Absolute path to an alternative `CONSTITUTION.md`. Defaults to the copy shipped inside the package, `persona_constitution/data/CONSTITUTION.md`. |

The server exits with status `1` and a message on **stderr** if the constitution file is missing or empty — a broken install fails loudly rather than silently serving nothing.

---

## Tests

Run from the repo root, using the virtualenv interpreter:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/benchmark_scanner.py          # regression gate
```

The suite is organised as a full test taxonomy:

1. **Smoke** (`test_smoke.py`) — the critical path of every delivery surface in seconds: package import and version coherence, one stub/one clean scan, one review verdict, the console entry point, and a real MCP stdio handshake listing all six tools. A broken install fails here before anything else spends time.
2. **Unit** (`test_server.py`, `test_ast_bridge.py`) — constitution loading, markdown section extraction (all 14 sections, 18 KAs, 10 rules), scanner line-number accuracy and verdict boundaries, JSON-RPC dispatch, per-language xast stub detection, the deep-logic rules (Po10 metrics, empty loops, identical branches, constant conditions, unreachable code, `while True:` exemption), and the constant-drift guards that keep cross-engine deduplication sound.
3. **Regression** (`test_server.py` false-positive classes, `tools/benchmark_scanner.py`) — every previously confirmed false positive stays fixed (string literals, `Protocol`, `@abstractmethod`, documented `except: pass`, `{}` literals inside Python bodies, triple-quote parity), and the 37-case adversarial corpus enforces environment-aware accuracy baselines (37/37 with `[ast]`, 30/37 without) in CI.
4. **Review engine** (`test_review.py`) — diff parsing (renames, binary, git-quoted unicode paths, submodule and mode-only changes, CRLF, lying hunk headers, adversarial garbage), changed-line attribution vs. pre-existing debt, exclusion globs, renderer contracts (never `APPROVE`, comment budgets, annotation escaping), and the `review_patch` tool over the dispatcher including C-03 arguments.
5. **Two-factor integration** (`test_two_factor.py`) — real git repositories: the policy config contract (strict schema, loud failures), C-03 test-presence enforcement in warn/fail modes, staged-gate index authority (a fixed worktree must not mask a broken index), hook installation (foreign-hook refusal, `--force`), an installed hook **blocking a genuine `git commit`** and then admitting a clean, tested change, and factor parity (staged gate and PR gate reach identical findings on the same change).
6. **End-to-end transport** (`test_server.py`) — a real subprocess driven over stdio: `initialize` handshake, `tools/list`, a full multi-tool session, malformed-input recovery, notification suppression, non-zero exit on a missing data file, and the invariant that **stdout carries only protocol frames**.

---

## Protocol notes

- Transport: newline-delimited JSON-RPC 2.0 over stdio, one message per line.
- Methods: `initialize`, `tools/list`, `tools/call`, `ping`. `notifications/*` are accepted and correctly produce no response frame.
- Protocol version: `2025-06-18`; the client's requested version is echoed when it supplies one.
- Tool-level failures (bad arguments) return `isError: true` inside the result so the model can read and self-correct. Protocol-level failures return proper JSON-RPC error codes (`-32700`, `-32600`, `-32601`, `-32602`, `-32603`).
- Diagnostics go to stderr exclusively. stdout is never polluted with non-protocol bytes.

---

## Credits

The structural detection layer of the scanner is provided by
**[CodebaseCSI](https://github.com/Thundastormgod/CodebaseCSI)**, used under the MIT License and
vendored at `codebase_csi/` (upstream revision and local modifications are recorded in
`codebase_csi/VENDORED.md`). This project adds the MCP interface, the Constitution corpus, the
Class 2 / Class 5 prose rules, the cross-language structural rules, the Python AST
false-positive suppression, the tree-sitter xast engine, and the diff-aware PR review stack.

---

## License

MIT — see [LICENSE](LICENSE).

CodebaseCSI is also MIT, and its license text is reproduced verbatim in the `LICENSE` file
under *Third-Party Components*, as its terms require.

---

## References

1. IEEE Computer Society (2024). *Guide to the Software Engineering Body of Knowledge (SWEBOK) v4.0.* Ed. H. Washizaki. 18 Knowledge Areas.
2. Holzmann, G.J. (2006). *The Power of 10: Rules for Developing Safety-Critical Code.* IEEE Computer 39(6), 95–97.
3. Model Context Protocol specification — <https://modelcontextprotocol.io>
4. CodebaseCSI — forensic AI-generated-code detection. <https://github.com/Thundastormgod/CodebaseCSI>
