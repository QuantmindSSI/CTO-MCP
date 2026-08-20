#!/usr/bin/env python3
"""persona-constitution MCP server.

Serves the Oluwaferanmi Oluwagbamila Agentic Engineering Persona
(LLM Operational Constitution v3.0.0) over the Model Context Protocol
stdio transport (newline-delimited JSON-RPC 2.0).

Dependencies: Python 3.9+ standard library (tested on CPython 3.9.6 and
3.14.6), plus `codebase-csi` for the scanner backend. Install into the
project's virtualenv:
    .venv/bin/pip install -e .

Tools exposed:
  get_constitution         Full constitution or a named section.
  get_knowledge_area       One of the 18 SWEBOK v4.0 Knowledge Areas.
  get_power_of_10          A specific NASA Power of 10 rule, or all ten.
  get_verification_gates   The G1-G5 pre-emission verification gates.
  scan_code_for_violations Static scan of code for Zero-Framework-Tolerance
                           violations (scaffold markers, stubs, deferral
                           phrases). CodebaseCSI plus Constitution prose rules.
  review_patch             Diff-aware review of staged or PR changes with
                           changed-line attribution and the C-03 test policy.

Transport contract: one JSON-RPC message per line on stdin/stdout.
Diagnostics go to stderr only; stdout carries protocol frames exclusively.

Data source resolution order for CONSTITUTION.md:
  1. PERSONA_CONSTITUTION_PATH environment variable, if set.
  2. persona_constitution/data/CONSTITUTION.md, shipped inside the package so
     that an installed copy (pip install) carries its own data.
  3. <project root>/data/CONSTITUTION.md - the pre-3.1 layout, still honoured
     so that existing checkouts and configs do not break.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from re import Pattern
from typing import (
    Any,
    Callable,
    TextIO,
)

# The scanner backend lives in a sibling module and depends on `codebase-csi`.
# server.py is launched both as a script (by opencode) and imported as part of
# the package (by the tests), so both import forms must resolve. A missing
# dependency is fatal and reported loudly: a silently degraded scanner would
# report clean results for code it never actually inspected.
try:
    from ._version import __version__
    from .review.engine import review_patch
    from .scanner import scan_code
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from persona_constitution._version import __version__
        from persona_constitution.review.engine import review_patch
        from persona_constitution.scanner import scan_code
    except ImportError as _scanner_error:
        sys.stderr.write(
            "persona-constitution: FATAL - cannot load the scanner backend: "
            f"{_scanner_error}\n"
            "The vendored `codebase_csi` package must be importable. Install "
            "this project into its virtualenv:\n"
            "  .venv/bin/pip install -e .\n"
            "and ensure opencode launches this server with that virtualenv's "
            "python.\n"
        )
        raise SystemExit(1) from _scanner_error

PROTOCOL_VERSION = "2025-06-18"
# Every MCP protocol revision this server implements. The initialize handshake
# echoes the client's requested version only when it is in this set; anything
# else is answered with PROTOCOL_VERSION (the spec's required behaviour:
# offer the latest supported version, never parrot an unknown one).
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18"})
# Version is single-sourced from pyproject.toml via _version.py; a literal
# here would drift from the packaged truth (and did, before 3.3.0).
SERVER_INFO = {"name": "persona-constitution", "version": __version__}
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

# Shipped inside the package, so `pip install` produces a working server.
PACKAGE_DATA_DIR = PACKAGE_ROOT / "data"
DEFAULT_CONSTITUTION_PATH = PACKAGE_DATA_DIR / "CONSTITUTION.md"
DEFAULT_DIRECTIVES_PATH = PACKAGE_DATA_DIR / "DIRECTIVES.md"

# The pre-3.1 location. Kept as a fallback so that a checkout or config still
# pointing at <project root>/data keeps working after the move.
LEGACY_CONSTITUTION_PATH = PROJECT_ROOT / "data" / "CONSTITUTION.md"

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Maps the `section` argument of get_constitution to the exact "## " heading
# prefix in CONSTITUTION.md. Insertion order defines the table-of-contents order.
SECTION_MAP = {
    "preamble": "PREAMBLE",
    "identity": "PART I",
    "anti-deception": "PART II",
    "intelligence-architecture": "PART III",
    "t-shape": "PART IV",
    "swebok": "PART V",
    "consensus-protocol": "PART VI",
    "iteration-protocol": "PART VII",
    "agentic-pathway": "PART VIII",
    "power-of-10": "PART IX",
    "operational-directives": "PART X",
    "knowledge-graph": "APPENDIX A",
    "invariants": "APPENDIX B",
    "references": "REFERENCES",
}

# Renamed section keys. Accepted on input so existing callers keep working, but
# deliberately excluded from SECTION_MAP so they stay out of the advertised enum
# and the table of contents.
DEPRECATED_SECTION_ALIASES = {
    "hive-mind": "consensus-protocol",
}

VERIFICATION_GATES = """THE FIVE VERIFICATION GATES (all must pass before any code output is emitted;
if any gate fails, regenerate from the problem statement - do not patch):

