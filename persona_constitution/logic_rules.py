"""Deep logic rules shared by the Python AST engine and the xast engine.

This module hardens the scanner beyond stub detection: it judges the *logic
shape* of code on real syntax trees. Every rule here emits WARNING severity,
never violation - these are Power of 10 discipline and confidence-mismatch
signals that demand judgement (the agent layer's job), not mechanical
rejection. Stub detection, which is mechanical, stays violation-severity in
the engines that own it.

Rules:
  * Po10 Rule 1  - cyclomatic complexity above COMPLEXITY_LIMIT per function.
  * Po10 Rule 4  - function length above LENGTH_LIMIT lines.
  * Empty loop body        - a loop that does nothing is scaffold or a spin
                             wait; both need a human decision.
  * Identical if/else arms - both branches textually identical: copy-paste
                             scaffold, a hallmark of generated filler.
  * Constant if condition  - `if True:` / `if (false)` dead-branch toggles.
                             (`while True:` event loops are deliberately NOT
                             flagged - that idiom is legitimate.)
  * Unreachable statements - code after return/raise/break/continue in the
                             same block (Python engine only; brace languages
                             get it from their compilers).

Complexity counting follows the classic McCabe convention: one plus the
number of decision points (if/elif, loops, except handlers, boolean-operator
short circuits, ternaries, comprehension filters, assertions, match cases).
Nested function bodies are excluded from the enclosing function's count and
measured separately.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import Any, Union

# One finding in the scanner's JSON schema (line/class/finding/severity/source).
Finding = dict[str, Any]
# The two def-statement node shapes; 3.9 is the floor, so no ast.Match here.
FunctionNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]

COMPLEXITY_LIMIT = 10
LENGTH_LIMIT = 50

CLASS_PO10_COMPLEXITY = "Power of 10 - Rule 1 (Simple Control Flow)"
CLASS_PO10_LENGTH = "Power of 10 - Rule 4 (Function Length)"
CLASS_CONFIDENCE = "Class 3 - Confidence Mismatch"
CLASS_FRAMEWORK = "Class 1 - Framework Generation"

TEXT_EMPTY_LOOP = "Loop body is empty - scaffold or unthrottled spin wait"
TEXT_IDENTICAL_BRANCHES = "if and else branches are identical - copy-paste scaffold"
TEXT_CONSTANT_CONDITION = "Branch condition is a constant - dead or always-taken branch"
TEXT_UNREACHABLE = "Unreachable code after a terminal statement in the same block"

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_TERMINAL_NODES = (ast.Return, ast.Raise, ast.Break, ast.Continue)
_LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)
_DECISION_NODES = (ast.If, ast.IfExp, ast.ExceptHandler, ast.Assert, ast.For, ast.AsyncFor, ast.While)

# ast.Match exists from 3.10; the floor is 3.9.
_MATCH_NODE = getattr(ast, "Match", None)


def _warning(line: int, failure_class: str, text: str) -> Finding:
    """One finding dict in the scanner schema, always warning severity."""
    return {
        "line": line,
        "class": failure_class,
        "finding": text,
        "severity": "warning",
        "source": "constitution-logic",
    }


def _iter_function_scope(function_node: FunctionNode) -> Iterator[ast.AST]:
    """Yield nodes of one function, not descending into nested functions."""
    stack = list(ast.iter_child_nodes(function_node))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _FUNCTION_NODES):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _complexity(function_node: FunctionNode) -> int:
    """McCabe cyclomatic complexity of one function scope."""
    score = 1
    for node in _iter_function_scope(function_node):
        if isinstance(node, _DECISION_NODES):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += max(len(node.values) - 1, 1)
        elif isinstance(node, ast.comprehension):
            score += 1 + len(node.ifs)
        elif _MATCH_NODE is not None and isinstance(node, _MATCH_NODE):
            score += len(getattr(node, "cases", []))
    return score


def _metric_findings(function_node: FunctionNode) -> list[Finding]:
    """Po10 Rule 1 and Rule 4 warnings for one function."""
    findings: list[Finding] = []
    complexity = _complexity(function_node)
    if complexity > COMPLEXITY_LIMIT:
        findings.append(
            _warning(
                function_node.lineno,
                CLASS_PO10_COMPLEXITY,
                f"Function '{function_node.name}' has cyclomatic complexity {complexity} "
                f"(limit {COMPLEXITY_LIMIT}) - decompose it",
            )
        )
    end_line = getattr(function_node, "end_lineno", None)
    if end_line is not None:
        length = end_line - function_node.lineno + 1
        if length > LENGTH_LIMIT:
            findings.append(
                _warning(
                    function_node.lineno,
                    CLASS_PO10_LENGTH,
                    f"Function '{function_node.name}' is {length} lines long "
                    f"(limit {LENGTH_LIMIT}) - single responsibility demands decomposition",
                )
            )
    return findings


def _body_is_only_pass(body: list[ast.stmt]) -> bool:
    """True when every statement in a body list is `pass`."""
    return bool(body) and all(isinstance(statement, ast.Pass) for statement in body)


def _branch_findings(node: ast.If) -> list[Finding]:
    """Identical-arm and constant-condition warnings for one If node."""
    findings: list[Finding] = []
    if isinstance(node.test, ast.Constant) and isinstance(node.test.value, (bool, int)):
        findings.append(_warning(node.lineno, CLASS_CONFIDENCE, TEXT_CONSTANT_CONDITION))
    orelse = node.orelse
    is_elif = len(orelse) == 1 and isinstance(orelse[0], ast.If)
    if orelse and not is_elif:
        body_dump = [ast.dump(statement) for statement in node.body]
        else_dump = [ast.dump(statement) for statement in orelse]
        if body_dump == else_dump:
            findings.append(_warning(node.lineno, CLASS_CONFIDENCE, TEXT_IDENTICAL_BRANCHES))
    return findings


def _unreachable_findings(node: ast.AST) -> list[Finding]:
    """Warnings for statements after a terminal statement in any block field."""
    findings: list[Finding] = []
    for field in ("body", "orelse", "finalbody"):
        block = getattr(node, field, None)
        if not isinstance(block, list):
            continue
        for index, statement in enumerate(block[:-1]):
            if isinstance(statement, _TERMINAL_NODES):
                findings.append(_warning(block[index + 1].lineno, CLASS_CONFIDENCE, TEXT_UNREACHABLE))
                break
    return findings


def python_logic_findings(tree: ast.Module) -> list[Finding]:
    """Deep logic warnings for a parsed Python module.

    Args:
        tree: An ast.Module produced by ast.parse. The caller owns parse
            failures; this function asserts it received a real tree.

    Returns:
        List of finding dicts (all warning severity, source
        "constitution-logic"), unsorted.

    Complexity: O(N) over AST nodes; each node is visited a bounded number of
    times (module walk + at most one enclosing-function scope walk).
    """
    assert isinstance(tree, ast.Module), "python_logic_findings requires a parsed ast.Module"

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTION_NODES):
            findings.extend(_metric_findings(node))
        if isinstance(node, _LOOP_NODES) and _body_is_only_pass(node.body):
            findings.append(_warning(node.lineno, CLASS_FRAMEWORK, TEXT_EMPTY_LOOP))
        if isinstance(node, ast.If):
            findings.extend(_branch_findings(node))
        findings.extend(_unreachable_findings(node))
    return findings
