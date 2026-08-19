"""Cross-language AST engine: the `constitution-xast` scanner backend.

This module walks real tree-sitter syntax trees (via the vendored CodebaseCSI
`TreeSitterParser`) and evaluates the constitution's structural stub rules on
AST nodes instead of regex approximations. It exists because regex cannot
distinguish `function getUser(id) { return null; }` (a stub) from a `null`
appearing anywhere else in an expression, and therefore the regex tier had to
grade single-hardcoded-return bodies as warnings. On a parsed tree the
judgement is exact, so this engine emits violations.

Engine contract:

  * Findings reuse the exact description strings of their regex counterparts
    in `scanner.PROSE_RULES`. The scanner's `_deduplicate` keys on
    (line, class, finding) and keeps the strictest severity, so an AST-backed
    violation upgrades the matching regex warning in place instead of
    double-reporting.
  * The engine only trusts full tree-sitter parses. When tree-sitter or the
    grammar is unavailable, or the tree contains ERROR nodes, it reports
    itself inactive and the caller falls back to the regex tier alone.
  * Python is out of scope here: `scanner._python_ast_findings` already covers
    it with the stdlib `ast` module at higher fidelity.

Deliberate non-detections, so the engine accuses no legitimate idiom:

  * Anonymous functions (`function () {}` callbacks, arrow functions) are the
    brace-language equivalent of `lambda: None` and are never flagged.
  * Constructors are excluded everywhere: an empty or trivial constructor is
    an established idiom, not a stub.
  * C/C++ skip the empty-body rule because constructors and destructors are
    not reliably distinguishable from functions without full class context.
  * A body of exactly `return;` is not flagged: no corpus evidence separates
    the deliberate no-op from the stub.

Every node-type name in the tables below was verified against parses produced
by the pinned grammar wheels (see the `ast` extra in pyproject.toml), not
taken from documentation.
"""

import re

from codebase_csi.parsers.ast_parser import TreeSitterParser

try:
    from .logic_rules import (
        CLASS_PO10_COMPLEXITY,
        CLASS_PO10_LENGTH,
        COMPLEXITY_LIMIT,
        LENGTH_LIMIT,
        TEXT_EMPTY_LOOP,
        TEXT_IDENTICAL_BRANCHES,
    )
except ImportError:  # pragma: no cover - direct module execution
    from persona_constitution.logic_rules import (
        CLASS_PO10_COMPLEXITY,
        CLASS_PO10_LENGTH,
        COMPLEXITY_LIMIT,
        LENGTH_LIMIT,
        TEXT_EMPTY_LOOP,
        TEXT_IDENTICAL_BRANCHES,
    )

# Constitution failure classes. Kept textually identical to
# persona_constitution.scanner; tests/test_ast_bridge.py asserts the match so
# the two modules cannot drift apart silently.
CLASS_FRAMEWORK = "Class 1 - Framework Generation"
CLASS_CONFIDENCE = "Class 3 - Confidence Mismatch"

# Finding texts, byte-identical to their PROSE_RULES counterparts (dedupe key).
TEXT_EMPTY_FUNCTION = "Function declared with an entirely empty body"
TEXT_HARDCODED_RETURN = "Function body is a single hardcoded return - no implementation"
TEXT_EMPTY_CATCH = "Empty catch block: silently swallowed exception"
TEXT_NOT_IMPLEMENTED = "'not implemented' exception stub"
TEXT_PANIC_STUB = "Go panic() used as an unimplemented stub"
TEXT_RUST_MACRO = "Rust unimplemented!()/todo!() macro stub"

SOURCE = "constitution-xast"

# Hint spellings accepted from callers -> canonical grammar language.
_LANGUAGE_ALIASES = {
    "javascript": "javascript",
    "js": "javascript",
    "jsx": "javascript",
    "node": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "tsx": "typescript",
    "java": "java",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "rs": "rust",
    "ruby": "ruby",
    "rb": "ruby",
    "c": "c",
    "cpp": "cpp",
    "c++": "cpp",
    "cc": "cpp",
}

