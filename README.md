# CTO-MCP — `persona-constitution` MCP Server

An MCP (Model Context Protocol) server that serves the **Oluwaferanmi Oluwagbamila Agentic Engineering Persona — LLM Operational Constitution v3.0.0** to any MCP-capable coding agent.

Grounded in **SWEBOK v4.0** (18 Knowledge Areas), the **NASA/JPL Power of 10**, and **Zero Framework Tolerance**.

The constitution exists to counteract a specific, structural LLM failure mode: producing code that has the *shape* of a solution but none of the substance — skeletons, `TODO`s, stubs, and "you can extend this to…". This server makes the constitution queryable, and ships a scanner that mechanically detects those violations in generated code.

> **The Supreme Law** — Every code output must be complete, executable, and correct. Not a scaffold. Not a pattern. Not a direction. Code that runs. Logic that is correct. Implementation that is done.

---

## Requirements

- Python **3.9+**
- **No third-party dependencies.** Standard library only.

---

## Layout

```
CTO-MCP/
├── persona_constitution/
│   ├── __init__.py          Package API re-exports
│   └── server.py            MCP server: JSON-RPC 2.0 over stdio
├── data/
│   ├── CONSTITUTION.md      Full constitution (the served corpus)
│   └── DIRECTIVES.md        Distilled directives for system-prompt injection
├── tests/
│   └── test_server.py       51 tests: unit + end-to-end stdio transport
├── pyproject.toml
└── README.md
```

---

## Install into opencode

Two mechanisms, used together. The instructions file guarantees the constitution is *always* enforced; the MCP server provides on-demand structured lookup and mechanical verification.

Add to `~/.config/opencode/opencode.json` (or `opencode.jsonc`), replacing `<REPO>` with the absolute path to this clone:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",

  "instructions": ["<REPO>/data/DIRECTIVES.md"],

  "mcp": {
    "persona-constitution": {
      "type": "local",
      "command": ["python3", "<REPO>/persona_constitution/server.py"],
      "enabled": true
    }
  }
}
```

Restart opencode afterwards — config is loaded once at startup and is not hot-reloaded.

### Install into other MCP clients

Any client that speaks MCP over stdio works. Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "persona-constitution": {
      "command": "python3",
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

`toc` · `preamble` · `identity` · `anti-deception` · `intelligence-architecture` · `t-shape` · `swebok` · `hive-mind` · `iteration-protocol` · `agentic-pathway` · `power-of-10` · `operational-directives` · `knowledge-graph` · `invariants` · `references` · `full`

### The scanner

`scan_code_for_violations` applies 21 rules covering four of the five documented LLM failure classes:

- **Class 1 — Framework Generation:** `TODO`, `FIXME`, `XXX`, "your code here", "implement … here/later", `raise NotImplementedError`, `todo!()`, `unimplemented!()`, and Python functions whose entire body is `pass` or `...`
- **Class 2 — Scaffold Deception:** "rest of the implementation", "follows the same pattern", "omitted for brevity", "and so on for the rest"
- **Class 3 — Confidence Mismatch:** empty `catch {}` blocks, `except: pass`
- **Class 5 — Iteration Deferral:** "left as an exercise", "you can extend this", "this is a starting point", "you would want to add", "the full implementation would"

Verdicts: `FAIL` if any *violation* fires, `REVIEW` if only *warnings* fire, `PASS` otherwise.

**A `PASS` is necessary but not sufficient.** Static pattern matching proves the absence of placeholder markers — it cannot prove executability, correctness, or dependency honesty. The G1–G5 gates still apply.

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

```bash
python3 -m unittest discover -s tests -v   # 51 tests
python3 tests/test_server.py               # equivalent, direct
```

Coverage spans two layers:

1. **Unit** — constitution loading (missing, empty, env-override), markdown section extraction (all 14 sections, all 18 KAs, all 10 rules, fenced-code-block handling), the scanner (line-number accuracy, per-class detection, verdict boundaries), and JSON-RPC dispatch (tool errors vs. protocol errors, notifications, malformed params).
2. **End-to-end transport** — a real subprocess driven over stdio: `initialize` handshake, `tools/list`, a full multi-tool session, malformed-input recovery, notification suppression, non-zero exit on a missing data file, and the invariant that **stdout carries only protocol frames**.

---

## Protocol notes

- Transport: newline-delimited JSON-RPC 2.0 over stdio, one message per line.
- Methods: `initialize`, `tools/list`, `tools/call`, `ping`. `notifications/*` are accepted and correctly produce no response frame.
- Protocol version: `2025-06-18`; the client's requested version is echoed when it supplies one.
- Tool-level failures (bad arguments) return `isError: true` inside the result so the model can read and self-correct. Protocol-level failures return proper JSON-RPC error codes (`-32700`, `-32600`, `-32601`, `-32602`, `-32603`).
- Diagnostics go to stderr exclusively. stdout is never polluted with non-protocol bytes.

---

## References

1. IEEE Computer Society (2024). *Guide to the Software Engineering Body of Knowledge (SWEBOK) v4.0.* Ed. H. Washizaki. 18 Knowledge Areas.
2. Holzmann, G.J. (2006). *The Power of 10: Rules for Developing Safety-Critical Code.* IEEE Computer 39(6), 95–97.
3. Model Context Protocol specification — <https://modelcontextprotocol.io>
