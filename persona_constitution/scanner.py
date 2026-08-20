"""Zero-Framework-Tolerance scanner: CodebaseCSI + Constitution prose rules.

This module is the detection backend for the `scan_code_for_violations` MCP
tool. It is a union of two complementary engines:

  1. CodebaseCSI's `MockCodeDetector` - structural detection of stubs, mock
     implementations, always-success functions, print-only bodies, fake data,
     pass-through functions and TODO markers. Sourced from
     https://github.com/Thundastormgod/CodebaseCSI (MIT).

  2. Constitution prose rules - Class 2 (Scaffold Deception) and Class 5
     (Iteration Deferral) narrative-deferral phrases, plus brace-language
     structural stubs. CodebaseCSI models none of these.

Neither engine alone is sufficient: measured against an 18-case adversarial
corpus, CSI scored 9/18 and the prose rules alone scored 3/18. They fail on
disjoint cases, so the union strictly dominates either.

Non-Python inputs additionally receive `constitution-xast` analysis
(ast_bridge.py): the vendored CodebaseCSI tree-sitter tier parses the source
and the structural stub rules are evaluated on real AST nodes, which lets
judgements regex must leave at warning severity (a body that is a single
hardcoded `return null;`) be made exactly and emitted as violations. The
engine is active only when the optional `ast` extra is installed and the
input parses cleanly; otherwise the regex tier stands alone, unchanged.

Python inputs additionally receive AST-aware analysis, which supplies two
things regex cannot:

  * Suppression of marker matches that occur inside ordinary string literals
    (so a linter containing `if "TODO" in line:` is not itself flagged), while
    preserving matches inside comments and docstrings, where a TODO genuinely
    is deferred work.

  * Recognition of legitimate abstract stubs. A body of `...` or `pass` is a
    violation in a concrete function but is correct in a `typing.Protocol`, an
    ABC, or under `@abstractmethod` / `@overload`.

The scanner is a necessary but not sufficient check. It cannot prove
executability, correctness, or dependency honesty; gates G1-G5 still apply.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from re import Pattern
from typing import Any

from codebase_csi.analyzers.mock_detector import MockCodeDetector

# Every way CPython's parser refuses input. SyntaxError and ValueError are
# the documented refusals; MemoryError is the parser-stack overflow raised
# by 3.12+ on pathologically deep expressions ("Parser stack overflowed"),
# and RecursionError is the same failure on older interpreters. All four
# mean exactly one thing here: this text is not analysable as Python, so
# the scan proceeds with the non-AST engines instead of crashing.
# Found by the adversarial corpus in tests/test_scan_budget.py: the
# modifier-keyword flood killed scan_code with MemoryError on CPython 3.12.
PARSER_REFUSALS = (SyntaxError, ValueError, MemoryError, RecursionError)

try:
    from .ast_bridge import xast_findings
    from .logic_rules import python_logic_findings
except ImportError:  # pragma: no cover - direct module execution
    from persona_constitution.ast_bridge import xast_findings
    from persona_constitution.logic_rules import python_logic_findings

# One finding in the scanner's JSON schema; one prose rule entry:
# (compiled pattern, failure class, message, severity, category, CWE).
# The CWE is a MITRE weakness ID attached only where the mapping is
# defensible - None means "no honest mapping exists", never "forgot".
Finding = dict[str, Any]
Span = tuple[int, int]
ProseRule = tuple["Pattern[str]", str, str, str, str, "str | None"]

# Constitution failure classes.
CLASS_FRAMEWORK = "Class 1 - Framework Generation"
CLASS_SCAFFOLD = "Class 2 - Scaffold Deception"
CLASS_CONFIDENCE = "Class 3 - Confidence Mismatch"
CLASS_DEFERRAL = "Class 5 - Iteration Deferral"

# A single detector instance is reused; MockCodeDetector holds only compiled
# regexes and is safe to share across calls.
_CSI_DETECTOR = MockCodeDetector()

# CodebaseCSI pattern_type prefix -> Constitution failure class.
_CSI_CLASS_BY_PREFIX = (
    ("stub", CLASS_FRAMEWORK),
    ("placeholder", CLASS_FRAMEWORK),
    ("todo", CLASS_FRAMEWORK),
    ("empty", CLASS_FRAMEWORK),
    ("mock", CLASS_FRAMEWORK),
    ("fake", CLASS_FRAMEWORK),
    ("print_only", CLASS_FRAMEWORK),
    ("passthrough", CLASS_FRAMEWORK),
    ("pass_through", CLASS_FRAMEWORK),
    ("always_success", CLASS_CONFIDENCE),
)

# Markers whose appearance inside a *data* string literal is not a deferral.
# These are suppressed by the Python string-span mask; matches in comments and
# docstrings survive.
_SUPPRESSIBLE_IN_STRINGS = frozenset({"marker", "prose"})

# CodebaseCSI pattern_type prefix -> CWE, for the prefixes with a defensible
# mapping. mock/fake/passthrough/always_success are deliberately absent:
# MITRE has no precise weakness for them and a wrong ID is worse than none.
_CSI_CWE_BY_PREFIX = (
    ("todo", "CWE-546"),  # Suspicious Comment
    ("empty", "CWE-1071"),  # Empty Code Block
    ("stub", "CWE-684"),  # Incorrect Provision of Specified Functionality
    ("placeholder", "CWE-684"),
    ("print_only", "CWE-489"),  # Active Debug Code
)


def _csi_cwe(pattern_type: str | None) -> str | None:
    """CWE for a CodebaseCSI pattern_type, or None when no honest mapping exists."""
    lowered = (pattern_type or "").lower()
    for prefix, cwe in _CSI_CWE_BY_PREFIX:
        if lowered.startswith(prefix):
            return cwe
    return None


def _csi_failure_class(pattern_type: str | None) -> str:
    """Map a CodebaseCSI pattern_type onto a Constitution failure class."""
    lowered = (pattern_type or "").lower()
    for prefix, failure_class in _CSI_CLASS_BY_PREFIX:
        if lowered.startswith(prefix):
            return failure_class
    return CLASS_FRAMEWORK


def _csi_severity(severity: str | None, confidence: float | None) -> str:
    """Collapse CodebaseCSI's 4-level severity onto violation/warning.

    CRITICAL and HIGH are unambiguous. MEDIUM is promoted to a violation only
    when the detector is at least 85% confident, which keeps low-confidence
    heuristics (fake-data and naming guesses) advisory rather than fatal.
    """
    upper = (severity or "").upper()
    if upper in ("CRITICAL", "HIGH"):
        return "violation"
    if upper == "MEDIUM" and (confidence or 0.0) >= 0.85:
        return "violation"
    return "warning"


# --------------------------------------------------------------------------
# Prose and structural rules that CodebaseCSI does not model
# --------------------------------------------------------------------------

# Each rule: (compiled regex, failure class, description, severity, kind, cwe).
# `kind` drives string-literal suppression: "prose" and "marker" rules are
# suppressed inside data strings, "structure" rules are always evaluated.
# CWE choices: prose/marker deferral text is CWE-546 (Suspicious Comment);
# empty bodies are CWE-1071 (Empty Code Block); empty catches CWE-1069
# (Empty Exception Block); stub bodies that fake their contract are
# CWE-684 (Incorrect Provision of Specified Functionality).
PROSE_RULES: list[ProseRule] = [
    # -- Class 2: Scaffold Deception -------------------------------------
    (
        re.compile(r"rest\s+of\s+the\s+(?:implementation|code|file|logic|method|function)", re.IGNORECASE),
        CLASS_SCAFFOLD,
        "'rest of the implementation ...' - code omitted",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"follows?\s+the\s+same\s+pattern", re.IGNORECASE),
        CLASS_SCAFFOLD,
        "'follows the same pattern' - code omitted by analogy",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(
            r"(?:omitted|elided|truncated|abbreviated|snipped|skipped)\s+for\s+brevity", re.IGNORECASE
        ),
        CLASS_SCAFFOLD,
        "Content omitted 'for brevity'",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"for\s+brevity[,\s]+(?:the\s+)?(?:rest|remainder|others?|implementation)", re.IGNORECASE),
        CLASS_SCAFFOLD,
        "Content omitted 'for brevity'",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"and\s+so\s+on\s+for\s+the\s+(?:rest|others|remaining)", re.IGNORECASE),
        CLASS_SCAFFOLD,
        "'and so on for the rest' - enumeration left unwritten",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"(?:similar|same)\s+(?:for|logic\s+for)\s+the\s+(?:other|remaining|rest)", re.IGNORECASE),
        CLASS_SCAFFOLD,
        "'similar for the others' - code omitted by analogy",
        "violation",
        "prose",
        "CWE-546",
    ),
    # -- Class 5: Iteration Deferral -------------------------------------
    (
        re.compile(r"left\s+as\s+an\s+exercise", re.IGNORECASE),
        CLASS_DEFERRAL,
        "'left as an exercise' - work pushed to the reader",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"you\s+can\s+(?:extend|expand|build\s+on|adapt)\s+this", re.IGNORECASE),
        CLASS_DEFERRAL,
        "'you can extend this' - verbal handoff instead of implementation",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"(?:this\s+is\s+(?:just\s+)?a|as\s+a)\s+(?:good\s+)?starting\s+point", re.IGNORECASE),
        CLASS_DEFERRAL,
        "'starting point' framing - partial solution offered as complete",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"you\s+(?:would|will|may|might|could)\s+want\s+to\s+add", re.IGNORECASE),
        CLASS_DEFERRAL,
        "'you would want to add ...' - known gap left open",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"(?:full|complete|real|actual|production)\s+implementation\s+would", re.IGNORECASE),
        CLASS_DEFERRAL,
        "'the full implementation would ...' - admission of incompleteness",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"in\s+(?:a\s+)?production[,\s]+you\s+(?:would|should|d\b)", re.IGNORECASE),
        CLASS_DEFERRAL,
        "'in production you would ...' - non-production code delivered",
        "violation",
        "prose",
        "CWE-546",
    ),
    (
        re.compile(r"\bXXX\b"),
        CLASS_FRAMEWORK,
        "XXX marker: unresolved issue left in code",
        "warning",
        "marker",
        "CWE-546",
    ),
    (
        re.compile(
            r"(?://|#|/\*|<!--|--)\s*(?:implement|add|insert|write|fill)\b.{0,40}\b(?:logic|code|here|this|later|in)\b",
            re.IGNORECASE,
        ),
        CLASS_FRAMEWORK,
        "Comment describing unwritten implementation",
        "violation",
        "marker",
        "CWE-546",
    ),
    (
        re.compile(r"your\s+code\s+(?:goes\s+)?here", re.IGNORECASE),
        CLASS_FRAMEWORK,
        "'your code here' placeholder",
        "violation",
        "marker",
        "CWE-546",
    ),
    # -- Structural stubs in brace languages (CSI is Python-centric) ------
    (
        # `def` is deliberately absent: Python empty bodies are the stdlib-AST
        # engine's jurisdiction and Ruby's braceless `def` can never match a
        # brace pattern, while a Python function whose body merely contains a
        # `{}` literal would false-positive here.
        re.compile(r"\b(?:func|function|fn)\s+\w+\s*\([^)]*\)[^{;]*\{[\s\n]*\}"),
        CLASS_FRAMEWORK,
        "Function declared with an entirely empty body",
        "violation",
        "structure",
        "CWE-1071",
    ),
    (
        re.compile(
            r"(?m)^[ \t]*(?:(?:public|private|protected|internal|static|final|override|async|virtual)\s+)+"
            r"[\w<>\[\],.?]+\s+\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\{[\s\n]*\}"
        ),
        CLASS_FRAMEWORK,
        "Method declared with an entirely empty body",
        "violation",
        "structure",
        "CWE-1071",
    ),
    (
        re.compile(r"\{[\s\n]*return\s+(?:null|nil|undefined|None|0|\"\"|''|false|true)\s*;?[\s\n]*\}"),
        CLASS_FRAMEWORK,
        "Function body is a single hardcoded return - no implementation",
        "warning",
        "structure",
        "CWE-684",
    ),
    (
        # The block-comment arm is deliberately bounded and unrolled
        # (/\*[^*]{0,120}(\*(?!/)[^*]{0,120}){0,6}\*/) instead of the obvious
        # /\*.*?\*/ with DOTALL: the lazy scan re-reads to end-of-input for
        # every unclosed "catch {/*" occurrence, which is quadratic - a 1MB
        # adversarial file hung the scanner for minutes (measured; see
        # tests/test_scan_budget.py). The bound means a comment inside an
        # empty catch is recognised up to ~840 characters, which covers any
        # honest "deliberately ignored" note; a longer comment stops the
        # block matching as empty, a miss we accept for immunity to
        # catastrophic scanning.
        re.compile(
            r"catch\s*(?:\([^)]*\))?\s*\{[\s\n]*"
            r"(?:/\*[^*]{0,120}(?:\*(?!/)[^*]{0,120}){0,6}\*/|//[^\n]*)?"
            r"[\s\n]*\}"
        ),
        CLASS_CONFIDENCE,
        "Empty catch block: silently swallowed exception",
        "violation",
        "structure",
        "CWE-1069",
    ),
    (
        re.compile(
            r"throw\s+new\s+\w*(?:Error|Exception)\s*\(\s*['\"][^'\"]*"
            r"(?:not\s*implemented|unimplemented|not\s*supported|TODO)",
            re.IGNORECASE,
        ),
        CLASS_FRAMEWORK,
        "'not implemented' exception stub",
        "violation",
        "structure",
        "CWE-684",
    ),
    (
        re.compile(r"panic\s*\(\s*[\"`][^\"`]*(?:not\s*implemented|unimplemented|TODO)", re.IGNORECASE),
        CLASS_FRAMEWORK,
        "Go panic() used as an unimplemented stub",
        "violation",
        "structure",
        "CWE-684",
    ),
    (
        re.compile(r"\b(?:unimplemented!|todo!)\s*\("),
        CLASS_FRAMEWORK,
        "Rust unimplemented!()/todo!() macro stub",
        "violation",
        "structure",
        "CWE-684",
    ),
]


# --------------------------------------------------------------------------
# Python AST and token analysis
# --------------------------------------------------------------------------


def _line_offsets(code: str) -> list[int]:
    """Return a list mapping 1-based line number to its start char offset."""
    offsets = [0, 0]
    for line in code.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _python_data_string_spans(code: str) -> list[Span]:
    """Return char spans of Python string literals that are not docstrings.

    Docstrings are excluded from the mask deliberately: a TODO written in a
    docstring is deferred work and must still be reported. A TODO inside an
    ordinary string literal is data, not a deferral.

    Returns an empty list if the source cannot be tokenized, which degrades
    the scan to unsuppressed regex matching rather than losing detection.
    """
    try:
        tree = ast.parse(code)
    except PARSER_REFUSALS:
        return []

    docstring_spans = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_spans.add((first.value.lineno, first.value.col_offset))

    offsets = _line_offsets(code)
    spans = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(code).readline)
        for tok in tokens:
            if tok.type != tokenize.STRING:
                continue
            if (tok.start[0], tok.start[1]) in docstring_spans:
                continue
            start_row, start_col = tok.start
            end_row, end_col = tok.end
            if start_row >= len(offsets) or end_row >= len(offsets):
                continue
            spans.append((offsets[start_row] + start_col, offsets[end_row] + end_col))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return []
    return spans


def _generic_data_string_spans(code: str) -> list[Span]:
    """Return char spans of quoted string literals for non-Python sources.

    This is a lexical approximation: it tracks single, double and backtick
    quoting with backslash escapes, and does not attempt to understand
    comments, regex literals, or heredocs. It is used only to suppress marker
    matches, so an inaccuracy costs at most one extra or one missing advisory.
    """
    spans = []
    index = 0
    length = len(code)
    while index < length:
        char = code[index]
        if char in "\"'`":
            quote = char
            start = index
            index += 1
            while index < length:
                if code[index] == "\\":
                    index += 2
                    continue
                if code[index] == quote:
                    index += 1
                    break
                if code[index] == "\n" and quote != "`":
                    break
                index += 1
            spans.append((start, index))
        else:
            index += 1
    return spans


def _in_spans(position: int, spans: list[Span]) -> bool:
    """True if char offset `position` falls inside any (start, end) span."""
    return any(start <= position < end for start, end in spans)


_ABSTRACT_DECORATORS = frozenset(
    {
        "abstractmethod",
        "abstractproperty",
        "overload",
        "abc.abstractmethod",
        "typing.overload",
    }
)
_ABSTRACT_BASES = frozenset({"Protocol", "ABC", "ABCMeta", "typing.Protocol", "abc.ABC"})


def _decorator_name(node: ast.expr) -> str:
    """Render a decorator expression as a dotted name, best effort."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_decorator_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _base_name(node: ast.expr) -> str:
    """Render a class base expression as a dotted name, best effort."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_base_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ""


def _body_is_trivial(body: list[ast.stmt]) -> bool:
    """True if a function body is only pass, ..., or a docstring plus those."""
    statements = list(body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements = statements[1:]
    if not statements:
        return True
    for statement in statements:
        if isinstance(statement, ast.Pass):
            continue
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is Ellipsis
        ):
            continue
        return False
    return True


def _python_ast_findings(code: str) -> list[Finding]:
    """AST-derived findings for Python: abstract-aware stubs, except/pass, and
    the deep logic rules (Po10 metrics, empty loops, identical branches,
    constant conditions, unreachable code).

    Returns [] if the source does not parse, leaving regex rules to operate
    alone rather than silently reporting a clean scan.
    """
    try:
        tree = ast.parse(code)
    except PARSER_REFUSALS:
        return []

    findings = python_logic_findings(tree)
    abstract_class_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = {_base_name(base) for base in node.bases}
            keywords = {kw.arg: _base_name(kw.value) for kw in node.keywords if kw.arg}
            is_abstract = bool(bases & _ABSTRACT_BASES) or keywords.get("metaclass") in _ABSTRACT_BASES
            if is_abstract:
                for child in ast.walk(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        abstract_class_lines.add(child.lineno)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _body_is_trivial(node.body):
                continue
            decorators = {_decorator_name(d) for d in node.decorator_list}
            if decorators & _ABSTRACT_DECORATORS or node.lineno in abstract_class_lines:
                continue
            findings.append(
                {
                    "line": node.lineno,
                    "class": CLASS_FRAMEWORK,
                    "finding": f"Function '{node.name}' has no implementation (body is pass/... only)",
                    "severity": "violation",
                    "source": "constitution-ast",
                    "cwe": "CWE-1071",
                }
            )
        elif isinstance(node, ast.ExceptHandler):
            if not all(isinstance(statement, ast.Pass) for statement in node.body):
                continue
            if node.type is None:
                findings.append(
                    {
                        "line": node.lineno,
                        "class": CLASS_CONFIDENCE,
                        "finding": "Bare 'except: pass' - every exception silently swallowed",
                        "severity": "violation",
                        "source": "constitution-ast",
                        "cwe": "CWE-1069",
                    }
                )
            else:
                findings.append(
                    {
                        "line": node.lineno,
                        "class": CLASS_CONFIDENCE,
                        "finding": (
                            f"'except {_base_name(node.type) or 'Exception'}: pass' - exception "
                            "swallowed; confirm this is deliberate and documented"
                        ),
                        "severity": "warning",
                        "source": "constitution-ast",
                        "cwe": "CWE-1069",
                    }
                )
    return findings


def _has_explanatory_comment(code: str, line_number: int) -> bool:
    """True if the given 1-based line carries a trailing or adjacent comment."""
    lines = code.splitlines()
    for candidate in (line_number - 1, line_number):
        if 0 <= candidate < len(lines) and re.search(r"#\s*\S", lines[candidate]):
            return True
    return False


# --------------------------------------------------------------------------
# Engine composition
# --------------------------------------------------------------------------


def _line_text(code: str, line_number: int) -> str:
    """Return the stripped, truncated text of a 1-based line number."""
    lines = code.splitlines()
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1].strip()[:200]
    return ""


def _is_python(code: str, language: str | None) -> bool:
    """Decide whether to apply Python AST analysis to this source."""
    if language:
        return language.strip().lower() in ("python", "py", "python3")
    try:
        ast.parse(code)
        return True
    except PARSER_REFUSALS:
        return False


# Trigger vocabulary of CodebaseCSI's docstring_todo rule, used to verify its
# hits against real docstrings resolved through the AST.
_DOCSTRING_TRIGGER_RE = re.compile(r"TODO|FIXME|placeholder|not implemented", re.IGNORECASE)


def _python_trigger_docstring_ranges(code: str) -> list[Span] | None:
    """Line ranges of real docstrings that contain incomplete-work triggers.

    Regex cannot decide triple-quote parity: a pattern anchored on triple
    quotes will happily match from one docstring's closing quotes to the next
    one's opening quotes, swallowing the code between. The AST knows which
    strings are actually docstrings, so CSI docstring findings are verified
    against these ranges. Returns None when the source does not parse (no
    verification possible - findings are then kept as reported).
    """
    try:
        tree = ast.parse(code)
    except PARSER_REFUSALS:
        return None
    ranges: list[Span] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if (
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and _DOCSTRING_TRIGGER_RE.search(value.value)
        ):
            ranges.append((body[0].lineno, body[0].end_lineno or body[0].lineno))
    return ranges


def _docstring_finding_is_verified(line_number: int, trigger_ranges: list[Span] | None) -> bool:
    """True when a docstring_todo hit lies inside a genuine trigger docstring."""
    if trigger_ranges is None:
        return True
    return any(start <= line_number <= end for start, end in trigger_ranges)


def _csi_findings(code: str, language: str | None, is_python: bool) -> tuple[list[Finding], str | None]:
    """Run CodebaseCSI's MockCodeDetector and normalise its output.

    Python sources get one extra verification step: docstring_todo hits are
    kept only when they fall inside a real docstring (per the AST) that
    genuinely contains a trigger word.
    """
    try:
        result = _CSI_DETECTOR.analyze(code, language=language or "python")
    except Exception as error:  # noqa: BLE001 - a detector fault must not abort the scan
        return [], f"CodebaseCSI detector failed: {type(error).__name__}: {error}"

    trigger_ranges = _python_trigger_docstring_ranges(code) if is_python else None

    findings: list[Finding] = []
    for pattern in result.get("patterns", []):
        pattern_type = getattr(pattern, "pattern_type", None)
        line_number = getattr(pattern, "line_number", 0)
        confidence = getattr(pattern, "confidence", 0.0)
        if (
            is_python
            # MockCodeDetector emits category-prefixed names ("todo_docstring_todo").
            and (pattern_type or "").endswith("docstring_todo")
            and not _docstring_finding_is_verified(line_number, trigger_ranges)
        ):
            continue
        finding: Finding = {
            "line": line_number,
            "class": _csi_failure_class(pattern_type),
            "finding": getattr(pattern, "description", pattern_type or "mock pattern"),
            "severity": _csi_severity(getattr(pattern, "severity", ""), confidence),
            "source": "codebase-csi",
            "confidence": round(float(confidence), 2),
            "suggestion": getattr(pattern, "suggestion", ""),
        }
        cwe = _csi_cwe(pattern_type)
        if cwe is not None:
            finding["cwe"] = cwe
        findings.append(finding)
    return findings, None


def _prose_findings(code: str, string_spans: list[Span]) -> list[Finding]:
    """Apply the Constitution prose and structural rules with span masking."""
    findings: list[Finding] = []
    for regex, failure_class, description, severity, kind, cwe in PROSE_RULES:
        suppressible = kind in _SUPPRESSIBLE_IN_STRINGS
        for match in regex.finditer(code):
            if suppressible and _in_spans(match.start(), string_spans):
                continue
            finding: Finding = {
                "line": code.count("\n", 0, match.start()) + 1,
                "class": failure_class,
                "finding": description,
                "severity": severity,
                "source": "constitution-prose",
            }
            if cwe is not None:
                finding["cwe"] = cwe
            findings.append(finding)
    return findings


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    """Collapse findings that report the same problem on the same line.

    Keys on (line, class, finding). Where duplicates differ in severity the
    strictest is retained, so a violation is never masked by a warning.
    """
    merged: dict[tuple[Any, Any, Any], Finding] = {}
    for finding in findings:
        key = (finding["line"], finding["class"], finding["finding"])
        existing = merged.get(key)
        if existing is None or (existing["severity"] == "warning" and finding["severity"] == "violation"):
            merged[key] = finding
    return list(merged.values())


def scan_code(code: str, language: str | None = None) -> dict[str, Any]:
    """Scan code for Zero-Framework-Tolerance violations.

    Args:
        code: Source text to scan. Must be a string.
        language: Optional language hint ("python", "javascript", ...). When
            omitted, Python is inferred by attempting to parse the source.

    Returns:
        dict with keys:
          verdict  - "FAIL" if any violation, "REVIEW" if only warnings,
                     otherwise "PASS".
          summary  - Human-readable disposition and required next action.
          findings - List of findings sorted by line, each with line, class,
                     finding, severity and source, plus a MITRE `cwe` ID
                     where a defensible mapping exists.
          engines  - Which detection engines contributed to this scan.

    Complexity: O(R x N) for R rules over N characters, plus one AST parse and
    one tokenize pass for Python sources.
    """
    assert isinstance(code, str), "code must be a string"

    treat_as_python = _is_python(code, language)
    string_spans = _python_data_string_spans(code) if treat_as_python else _generic_data_string_spans(code)

    findings, csi_error = _csi_findings(code, language, treat_as_python)
    findings.extend(_prose_findings(code, string_spans))

    engines = ["constitution-prose"]
    if csi_error is None:
        engines.append("codebase-csi")

    if not treat_as_python:
        # Real AST analysis for brace languages via the vendored tree-sitter
        # tier. Inactive (no grammar installed, unparseable input, unknown
        # language) contributes nothing and the regex tier stands alone.
        xfindings, xactive = xast_findings(code, language)
        if xactive:
            engines.append("constitution-xast")
            findings.extend(xfindings)

    if treat_as_python:
        engines.append("constitution-ast")
        for finding in _python_ast_findings(code):
            # A typed `except X: pass` carrying an explanatory comment is a
            # documented deliberate suppression, not an oversight.
            if (
                finding["severity"] == "warning"
                and finding["class"] == CLASS_CONFIDENCE
                and _has_explanatory_comment(code, finding["line"])
            ):
                continue
            findings.append(finding)

    findings = _deduplicate(findings)
    for finding in findings:
        finding["text"] = _line_text(code, finding["line"])
    findings.sort(key=lambda item: (item["line"], item["class"], item["finding"]))

    violation_count = sum(1 for item in findings if item["severity"] == "violation")
    warning_count = len(findings) - violation_count

    if violation_count > 0:
        verdict = "FAIL"
        summary = (
            f"{violation_count} violation(s) and {warning_count} warning(s) found. "
            "Per the Anti-Deception Enforcement Protocol this output is a failed output: "
            "discard it and regenerate the complete implementation from the problem "
            "statement. Do not patch the framework."
        )
    elif warning_count > 0:
        verdict = "REVIEW"
        summary = (
            f"No definite violations, but {warning_count} warning(s) require judgement. "
            "Confirm each flagged line is genuinely complete, then run gates G1-G5."
        )
    else:
        verdict = "PASS"
        summary = (
            "No placeholder, stub, scaffold, or deferral markers detected. This scan is "
            "necessary but not sufficient: it cannot prove executability, correctness, "
            "or dependency honesty. Run gates G1-G5 before delivering."
        )

    result = {
        "verdict": verdict,
        "summary": summary,
        "findings": findings,
        "engines": engines,
    }
    if csi_error is not None:
        result["degraded"] = csi_error
    return result