# Named function/method definition node types per language. Constructors are
# excluded here (java) or by name check (_is_constructor).
_FUNCTION_TYPES = {
    "javascript": frozenset(
        {"function_declaration", "generator_function_declaration", "function_expression", "method_definition"}
    ),
    "typescript": frozenset(
        {"function_declaration", "generator_function_declaration", "function_expression", "method_definition"}
    ),
    "java": frozenset({"method_declaration"}),
    "go": frozenset({"function_declaration", "method_declaration"}),
    "rust": frozenset({"function_item"}),
    "ruby": frozenset({"method", "singleton_method"}),
    "c": frozenset({"function_definition"}),
    "cpp": frozenset({"function_definition"}),
}

# Languages where an empty body is flagged. C/C++ are excluded: see module
# docstring.
_EMPTY_BODY_LANGUAGES = frozenset({"javascript", "typescript", "java", "go", "rust", "ruby"})

# catch-clause node types whose empty body is a Class 3 violation.
_CATCH_TYPES = {
    "javascript": frozenset({"catch_clause"}),
    "typescript": frozenset({"catch_clause"}),
    "java": frozenset({"catch_clause"}),
    "cpp": frozenset({"catch_clause"}),
}

# Literal node types that make `return <literal>;` a stub. Grammar quirk that
# helps here: tree-sitter-c/cpp normalise NULL and nullptr into a `null` node.
_NULLISH_RETURN_TYPES = {
    "javascript": frozenset({"null", "undefined", "true", "false"}),
    "typescript": frozenset({"null", "undefined", "true", "false"}),
    "java": frozenset({"null_literal", "true", "false"}),
    "go": frozenset({"nil", "true", "false"}),
    "c": frozenset({"null", "true", "false"}),
    "cpp": frozenset({"null", "true", "false"}),
}

_COMMENT_TYPES = frozenset({"comment", "line_comment", "block_comment"})

# Function-valued expressions that acquire a name through a variable
# declarator (`const getUser = (id) => {...}`). Sole-statement stub rules and
# Po10 metrics apply to them; the empty-body rule deliberately does NOT -
# `const onClose = () => {}` is an established deliberate-noop default idiom.
_VALUE_FUNCTION_TYPES = frozenset({"arrow_function", "function_expression", "generator_function", "function"})

# Loop constructs whose empty body is scaffold or an unthrottled spin wait.
# Every node type verified against the pinned grammars; Ruby's `while` carries
# its body in a `do` node reached through the same `body` field.
_LOOP_TYPES = {
    "javascript": frozenset({"while_statement", "do_statement", "for_statement", "for_in_statement"}),
    "typescript": frozenset({"while_statement", "do_statement", "for_statement", "for_in_statement"}),
    "java": frozenset({"while_statement", "do_statement", "for_statement", "enhanced_for_statement"}),
    "go": frozenset({"for_statement"}),
    "rust": frozenset({"while_expression", "for_expression", "loop_expression"}),
    "ruby": frozenset({"while", "until", "for"}),
    "c": frozenset({"while_statement", "do_statement", "for_statement"}),
    "cpp": frozenset({"while_statement", "do_statement", "for_statement"}),
}

_IF_TYPES = frozenset({"if_statement", "if_expression"})
_BLOCK_TYPES = frozenset({"statement_block", "block", "compound_statement"})

# Decision-point node types across the supported grammars, for McCabe
# complexity. A union set is deliberate: type names do not collide across
# languages in ways that distort the count, and one table is auditable where
# eight per-language tables drift.
_DECISION_TYPES = frozenset(
    {
        "if_statement",
        "if_expression",
        "while_statement",
        "while_expression",
        "do_statement",
        "for_statement",
        "for_in_statement",
        "for_expression",
        "enhanced_for_statement",
        "switch_case",
        "case_statement",
        "switch_block_statement_group",
        "match_arm",
        "expression_case",
        "type_case",
        "communication_case",
        "catch_clause",
        "ternary_expression",
        "conditional_expression",
        "when",
        "elsif",
        "rescue",
    }
)
_BOOL_OPERATOR_TEXT = frozenset({"&&", "||", "??", "and", "or"})
_OPERATOR_CARRIER_TYPES = frozenset({"binary_expression", "boolean_operator", "binary"})