G1 - Executability: If I copy-paste this code into a blank file with the stated
     dependencies, does it run without modification?
G2 - Completeness: Does every function contain a real implementation? Is there a
     single placeholder, TODO, or empty body?
G3 - Correctness: Have I traced the execution path for the happy path? For the
     primary error paths? For the edge cases stated in the problem?
G4 - Dependency Honesty: Does every import, every function call, every referenced
     module actually exist in this output or in a stated, verified dependency?
G5 - Problem Fit: Does this solve the specific problem stated, at the scale stated,
     with the constraints stated? Or did I solve a simpler adjacent problem and
     call it done?

PROHIBITED MARKERS (any occurrence means the output has failed):
- TODO / FIXME / "implement this" / "your code here"
- Function bodies that are only comments, `pass`, `...`, or empty blocks
- "You can extend this to..." / "This is a starting point" / "left as an exercise"
- "... rest of the implementation follows the same pattern"
- Calls to functions never defined; imports of modules never created
- Schemas, configs, or files referenced but never written
- "For a production system, you would want to add..."
"""

# --------------------------------------------------------------------------
# Constitution loading and section extraction
# --------------------------------------------------------------------------


def resolve_constitution_path() -> Path:
    """Return the Path to CONSTITUTION.md.

    Resolution order:
      1. PERSONA_CONSTITUTION_PATH (expanding `~` and relative segments), so the
         data file can live outside the repository entirely.
      2. The copy shipped inside the package, which is what an installed
         (pip install) server uses.
      3. The pre-3.1 <project root>/data location, so older checkouts still work.

    The legacy path is only returned if it actually exists; otherwise the
    packaged path is returned so that the "not found" error names the location
    a correct installation would use.
    """
    override = os.environ.get("PERSONA_CONSTITUTION_PATH")
    if override and override.strip():
        return Path(override).expanduser().resolve()
    if DEFAULT_CONSTITUTION_PATH.is_file():
        return DEFAULT_CONSTITUTION_PATH
    if LEGACY_CONSTITUTION_PATH.is_file():
        return LEGACY_CONSTITUTION_PATH
    return DEFAULT_CONSTITUTION_PATH


def load_constitution(path: str | Path | None = None) -> str:
    """Read CONSTITUTION.md from disk and return its full text.

    Raises FileNotFoundError if absent and ValueError if empty, so a broken
    installation fails loudly and diagnosably rather than serving nothing.
    """
    target = Path(path).expanduser().resolve() if path is not None else resolve_constitution_path()
    if not target.is_file():
        raise FileNotFoundError(
            f"Constitution file not found at {target}. The persona-constitution MCP "
            "server cannot operate without it. Set PERSONA_CONSTITUTION_PATH to "
            "override the location."
        )
    text = target.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Constitution file at {target} is empty.")
    return text


def split_headings(text: str, level: int) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) tuples at the given heading level.

    `level` is 2 for "## " or 3 for "### ". Fenced code blocks are respected:
    heading-like lines inside ``` fences are not treated as headings.
    Complexity: O(n) over the number of lines.
    """
    assert level in (2, 3), "only heading levels 2 and 3 are used"
    prefix = "#" * level + " "
    sections: list[tuple[str, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith(prefix) and not line.startswith("#" * (level + 1)):
            if current_heading is not None:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line[len(prefix) :].strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)
    if current_heading is not None:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return sections


def find_section(text: str, heading_prefix: str) -> str | None:
    """Return 'heading\\n\\nbody' for the level-2 section whose heading starts
    with `heading_prefix`, or None if absent."""
    for heading, body in split_headings(text, 2):
        if heading.upper().startswith(heading_prefix.upper()):
            return f"## {heading}\n\n{body}"
    return None


def find_subsection(text: str, pattern: Pattern[str]) -> str | None:
    """Return 'heading\\n\\nbody' for the first level-3 section whose heading
    matches the compiled regex `pattern`, or None if absent."""
    for heading, body in split_headings(text, 3):
        if pattern.search(heading):
            return f"### {heading}\n\n{body}"
    return None


# --------------------------------------------------------------------------
# Violation scanner
# --------------------------------------------------------------------------
#
# The detection engine lives in scanner.py: a union of CodebaseCSI's
# structural detector of incomplete implementations, the Constitution's own
# prose rules for Class 2 / Class 5 narrative deferral, Python stdlib-AST
# analysis, and - when the optional `ast` extra is installed - the
# constitution-xast tree-sitter engine for brace languages (ast_bridge.py).
#
# Measured on the adversarial 37-case corpus (24 violations, 13 legitimate)
# in tools/benchmark_scanner.py: prose rules alone 24/37 (64%), the shipped
# union 37/37 with the `ast` extra and 30/37 without it (the delta is the
# cases only real tree-sitter parsing can decide). Reproduce with
# `python tools/benchmark_scanner.py`; do not edit these numbers without
# rerunning it.

MAX_SCAN_BYTES = 2_000_000

# Bounds for review_patch payloads (Power of 10 rule 3: bound all resource
# growth). The diff cap absorbs any PR a human could plausibly review; the
# files cap bounds the full-content map that enables AST analysis. Both fail
# loudly with instructions rather than degrading.
MAX_REVIEW_DIFF_CHARS = 10_000_000
MAX_REVIEW_FILES_TOTAL_CHARS = 20_000_000

# Transport-frame ceiling for one newline-delimited JSON-RPC message, sized
# above the largest legitimate tool payload plus JSON-escaping overhead.
# Checked before json.loads so an oversized frame costs one buffered string,
# not a parsed object tree plus handler amplification. (The line itself is
# already in memory by the time we can measure it - bounding the read would
# require abandoning line iteration for manual framing, which is not worth
# the complexity for a stdio transport whose client is a local process
# spending its own memory.)
MAX_MESSAGE_CHARS = 50_000_000


# --------------------------------------------------------------------------
# Tool handlers
# --------------------------------------------------------------------------


def tool_get_constitution(constitution: str, args: dict[str, Any]) -> str:
    """Return the full constitution or one named section."""
    section = args.get("section", "toc")
    if section == "full":
        return constitution
    if section == "toc":
        lines = ["Available sections for get_constitution (use the `section` argument):", ""]
        for key, prefix in SECTION_MAP.items():
            match = find_section(constitution, prefix)
            title = match.splitlines()[0][3:] if match else prefix
            lines.append(f"- {key}: {title}")
        lines.append("- full: the entire constitution document")
        supreme = find_section(constitution, "PREAMBLE")
        if supreme:
            lines.append("")
            lines.append(supreme)
        return "\n".join(lines)
    section = DEPRECATED_SECTION_ALIASES.get(section, section)
    heading_prefix = SECTION_MAP.get(section)
    if heading_prefix is None:
        valid = ", ".join([*SECTION_MAP, "full", "toc"])
        raise ValueError(f"Unknown section '{section}'. Valid values: {valid}")
    result = find_section(constitution, heading_prefix)
    if result is None:
        raise ValueError(
            f"Section '{section}' (heading prefix '{heading_prefix}') not found in constitution file."
        )
    return result


KA_TITLES: dict[int, str] = {
    1: "Software Requirements",
    2: "Software Architecture",
    3: "Software Design",
    4: "Software Construction",
    5: "Software Testing",
    6: "Software Engineering Operations",
    7: "Software Maintenance",
    8: "Software Configuration Management",
    9: "Software Engineering Management",
    10: "Software Engineering Process",
    11: "Software Engineering Models and Methods",
    12: "Software Quality",
    13: "Software Security",
    14: "Software Engineering Professional Practice",
    15: "Software Engineering Economics",
    16: "Computing Foundations",
    17: "Mathematical Foundations",
    18: "Engineering Foundations",
}


def _resolve_ka_number(ka: Any) -> int | None:
    """Map a ka argument (number, digit string, or name substring) to 1-18."""
    if isinstance(ka, (int, float)) and int(ka) == ka:
        return int(ka)
    if not isinstance(ka, str):
        return None
    digits = re.search(r"\d+", ka)
    if digits:
        return int(digits.group())
    needle = ka.strip().lower()
    matches = [n for n, t in KA_TITLES.items() if needle in t.lower()]
    if len(matches) > 1:
        options = ", ".join(f"KA-{n:02d} {KA_TITLES[n]}" for n in matches)
        raise ValueError(f"Ambiguous KA name '{ka}'. Matches: {options}")
    return matches[0] if matches else None


def tool_get_knowledge_area(constitution: str, args: dict[str, Any]) -> str:
    """Return one SWEBOK v4.0 Knowledge Area by number (1-18) or name."""
    ka = args.get("ka")
    if ka is None:
        listing = "\n".join(f"KA-{n:02d} - {t}" for n, t in KA_TITLES.items())
        return "SWEBOK v4.0 defines 18 Knowledge Areas. Pass `ka` as a number (1-18) or a name:\n" + listing
    number = _resolve_ka_number(ka)
    if number is None or not 1 <= number <= 18:
        raise ValueError(f"Invalid ka '{ka}'. Use a number 1-18 or a KA name such as 'Software Security'.")
    pattern = re.compile(rf"^KA-{number:02d}\b")
    result = find_subsection(constitution, pattern)
    if result is None:
        raise ValueError(f"KA-{number:02d} not found in constitution file.")
    return result


def tool_get_power_of_10(constitution: str, args: dict[str, Any]) -> str:
    """Return one Power of 10 rule (1-10) or all ten."""
    rule = args.get("rule")
    part_ix = find_section(constitution, "PART IX")
    if part_ix is None:
        raise ValueError("PART IX (Power of 10) not found in constitution file.")
    if rule is None:
        return part_ix
    try:
        number = int(rule)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid rule '{rule}'. Use an integer 1-10, or omit for all rules.") from exc
    if not 1 <= number <= 10:
        raise ValueError(f"Rule number {number} out of range. Power of 10 rules are numbered 1-10.")
    pattern = re.compile(rf"^Rule {number}\b")
    result = find_subsection(part_ix, pattern)
    if result is None:
        raise ValueError(f"Rule {number} not found in PART IX.")
    return result


def tool_get_verification_gates(constitution: str, args: dict[str, Any]) -> str:  # noqa: ARG001 - uniform handler signature
    """Return the G1-G5 gates plus the prohibited-marker checklist.

    Takes `constitution` and `args` it does not read: every tool handler shares
    one signature so `dispatch` can invoke them without special-casing.
    """
    return VERIFICATION_GATES


def tool_scan_code_for_violations(constitution: str, args: dict[str, Any]) -> str:  # noqa: ARG001 - uniform handler signature
    """Run the static Zero-Framework-Tolerance scan over the supplied code.

    `constitution` is unused: the scan is purely static and needs no corpus.
    """
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Argument 'code' is required and must be a non-empty string.")
    if len(code) > MAX_SCAN_BYTES:
        raise ValueError(
            f"Argument 'code' exceeds the {MAX_SCAN_BYTES // 1_000_000}MB scan limit; scan files individually."
        )
    language = args.get("language")
    if language is not None and not isinstance(language, str):
        raise ValueError("Argument 'language' must be a string when supplied.")
    result = scan_code(code, language=language)
    return json.dumps(result, indent=2)


def _require_string_list(args: dict[str, Any], name: str) -> list[str] | None:
    """Optional array-of-strings argument, validated loudly."""
    value = args.get(name)
    if value is not None and (
        not isinstance(value, list) or any(not isinstance(item, str) for item in value)
    ):
        raise ValueError(f"Argument '{name}' must be an array of glob strings.")
    return value


def _require_files_map(args: dict[str, Any]) -> dict[str, str] | None:
    """Optional path -> content object argument, validated loudly and bounded."""
    files = args.get("files")
    if files is None:
        return None
    if not isinstance(files, dict):
        raise ValueError("Argument 'files' must be an object mapping file paths to file contents.")
    total_chars = 0
    for path, content in files.items():
        if not isinstance(content, str):
            raise ValueError(f"files[{path!r}] must be a string.")
        total_chars += len(content)
    if total_chars > MAX_REVIEW_FILES_TOTAL_CHARS:
        raise ValueError(
            f"Argument 'files' totals {total_chars} characters, over the "
            f"{MAX_REVIEW_FILES_TOTAL_CHARS} limit; supply contents only for the changed files, "
            "or omit 'files' to fall back to fragment scanning."
        )
    return files


def tool_review_patch(constitution: str, args: dict[str, Any]) -> str:  # noqa: ARG001 - uniform handler signature
    """Review a unified diff with the diff-aware constitution gate.

    `constitution` is unused: the review is purely static. The caller (an
    agent driving `gh pr diff`, or the persona-pr-review CLI) supplies the
    diff and, for full fidelity, the new-version file contents; this server
    performs no network I/O by design.
    """
    diff_text = args.get("diff")
    if not isinstance(diff_text, str) or not diff_text.strip():
        raise ValueError("Argument 'diff' is required and must be a non-empty unified diff string.")
    if len(diff_text) > MAX_REVIEW_DIFF_CHARS:
        raise ValueError(
            f"Argument 'diff' is {len(diff_text)} characters, over the {MAX_REVIEW_DIFF_CHARS} "
            "limit; review the change in smaller units."
        )
    require_tests = args.get("require_tests", "off")
    if require_tests not in ("off", "warn", "fail"):
        raise ValueError("Argument 'require_tests' must be one of: off, warn, fail.")
    result = review_patch(
        diff_text,
        file_contents=_require_files_map(args),
        exclude=_require_string_list(args, "exclude"),
        require_tests=require_tests,
        test_globs=_require_string_list(args, "test_globs"),
    )
    return json.dumps(result, indent=2)


TOOLS: dict[str, dict[str, Any]] = {
    "get_constitution": {
        "handler": tool_get_constitution,
        "description": (
            "Retrieve the Agentic Engineering Persona constitution (v3.0.0) that governs all "
            "programming and software development work: SWEBOK v4.0, NASA Power of 10, Zero "
            "Framework Tolerance. Call with no arguments for the table of contents plus the "
            "Supreme Law; pass `section` for a specific part or 'full' for the whole document."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": [*SECTION_MAP, "full", "toc"],
                    "description": "Which section to return. Omit (or 'toc') for the table of contents plus the Preamble/Supreme Law.",
                },
            },
            "additionalProperties": False,
        },
    },
    "get_knowledge_area": {
        "handler": tool_get_knowledge_area,
        "description": (
            "Retrieve one of the 18 SWEBOK v4.0 Knowledge Areas (KA-01 Requirements through "
            "KA-18 Engineering Foundations) including its LLM operational discipline. Pass `ka` "
            "as a number 1-18 or a name (e.g. 'Software Security'). Omit `ka` to list all 18."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ka": {
                    "description": "Knowledge Area number (1-18) or name substring.",
                    "anyOf": [{"type": "integer", "minimum": 1, "maximum": 18}, {"type": "string"}],
                },
            },
            "additionalProperties": False,
        },
    },
    "get_power_of_10": {
        "handler": tool_get_power_of_10,
        "description": (
            "Retrieve NASA/JPL Power of 10 rules (Holzmann 2006) with the persona's code-level, "
            "architecture-level, and organisational-level applications. Pass `rule` (1-10) for "
            "one rule, or omit for all ten."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "rule": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Rule number 1-10. Omit for all rules.",
                },
            },
            "additionalProperties": False,
        },
    },
    "get_verification_gates": {
        "handler": tool_get_verification_gates,
        "description": (
            "Retrieve the five pre-emission verification gates (G1 Executability, G2 Completeness, "
            "G3 Correctness, G4 Dependency Honesty, G5 Problem Fit) and the prohibited-marker "
            "checklist. Run these gates before delivering any code output."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "scan_code_for_violations": {
        "handler": tool_scan_code_for_violations,
        "description": (
            "Statically scan code for Zero-Framework-Tolerance violations: TODO/FIXME markers, "
            "stub bodies (pass, ellipsis, NotImplementedError, unimplemented macros, panic stubs), "
            "empty function and catch "
            "bodies across Python, JavaScript, TypeScript, Java, Go and Rust, scaffold deception "
            "phrases ('rest of the implementation', 'omitted for brevity'), and iteration-deferral "
            "phrases ('left as an exercise', 'you can extend this'). Backed by the CodebaseCSI "
            "forensic detector plus Constitution prose rules; Python input additionally gets AST "
            "analysis so abstract stubs (Protocol/ABC/@abstractmethod) and markers inside string "
            "literals are not falsely flagged. Returns a JSON verdict (PASS/REVIEW/FAIL) with "
            "line-numbered findings. Use before delivering generated code. A PASS is necessary "
            "but not sufficient - still run gates G1-G5."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "The complete code to scan."},
                "language": {
                    "type": "string",
                    "description": (
                        "Optional language hint, e.g. 'python', 'javascript', 'typescript', 'java', "
                        "'go', 'rust'. Selects the string-masking strategy and enables Python AST "
                        "analysis. Omit to infer automatically."
                    ),
                },
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    "review_patch": {
        "handler": tool_review_patch,
        "description": (
            "Review a unified diff (git diff / gh pr diff output) against the Zero-Framework-"
            "Tolerance rules. Every changed code file is scanned with the full engine union "
            "(CodebaseCSI, constitution prose rules, Python AST, tree-sitter xast) and findings "
            "are attributed to the lines the change introduces; pre-existing debt in touched "
            "files is counted separately and never fails the gate. Supply `files` (path -> full "
            "new-version content) for full-fidelity AST analysis; without it, added lines are "
            "scanned as fragments. Returns JSON: verdict (FAIL/REVIEW/PASS), per-file findings "
            "with new-file line numbers, totals, and the engines that ran. Deterministic and "
            "offline: fetch the diff yourself (e.g. `gh pr diff`) and post reviews yourself. A "
            "PASS gates nothing but markers - gates G1-G5 remain the reviewer's responsibility."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff": {
                    "type": "string",
                    "description": "Unified diff text, e.g. from `git diff` or `gh pr diff`.",
                },
                "files": {
                    "type": "object",
                    "description": (
                        "Optional map of changed-file path (new version) to its complete file "
                        "content, enabling full-file AST analysis instead of fragment scanning."
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional fnmatch globs for paths the gate must not judge: detector rule "
                        "definitions and test fixture corpora contain hunted patterns as data."
                    ),
                },
                "require_tests": {
                    "type": "string",
                    "enum": ["off", "warn", "fail"],
                    "description": (
                        "C-03 enforcement: flag production-logic changes when the diff touches no "
                        "test files. 'warn' surfaces them for judgement, 'fail' gates the verdict. "
                        "Default off; the reviewing agent should normally pass 'warn'."
                    ),
                },
                "test_globs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Project-specific test path globs added to the built-in conventions "
                        "(tests/*, test_*.py, *.spec.ts, *_test.go, ...)."
                    ),
                },
            },
            "required": ["diff"],
            "additionalProperties": False,
        },
    },
}


