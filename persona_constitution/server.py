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
                           violations (placeholders, stubs, deferral phrases).
                           Backed by CodebaseCSI plus Constitution prose rules.

Transport contract: one JSON-RPC message per line on stdin/stdout.
Diagnostics go to stderr only; stdout carries protocol frames exclusively.

Data source resolution order for CONSTITUTION.md:
  1. PERSONA_CONSTITUTION_PATH environment variable, if set.
  2. persona_constitution/data/CONSTITUTION.md, shipped inside the package so
     that an installed copy (pip install) carries its own data.
  3. <project root>/data/CONSTITUTION.md - the pre-3.1 layout, still honoured
     so that existing checkouts and configs do not break.
"""

import json
import os
import re
import sys
from pathlib import Path

# The scanner backend lives in a sibling module and depends on `codebase-csi`.
# server.py is launched both as a script (by opencode) and imported as part of
# the package (by the tests), so both import forms must resolve. A missing
# dependency is fatal and reported loudly: a silently degraded scanner would
# report clean results for code it never actually inspected.
try:
    from .scanner import scan_code
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from persona_constitution.scanner import scan_code
    except ImportError as _scanner_error:
        sys.stderr.write(
            "persona-constitution: FATAL - cannot load the scanner backend: "
            f"{_scanner_error}\n"
            "The `codebase-csi` package is required. Install it with:\n"
            "  .venv/bin/pip install 'codebase-csi @ "
            "git+https://github.com/Thundastormgod/CodebaseCSI.git@main'\n"
            "and ensure opencode launches this server with that virtualenv's "
            "python.\n"
        )
        raise SystemExit(1) from _scanner_error

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "persona-constitution", "version": "3.0.0"}
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


def resolve_constitution_path():
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


def load_constitution(path=None):
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


def split_headings(text, level):
    """Split markdown into (heading, body) tuples at the given heading level.

    `level` is 2 for "## " or 3 for "### ". Fenced code blocks are respected:
    heading-like lines inside ``` fences are not treated as headings.
    Complexity: O(n) over the number of lines.
    """
    assert level in (2, 3), "only heading levels 2 and 3 are used"
    prefix = "#" * level + " "
    sections = []
    current_heading = None
    current_lines = []
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


def find_section(text, heading_prefix):
    """Return 'heading\\n\\nbody' for the level-2 section whose heading starts
    with `heading_prefix`, or None if absent."""
    for heading, body in split_headings(text, 2):
        if heading.upper().startswith(heading_prefix.upper()):
            return f"## {heading}\n\n{body}"
    return None


def find_subsection(text, pattern):
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
# MockCodeDetector (structural stub/mock detection) and the Constitution's
# own prose rules for Class 2 / Class 5 narrative deferral, which CSI does
# not model. `scan_code` is imported at module load; the rules themselves
# live in scanner.py and are re-exported from the package __init__.
#
# Measured on the adversarial 27-case corpus in tools/benchmark_scanner.py:
# CodebaseCSI alone 13/27 (48%), prose rules alone 20/27 (74%), the union
# 26/27 (96%). Reproduce with `python tools/benchmark_scanner.py`; do not
# edit these numbers without rerunning it.

MAX_SCAN_BYTES = 2_000_000


# --------------------------------------------------------------------------
# Tool handlers
# --------------------------------------------------------------------------


def tool_get_constitution(constitution, args):
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
    prefix = SECTION_MAP.get(section)
    if prefix is None:
        valid = ", ".join([*SECTION_MAP, "full", "toc"])
        raise ValueError(f"Unknown section '{section}'. Valid values: {valid}")
    result = find_section(constitution, prefix)
    if result is None:
        raise ValueError(f"Section '{section}' (heading prefix '{prefix}') not found in constitution file.")
    return result


KA_TITLES = {
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


def tool_get_knowledge_area(constitution, args):
    """Return one SWEBOK v4.0 Knowledge Area by number (1-18) or name."""
    ka = args.get("ka")
    if ka is None:
        listing = "\n".join(f"KA-{n:02d} - {t}" for n, t in KA_TITLES.items())
        return "SWEBOK v4.0 defines 18 Knowledge Areas. Pass `ka` as a number (1-18) or a name:\n" + listing
    number = None
    if isinstance(ka, (int, float)) and int(ka) == ka:
        number = int(ka)
    elif isinstance(ka, str):
        digits = re.search(r"\d+", ka)
        if digits:
            number = int(digits.group())
        else:
            needle = ka.strip().lower()
            matches = [n for n, t in KA_TITLES.items() if needle in t.lower()]
            if len(matches) == 1:
                number = matches[0]
            elif len(matches) > 1:
                options = ", ".join(f"KA-{n:02d} {KA_TITLES[n]}" for n in matches)
                raise ValueError(f"Ambiguous KA name '{ka}'. Matches: {options}")
    if number is None or not 1 <= number <= 18:
        raise ValueError(f"Invalid ka '{ka}'. Use a number 1-18 or a KA name such as 'Software Security'.")
    pattern = re.compile(rf"^KA-{number:02d}\b")
    result = find_subsection(constitution, pattern)
    if result is None:
        raise ValueError(f"KA-{number:02d} not found in constitution file.")
    return result


def tool_get_power_of_10(constitution, args):
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


def tool_get_verification_gates(constitution, args):  # noqa: ARG001 - uniform handler signature
    """Return the G1-G5 gates plus the prohibited-marker checklist.

    Takes `constitution` and `args` it does not read: every tool handler shares
    one signature so `dispatch` can invoke them without special-casing.
    """
    return VERIFICATION_GATES


def tool_scan_code_for_violations(constitution, args):  # noqa: ARG001 - uniform handler signature
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


TOOLS = {
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
            "stub bodies (pass/.../NotImplementedError/todo!()/panic()), empty function and catch "
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
}


# --------------------------------------------------------------------------
# JSON-RPC 2.0 / MCP protocol layer
# --------------------------------------------------------------------------


def make_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_initialize(params, request_id, _constitution):
    client_version = params.get("protocolVersion", PROTOCOL_VERSION)
    # Echo the client's requested version when it is a string; otherwise offer ours.
    version = client_version if isinstance(client_version, str) else PROTOCOL_VERSION
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


def handle_tools_list(_params, request_id, _constitution):
    tools = [
        {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
        for name, spec in TOOLS.items()
    ]
    return make_result(request_id, {"tools": tools})


def handle_tools_call(params, request_id, constitution):
    name = params.get("name")
    spec = TOOLS.get(name)
    if spec is None:
        return make_error(request_id, INVALID_PARAMS, f"Unknown tool: {name!r}")
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


def handle_ping(_params, request_id, _constitution):
    return make_result(request_id, {})


REQUEST_HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "ping": handle_ping,
}


def dispatch(message, constitution):
    """Route one parsed JSON-RPC message. Returns a response dict or None
    (None for notifications, which must not receive responses)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return make_error(
            message.get("id") if isinstance(message, dict) else None,
            INVALID_REQUEST,
            "Not a valid JSON-RPC 2.0 message.",
        )
    method = message.get("method")
    request_id = message.get("id")
    is_notification = "id" not in message
    if not isinstance(method, str):
        return None if is_notification else make_error(request_id, INVALID_REQUEST, "Missing method.")
    if method.startswith("notifications/"):
        return None
    handler = REQUEST_HANDLERS.get(method)
    if handler is None:
        return (
            None
            if is_notification
            else make_error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        )
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return make_error(request_id, INVALID_PARAMS, "params must be an object.")
    try:
        response = handler(params, request_id, constitution)
        return None if is_notification else response
    except Exception as exc:  # noqa: BLE001 - protocol boundary: convert to JSON-RPC error, never crash the transport.
        print(f"persona-constitution internal error in {method}: {exc}", file=sys.stderr, flush=True)
        return None if is_notification else make_error(request_id, INTERNAL_ERROR, f"Internal error: {exc}")


def serve(stdin, stdout, constitution):
    """Read newline-delimited JSON-RPC messages from `stdin`, write responses
    to `stdout`, until `stdin` reaches EOF. Flushes after every response so the
    client never blocks on a buffered reply."""
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            stdout.write(json.dumps(make_error(None, PARSE_ERROR, f"Parse error: {exc}")) + "\n")
            stdout.flush()
            continue
        response = dispatch(message, constitution)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


def main():
    """Serve MCP over stdio until stdin closes. Never writes non-protocol bytes
    to stdout; diagnostics go to stderr. Exits 1 on unusable installation."""
    try:
        constitution = load_constitution()
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"persona-constitution fatal: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    try:
        serve(sys.stdin, sys.stdout, constitution)
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        # Client closed the transport mid-write; shut down quietly.
        sys.exit(0)


if __name__ == "__main__":
    main()