# Stub spellings inside a throw/panic message. Scoped strictly to
# throw/panic/macro nodes, never to arbitrary code text.
_NOT_IMPLEMENTED_RE = re.compile(
    r"not[\s_-]*implemented|unimplemented|not[\s_-]*supported|unsupportedoperation|\btodo\b",
    re.IGNORECASE,
)

_RUST_STUB_MACROS = frozenset({"todo", "unimplemented"})

# Defense-in-depth bound on tree traversal. Input is already capped at
# MAX_SCAN_BYTES upstream; node count is linear in input size, so this limit
# is unreachable for legal inputs and exists to make the walk provably finite.
_MAX_NODES = 500_000


def normalize_language(language):
    """Map a caller-supplied language hint to a canonical grammar name.

    Args:
        language: Free-form hint such as "ts", "C++", "golang", or None.

    Returns:
        The canonical language key used by the rule tables, or None when the
        hint is absent or names a language this engine does not cover.
    """
    if not language:
        return None
    return _LANGUAGE_ALIASES.get(str(language).strip().lower())


def _node_text(node, code_bytes):
    """Return the source text of a node, decoded defensively."""
    return code_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _statements(body):
    """Named children of a body node, excluding comments."""
    return [child for child in body.named_children if child.type not in _COMMENT_TYPES]


def _function_name(node, language, code_bytes):
    """Extract a function's declared name, or None when it is anonymous.

    C/C++ nest the identifier inside (pointer_)declarator chains, so the
    declarator field is followed until an identifier-bearing node appears.
    The descent is bounded by the declarator chain length.
    """
    if language in ("c", "cpp"):
        current = node.child_by_field_name("declarator")
        while current is not None and current.type not in ("identifier", "field_identifier"):
            nested = current.child_by_field_name("declarator")
            if nested is None:
                return None
            current = nested
        return _node_text(current, code_bytes) if current is not None else None
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text(name_node, code_bytes)


def _is_constructor(node, name):
    """True for constructor definitions, which are exempt from all rules."""
    if node.type == "constructor_declaration":
        return True
    return name == "constructor"


def _finding(node, failure_class, text, severity="violation"):
    """Build one finding in the scanner's schema."""
    return {
        "line": node.start_point[0] + 1,
        "class": failure_class,
        "finding": text,
        "severity": severity,
        "source": SOURCE,
    }


def _unwrap_expression(statement):
    """Unwrap an expression_statement to its single expression child."""
    if statement.type == "expression_statement":
        inner = _statements(statement)
        if len(inner) == 1:
            return inner[0]
    return statement


def _classify_sole_statement(statement, node, language, code_bytes):
    """Judge a function whose body is exactly one statement.

    Returns a finding for stub-shaped sole statements (hardcoded nullish
    return, not-implemented throw, panic stub, todo!/unimplemented! macro),
    otherwise None.
    """
    inner = _unwrap_expression(statement)

    if inner.type == "return_statement":
        values = _statements(inner)
        # Go wraps return values in an expression_list node; a single-value
        # list is transparent for this judgement.
        if len(values) == 1 and values[0].type == "expression_list":
            values = _statements(values[0])
        nullish = _NULLISH_RETURN_TYPES.get(language, frozenset())
        if len(values) == 1 and values[0].type in nullish:
            return _finding(node, CLASS_FRAMEWORK, TEXT_HARDCODED_RETURN)
        return None

    if inner.type == "throw_statement":
        if _NOT_IMPLEMENTED_RE.search(_node_text(inner, code_bytes)):
            return _finding(node, CLASS_FRAMEWORK, TEXT_NOT_IMPLEMENTED)
        return None

    if language == "go" and inner.type == "call_expression":
        function = inner.child_by_field_name("function")
        if (
            function is not None
            and _node_text(function, code_bytes) == "panic"
            and _NOT_IMPLEMENTED_RE.search(_node_text(inner, code_bytes))
        ):
            return _finding(node, CLASS_FRAMEWORK, TEXT_PANIC_STUB)
        return None

    if language == "rust" and inner.type == "macro_invocation":
        macro = inner.child_by_field_name("macro")
        if macro is not None and _node_text(macro, code_bytes) in _RUST_STUB_MACROS:
            return _finding(node, CLASS_FRAMEWORK, TEXT_RUST_MACRO)
        return None

    return None


