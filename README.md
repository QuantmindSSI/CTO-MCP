# CTO-MCP — `persona-constitution` MCP Server

An MCP (Model Context Protocol) server that serves the **Oluwaferanmi Oluwagbamila Agentic Engineering Persona — LLM Operational Constitution v3.0.0** to any MCP-capable coding agent.

Grounded in **SWEBOK v4.0** (18 Knowledge Areas), the **NASA/JPL Power of 10**, and **Zero Framework Tolerance**.

The constitution exists to counteract a specific, structural LLM failure mode: producing code that has the *shape* of a solution but none of the substance — skeletons, `TODO`s, stubs, and "you can extend this to…". This server makes the constitution queryable, and ships a scanner that mechanically detects those violations in generated code.

> **The Supreme Law** — Every code output must be complete, executable, and correct. Not a scaffold. Not a pattern. Not a direction. Code that runs. Logic that is correct. Implementation that is done.

---

## Requirements

- Python **3.9+** — the test suite is run against CPython 3.9.6 and 3.14.6.
- One dependency: [**CodebaseCSI**](https://github.com/Thundastormgod/CodebaseCSI) (MIT), which
  backs the code scanner. It is itself dependency-free, so the full install tree is
  CodebaseCSI and nothing else. It is not published on PyPI and is pinned to a git revision.

---

## Layout

```
CTO-MCP/
├── persona_constitution/
│   ├── __init__.py          Package API re-exports
│   ├── scanner.py           Detection engine: CodebaseCSI + prose rules + Python AST
│   └── server.py            MCP server: JSON-RPC 2.0 over stdio
├── data/
│   ├── CONSTITUTION.md      Full constitution (the served corpus)
│   └── DIRECTIVES.md        Distilled directives for system-prompt injection
├── tests/
│   └── test_server.py       74 tests: unit + end-to-end stdio transport
├── pyproject.toml
└── README.md
```

---

## Setup

The server needs a virtualenv with CodebaseCSI installed. From the repo root:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

`.venv/bin/python` is then the interpreter your MCP client must launch. Starting the
server with an interpreter that lacks CodebaseCSI exits `1` with an explanatory message
on stderr — it will not fall back to a weaker scanner and report misleadingly clean results.

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

  "instructions": ["<REPO>/data/DIRECTIVES.md"],

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

### `section` values for `get_constitution`

`toc` · `preamble` · `identity` · `anti-deception` · `intelligence-architecture` · `t-shape` · `swebok` · `consensus-protocol` · `iteration-protocol` · `agentic-pathway` · `power-of-10` · `operational-directives` · `knowledge-graph` · `invariants` · `references` · `full`

(`hive-mind` is still accepted as a deprecated alias for `consensus-protocol`.)

### The scanner

`scan_code_for_violations` is a union of three engines, because no one of them is adequate alone:

| Engine | Contributes |
|---|---|
| **CodebaseCSI** `MockCodeDetector` | Structural stubs, mock implementations, always-success functions, print-only bodies, fake data, pass-through functions, TODO markers |
| **Constitution prose rules** | Class 2 / Class 5 narrative deferral, and empty-body / unimplemented-stub detection for JavaScript, TypeScript, Java, Go and Rust |
| **Python AST analysis** | Suppresses markers inside ordinary string literals; distinguishes genuine stubs from legitimate abstract declarations; classifies bare vs. typed `except: pass` |

Coverage by failure class:

- **Class 1 — Framework Generation:** `TODO`, `FIXME`, `XXX`, "your code here", "implement … here/later", `raise NotImplementedError`, `todo!()`, `unimplemented!()`, `panic("not implemented")`, empty function and method bodies, and bodies consisting only of `pass` or `...`
- **Class 2 — Scaffold Deception:** "rest of the implementation", "follows the same pattern", "omitted for brevity", "and so on for the rest", "similar for the others"
- **Class 3 — Confidence Mismatch:** empty `catch {}` blocks, bare `except: pass`, always-success functions
- **Class 5 — Iteration Deferral:** "left as an exercise", "you can extend this", "this is a starting point", "you would want to add", "the full implementation would", "in production you would"

Verdicts: `FAIL` if any *violation* fires, `REVIEW` if only *warnings* fire, `PASS` otherwise.

#### Measured accuracy

Measured against a 27-case adversarial corpus — 18 real violations across six languages, plus 9
pieces of legitimate code specifically constructed to resemble violations (a linter that matches
on the string `"TODO"`, a `typing.Protocol` whose methods are `...`, a documented
`except OSError: pass`, a React `placeholder=` attribute, a docstring containing the words
"for brevity"):

| Configuration | Correct verdicts |
|---|---|
| Original regex-only scanner (pre-CSI, git history) | 12/27 — 44% |
| CodebaseCSI alone | 13/27 — 48% |
| Constitution prose + structural rules alone | 20/27 — 74% |
| **Union (this implementation)** | **26/27 — 96%** |

The two engines fail on largely disjoint inputs, which is why the union beats both: CodebaseCSI
misses every non-Python structural stub and every prose deferral; the prose rules miss
Python-semantic stubs such as always-true and print-only functions.

The one remaining miss is a JavaScript body of `{ return null; }`, deliberately graded `REVIEW`
rather than `FAIL` because a bare null return is legitimate in hand-written code. It is surfaced,
not silently dropped.

Reproduce with:

```bash
.venv/bin/python tools/benchmark_scanner.py
```

**Read these numbers with suspicion.** The corpus is small and was written by the same author as
the rules, which biases the result upward. It is a regression guard, not a general accuracy claim.

**A `PASS` is necessary but not sufficient.** Static analysis proves the absence of placeholder
markers — it cannot prove executability, correctness, or dependency honesty. The G1–G5 gates still apply.

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
| `PERSONA_CONSTITUTION_PATH` | Absolute path to an alternative `CONSTITUTION.md`. Defaults to `<repo>/data/CONSTITUTION.md`. |

The server exits with status `1` and a message on **stderr** if the constitution file is missing or empty — a broken install fails loudly rather than silently serving nothing.

---

## Tests

Run from the repo root, using the virtualenv interpreter:

```bash
.venv/bin/python -m unittest discover -s tests -v   # 74 tests
```

Coverage spans three layers:

1. **Unit** — constitution loading (missing, empty, env-override), markdown section extraction (all 14 sections, all 18 KAs, all 10 rules, fenced-code-block handling), the scanner (line-number accuracy, per-class detection, verdict boundaries), and JSON-RPC dispatch (tool errors vs. protocol errors, notifications, malformed params).
2. **Scanner behaviour** — false-positive suppression (string literals, `Protocol`, `@abstractmethod`, documented `except: pass`), cross-language stub detection (Go, JavaScript, Java, TypeScript), prose deferral rules, engine composition, and graceful handling of unparseable source.
3. **End-to-end transport** — a real subprocess driven over stdio: `initialize` handshake, `tools/list`, a full multi-tool session, malformed-input recovery, notification suppression, non-zero exit on a missing data file, and the invariant that **stdout carries only protocol frames**.

---

## Protocol notes

- Transport: newline-delimited JSON-RPC 2.0 over stdio, one message per line.
- Methods: `initialize`, `tools/list`, `tools/call`, `ping`. `notifications/*` are accepted and correctly produce no response frame.
- Protocol version: `2025-06-18`; the client's requested version is echoed when it supplies one.
- Tool-level failures (bad arguments) return `isError: true` inside the result so the model can read and self-correct. Protocol-level failures return proper JSON-RPC error codes (`-32700`, `-32600`, `-32601`, `-32602`, `-32603`).
- Diagnostics go to stderr exclusively. stdout is never polluted with non-protocol bytes.

---

## Credits

The structural detection half of `scan_code_for_violations` is provided by
**[CodebaseCSI](https://github.com/Thundastormgod/CodebaseCSI)**, used under the MIT License.
This project adds the MCP interface, the Constitution corpus, the Class 2 / Class 5 prose
rules, the cross-language structural rules, and the Python AST false-positive suppression.

---

## References

1. IEEE Computer Society (2024). *Guide to the Software Engineering Body of Knowledge (SWEBOK) v4.0.* Ed. H. Washizaki. 18 Knowledge Areas.
2. Holzmann, G.J. (2006). *The Power of 10: Rules for Developing Safety-Critical Code.* IEEE Computer 39(6), 95–97.
3. Model Context Protocol specification — <https://modelcontextprotocol.io>
4. CodebaseCSI — forensic AI-generated-code detection. <https://github.com/Thundastormgod/CodebaseCSI>