# --------------------------------------------------------------------------
# JSON-RPC 2.0 / MCP protocol layer
# --------------------------------------------------------------------------


def make_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_initialize(params: dict[str, Any], request_id: Any, _constitution: str) -> dict[str, Any]:
    client_version = params.get("protocolVersion")
    # Echo the client's version only when this server actually implements it;
    # for unknown or malformed values, offer the latest version we support.
    version = client_version if client_version in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
    return make_result(
        request_id,
        {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "This server carries the Agentic Engineering Persona constitution governing all "
                "programming tasks. Core mandate: every code output must be complete, executable, "
                "and correct - no placeholders, no TODOs, no scaffolds. Use scan_code_for_violations "
                "on generated code and get_verification_gates before delivery."
            ),
        },
    )


def handle_tools_list(_params: dict[str, Any], request_id: Any, _constitution: str) -> dict[str, Any]:
    tools = [
        {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
        for name, spec in TOOLS.items()
    ]
    return make_result(request_id, {"tools": tools})


def handle_tools_call(params: dict[str, Any], request_id: Any, constitution: str) -> dict[str, Any]:
    name = params.get("name")
    # isinstance, not a bare dict lookup: an unhashable name (a list, say)
    # would raise inside dict.get and surface as INTERNAL_ERROR; a caller
    # mistake must always be INVALID_PARAMS.
    if not isinstance(name, str) or name not in TOOLS:
        return make_error(request_id, INVALID_PARAMS, f"Unknown tool: {name!r}")
    spec = TOOLS[name]
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return make_error(request_id, INVALID_PARAMS, "Tool arguments must be an object.")
    try:
        text = spec["handler"](constitution, arguments)
        return make_result(request_id, {"content": [{"type": "text", "text": text}], "isError": False})
    except ValueError as exc:
        # Tool-level errors are reported inside the result per MCP convention,
        # so the model can read and correct its arguments.
        return make_result(
            request_id, {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
        )


def handle_ping(_params: dict[str, Any], request_id: Any, _constitution: str) -> dict[str, Any]:
    return make_result(request_id, {})


REQUEST_HANDLERS: dict[str, Callable[[dict[str, Any], Any, str], dict[str, Any]]] = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "ping": handle_ping,
}


def _route(message: dict[str, Any], constitution: str) -> dict[str, Any] | None:
    """Resolve and invoke the handler for a well-formed message.

    Unknown methods - including the notifications/* family, which this
    server has no handlers for - uniformly produce METHOD_NOT_FOUND here;
    dispatch() then discards the response when the message carried no id.
    That split keeps the JSON-RPC contract exact in both directions: an
    id-less notification gets silence, while a client that attaches an id
    to notifications/initialized has sent a request and gets its answer."""
    method = message["method"]
    request_id = message.get("id")
    handler = REQUEST_HANDLERS.get(method)
    if handler is None:
        return make_error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return make_error(request_id, INVALID_PARAMS, "params must be an object.")
    try:
        return handler(params, request_id, constitution)
    except Exception as exc:  # noqa: BLE001 - protocol boundary: convert to JSON-RPC error, never crash the transport.
        print(f"persona-constitution internal error in {method}: {exc}", file=sys.stderr, flush=True)
        return make_error(request_id, INTERNAL_ERROR, f"Internal error: {exc}")


def dispatch(message: Any, constitution: str) -> dict[str, Any] | None:
    """Route one parsed JSON-RPC message. Returns a response dict or None.

    Silence is reserved for well-formed notifications: a dict with
    jsonrpc "2.0", a string method, and no id. A malformed object cannot
    be trusted to be a notification - the missing id may itself be part of
    the malformation - so it gets an id-null Invalid Request response,
    exactly as the JSON-RPC 2.0 specification's own examples answer
    `{"jsonrpc": "2.0", "method": 1}`."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return make_error(
            message.get("id") if isinstance(message, dict) else None,
            INVALID_REQUEST,
            "Not a valid JSON-RPC 2.0 message.",
        )
    if not isinstance(message.get("method"), str):
        return make_error(message.get("id"), INVALID_REQUEST, "Missing method.")
    response = _route(message, constitution)
    return None if "id" not in message else response


def _debug_line(method: str, tool: str, frame_chars: int, response_chars: int, elapsed_ms: float) -> None:
    """One structured diagnostics line on stderr.

    Sizes and durations only, never payload content: the code this server
    scans is other people's unreleased work and must not leak into logs.
    key=value tokens so the output greps and parses trivially.
    """
    print(
        f"persona-constitution debug: method={method} tool={tool} "
        f"frame_chars={frame_chars} response_chars={response_chars} "
        f"elapsed_ms={elapsed_ms:.1f}",
        file=sys.stderr,
        flush=True,
    )


def _write_response(stdout: TextIO, response: dict[str, Any]) -> str:
    """Serialise one response, write it as a frame, flush so the client
    never blocks on a buffered reply. Returns the encoded text (for size
    diagnostics)."""
    encoded = json.dumps(response)
    stdout.write(encoded + "\n")
    stdout.flush()
    return encoded


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000.0


def _frame_identity(message: Any) -> tuple[str, str]:
    """(method, tool) labels for diagnostics; malformed frames get fixed
    fallback labels so the log line always has the same shape."""
    method = message.get("method") if isinstance(message, dict) else None
    method_label = method if isinstance(method, str) and method else "<invalid>"
    tool = "-"
    if method == "tools/call" and isinstance(message.get("params"), dict):
        requested = message["params"].get("name")
        if isinstance(requested, str) and requested:
            tool = requested
    return method_label, tool


def _serve_one(raw_line: str, stdout: TextIO, constitution: str, debug: bool) -> None:
    """Process one raw input line end to end: bound it, parse it, dispatch
    it, answer it, and (in debug mode) account for it on stderr."""
    started = time.monotonic()
    if len(raw_line) > MAX_MESSAGE_CHARS:
        encoded = _write_response(
            stdout,
            make_error(
                None,
                INVALID_REQUEST,
                f"Message of {len(raw_line)} characters exceeds the "
                f"{MAX_MESSAGE_CHARS} character frame limit.",
            ),
        )
        if debug:
            _debug_line("<oversized>", "-", len(raw_line), len(encoded), _elapsed_ms(started))
        return
    line = raw_line.strip()
    if not line:
        return
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        encoded = _write_response(stdout, make_error(None, PARSE_ERROR, f"Parse error: {exc}"))
        if debug:
            _debug_line("<unparseable>", "-", len(raw_line), len(encoded), _elapsed_ms(started))
        return
    response = dispatch(message, constitution)
    encoded = _write_response(stdout, response) if response is not None else ""
    if debug:
        method_label, tool = _frame_identity(message)
        _debug_line(method_label, tool, len(raw_line), len(encoded), _elapsed_ms(started))


def serve(stdin: Iterable[str], stdout: TextIO, constitution: str, debug: bool = False) -> None:
    """Read newline-delimited JSON-RPC messages from `stdin`, write responses
    to `stdout`, until `stdin` reaches EOF.

    With `debug` enabled, every frame produces one stderr line with the
    method, the tool (for tools/call), the frame and response sizes, and the
    wall-clock cost - enough to diagnose a slow or failing integration at a
    customer site without ever logging the payloads themselves."""
    for raw_line in stdin:
        _serve_one(raw_line, stdout, constitution, debug)


def _debug_enabled(argv: Sequence[str], environ: Mapping[str, str]) -> bool:
    """Diagnostics opt-in: the --debug flag or a truthy env var. Both exist
    because MCP hosts differ in which of args and env they let users set."""
    if "--debug" in argv:
        return True
    return environ.get("PERSONA_CONSTITUTION_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def main() -> None:
    """Serve MCP over stdio until stdin closes. Never writes non-protocol bytes
    to stdout; diagnostics go to stderr. Exits 1 on unusable installation."""
    try:
        constitution = load_constitution()
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"persona-constitution fatal: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    debug = _debug_enabled(sys.argv[1:], os.environ)
    if debug:
        print(
            f"persona-constitution debug: serving version={SERVER_INFO['version']} "
            f"protocol={PROTOCOL_VERSION} pid={os.getpid()}",
            file=sys.stderr,
            flush=True,
        )
    try:
        serve(sys.stdin, sys.stdout, constitution, debug=debug)
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        # Client closed the transport mid-write; shut down quietly.
        sys.exit(0)


if __name__ == "__main__":
    main()