def _classify_function(node, language, code_bytes):
    """Evaluate one function definition node against the stub rules.

    Returns a finding dict or None. Anonymous functions, constructors, and
    body-less declarations (interfaces, prototypes, `declare` signatures) are
    never flagged.
    """
    name = _function_name(node, language, code_bytes)
    if _is_constructor(node, name):
        return None

    body = node.child_by_field_name("body")
    if body is None:
        # Ruby methods have no body field when the body is empty; everywhere
        # else a missing body means declaration-only, which is legitimate.
        if language == "ruby" and name is not None:
            return _finding(node, CLASS_FRAMEWORK, TEXT_EMPTY_FUNCTION)
        return None

    if name is None:
        return None

    statements = _statements(body)
    if len(statements) == 0:
        if language in _EMPTY_BODY_LANGUAGES:
            return _finding(node, CLASS_FRAMEWORK, TEXT_EMPTY_FUNCTION)
        return None
    if len(statements) == 1:
        return _classify_sole_statement(statements[0], node, language, code_bytes)
    return None


def _classify_catch(node):
    """Flag catch clauses whose body holds no statements (comments allowed)."""
    body = node.child_by_field_name("body")
    if body is None:
        return None
    if len(_statements(body)) == 0:
        return _finding(node, CLASS_CONFIDENCE, TEXT_EMPTY_CATCH)
    return None


def _classify_loop(node):
    """Warn on loops whose body contains no statements."""
    body = node.child_by_field_name("body")
    if body is None:
        return None
    if len(_statements(body)) == 0:
        return _finding(node, CLASS_FRAMEWORK, TEXT_EMPTY_LOOP, severity="warning")
    return None


def _resolve_else(alternative):
    """Unwrap an else_clause wrapper (js/ts/rust) to its single payload node."""
    if alternative.type == "else_clause":
        inner = _statements(alternative)
        return inner[0] if len(inner) == 1 else None
    return alternative


def _classify_branches(node, code_bytes):
    """Warn when if and else arms are textually identical (else-if exempt)."""
    consequence = node.child_by_field_name("consequence")
    alternative = node.child_by_field_name("alternative")
    if consequence is None or alternative is None:
        return None
    resolved = _resolve_else(alternative)
    if resolved is None or resolved.type in _IF_TYPES:
        return None
    if consequence.type not in _BLOCK_TYPES or resolved.type not in _BLOCK_TYPES:
        return None
    if _node_text(consequence, code_bytes).strip() == _node_text(resolved, code_bytes).strip():
        return _finding(node, CLASS_CONFIDENCE, TEXT_IDENTICAL_BRANCHES, severity="warning")
    return None


def _nested_function_types(language):
    """Node types whose subtrees are separate scopes for complexity counting."""
    return _FUNCTION_TYPES[language] | _VALUE_FUNCTION_TYPES | {"constructor_declaration"}


def _complexity(function_node, language, code_bytes):
    """McCabe complexity of one function scope, nested functions excluded."""
    skip_types = _nested_function_types(language)
    score = 1
    stack = list(function_node.named_children)
    while stack:
        node = stack.pop()
        if node.type in skip_types:
            continue
        if node.type in _DECISION_TYPES:
            score += 1
        elif node.type in _OPERATOR_CARRIER_TYPES:
            operator = node.child_by_field_name("operator")
            if operator is not None and _node_text(operator, code_bytes) in _BOOL_OPERATOR_TEXT:
                score += 1
        stack.extend(node.named_children)
    return score


def _metric_findings(name, function_node, language, code_bytes):
    """Po10 Rule 1/4 warnings for one function-like node."""
    findings = []
    label = name or "anonymous"
    complexity = _complexity(function_node, language, code_bytes)
    if complexity > COMPLEXITY_LIMIT:
        findings.append(
            _finding(
                function_node,
                CLASS_PO10_COMPLEXITY,
                f"Function '{label}' has cyclomatic complexity {complexity} "
                f"(limit {COMPLEXITY_LIMIT}) - decompose it",
                severity="warning",
            )
        )
    length = function_node.end_point[0] - function_node.start_point[0] + 1
    if length > LENGTH_LIMIT:
        findings.append(
            _finding(
                function_node,
                CLASS_PO10_LENGTH,
                f"Function '{label}' is {length} lines long "
                f"(limit {LENGTH_LIMIT}) - single responsibility demands decomposition",
                severity="warning",
            )
        )
    return findings


def _classify_declarator(node, language, code_bytes):
    """Stub and metric findings for `const name = function/arrow` bindings."""
    name_node = node.child_by_field_name("name")
    value = node.child_by_field_name("value")
    if name_node is None or value is None or value.type not in _VALUE_FUNCTION_TYPES:
        return []
    body = value.child_by_field_name("body")
    if body is None or body.type not in _BLOCK_TYPES:
        # Expression-bodied arrows (`() => null`) are lambda-equivalent: exempt.
        return []
    name = _node_text(name_node, code_bytes)
    findings = []
    statements = _statements(body)
    if len(statements) == 1:
        stub = _classify_sole_statement(statements[0], node, language, code_bytes)
        if stub is not None:
            findings.append(stub)
    findings.extend(_metric_findings(name, value, language, code_bytes))
    return findings


def xast_findings(code, language):
    """Scan non-Python source with the tree-sitter engine.

    Args:
        code: Source text to scan. Must be a string.
        language: Language hint; any spelling in _LANGUAGE_ALIASES.

    Returns:
        (findings, active): `findings` is a list of scanner-schema dicts;
        `active` is False when this engine could not run (no grammar, parse
        errors, unsupported language) and True when its verdict is trustworthy.
        An inactive engine never contributes findings.

    Complexity: O(N) over tree nodes, bounded by _MAX_NODES.
    """
    assert isinstance(code, str), "code must be a string"

    canonical = normalize_language(language)
    if canonical is None or canonical not in _FUNCTION_TYPES:
        return [], False

    tree = TreeSitterParser.parse(code, canonical)
    if tree is None:
        return [], False
    root = tree.root_node
    if root.has_error:
        # A broken parse means node boundaries cannot be trusted; regex tiers
        # still cover this input upstream.
        return [], False

    code_bytes = code.encode("utf-8")

    findings = []
    stack = [root]
    visited = 0
    while stack and visited < _MAX_NODES:
        node = stack.pop()
        visited += 1
        findings.extend(_dispatch_node(node, canonical, code_bytes))
        stack.extend(node.named_children)

    assert visited < _MAX_NODES, "AST walk exceeded the node budget; input exceeds supported size"
    return findings, True


def _dispatch_node(node, language, code_bytes):
    """Route one node to every rule that applies to its type."""
    function_types = _FUNCTION_TYPES[language]
    findings = []
    if node.type in function_types or node.type == "constructor_declaration":
        stub = _classify_function(node, language, code_bytes)
        if stub is not None:
            findings.append(stub)
        # Declarator-bound function expressions are measured through their
        # declarator so the metric carries the bound name, not "anonymous".
        parent = node.parent
        if not (parent is not None and parent.type == "variable_declarator"):
            name = _function_name(node, language, code_bytes)
            findings.extend(_metric_findings(name, node, language, code_bytes))
    elif node.type == "variable_declarator":
        findings.extend(_classify_declarator(node, language, code_bytes))
    elif node.type in _CATCH_TYPES.get(language, frozenset()):
        catch = _classify_catch(node)
        if catch is not None:
            findings.append(catch)
    elif node.type in _LOOP_TYPES.get(language, frozenset()):
        loop = _classify_loop(node)
        if loop is not None:
            findings.append(loop)
    elif node.type in _IF_TYPES:
        branch = _classify_branches(node, code_bytes)
        if branch is not None:
            findings.append(branch)
    return findings
