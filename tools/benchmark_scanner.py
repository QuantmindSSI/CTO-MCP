#!/usr/bin/env python3
"""Measure the scanner against an adversarial corpus.

Reports the correct-verdict rate for three configurations so the accuracy
claim in README.md is reproducible rather than asserted:

  1. Constitution prose/structural rules alone (CodebaseCSI and AST disabled).
  2. CodebaseCSI's MockCodeDetector alone.
  3. The shipped union of all three engines.

The corpus deliberately includes legitimate code constructed to resemble
violations, because a scanner that flags real code is worse than no scanner:
it trains its users to ignore it.

Run:  .venv/bin/python tools/benchmark_scanner.py
Exits non-zero if the shipped union regresses below its recorded baseline.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codebase_csi.analyzers.mock_detector import MockCodeDetector
from persona_constitution import scanner
from persona_constitution.ast_bridge import xast_findings

# The constitution-xast engine is active only when the optional `ast` extra
# (tree-sitter + grammars) is installed. Seven corpus cases are decidable only
# on a real syntax tree, so the baseline is environment-aware: one number for
# each configuration, both enforced in CI. Update only with evidence.
XAST_ACTIVE = xast_findings("function probe() {\n}\n", "javascript")[1]
UNION_BASELINE = 37 if XAST_ACTIVE else 30

# (name, source, language) for code that MUST produce a FAIL verdict.
VIOLATIONS = [
    ("go empty body", "package main\nfunc Process(d []byte) error {\n}\n", "go"),
    ("go panic stub", 'func Save(u User) error {\n    panic("not implemented")\n}\n', "go"),
    ("js empty function", "function handler(req, res) {\n}\n", "javascript"),
    ("java empty method", "public class S {\n    public void save(User u) {\n    }\n}\n", "java"),
    ("catch comment only", "try { work(); } catch (e) { /* ignore */ }\n", "javascript"),
    ("bare except pass", "try:\n    x()\nexcept: pass\n", "python"),
    ("ts unimplemented throw", 'function f(): never { throw new Error("unimplemented"); }\n', "typescript"),
    ("concrete def ellipsis", "def f(a: int) -> int: ...\n", "python"),
    ("todo stub", "def process(d):\n    # TODO: implement later\n    pass\n", "python"),
    ("not implemented error", "def compute(v):\n    raise NotImplementedError\n", "python"),
    ("always true stub", "def validate(user):\n    return True\n", "python"),
    ("print only stub", 'def save(rec):\n    print("saving", rec)\n', "python"),
    (
        "rest of implementation",
        "def a():\n    return 1\n# rest of the implementation follows the same pattern\n",
        "python",
    ),
    ("left as an exercise", "// Error handling is left as an exercise for the reader\n", "javascript"),
    ("starting point", "# This is a starting point; you can extend this to handle retries\n", "python"),
    ("rust todo macro", "fn parse(s: &str) -> Ast {\n    todo!()\n}\n", "rust"),
    ("omitted for brevity", "// remaining handlers omitted for brevity\n", "javascript"),
    # Detectable only with the xast engine (the `ast` extra). Without real AST
    # parsing these grade REVIEW or PASS; the environment-aware baseline above
    # records them as accepted misses in that configuration.
    ("hardcoded null return", "function getUser(id) {\n  return null;\n}\n", "javascript"),
    (
        "java unsupported op stub",
        "class Store {\n    void save(User u) {\n        throw new UnsupportedOperationException();\n    }\n}\n",
        "java",
    ),
    (
        "ts template literal throw",
        "function migrate(): void {\n  throw new Error(`not implemented`);\n}\n",
        "typescript",
    ),
    ("ruby empty method", "def process(record)\nend\n", "ruby"),
    ("go nil return stub", "package db\nfunc GetUser(id int) *User {\n\treturn nil\n}\n", "go"),
    ("js named arrow stub", "const getUser = (id) => {\n  return null;\n};\n", "javascript"),
    (
        "ts named function expression stub",
        "const isValid = function (token) {\n  return true;\n};\n",
        "typescript",
    ),
]

# (name, source, language) for legitimate code that must NOT produce a FAIL.
LEGITIMATE = [
    ("react placeholder attr", 'export const F = () => <input placeholder="Enter email" />;\n', "javascript"),
    ("sql bind parameter", 'query = "SELECT * FROM t WHERE id = %s"\n', "python"),
    (
        "linter matching TODO",
        'def check(line):\n    if "TODO" in line:\n        report(line)\n        return 1\n    return 0\n',
        "python",
    ),
    (
        "typing.Protocol stub",
        "from typing import Protocol\nclass Repo(Protocol):\n    def get(self, k: str) -> bytes:\n        ...\n",
        "python",
    ),
    (
        "abstractmethod stub",
        "import abc\nclass B(abc.ABC):\n    @abc.abstractmethod\n    def run(self): ...\n",
        "python",
    ),
    (
        "documented except pass",
        "def shut(sock):\n    try:\n        sock.close()\n    except OSError:\n        pass  # already closed by peer\n",
        "python",
    ),
    (
        "docstring says brevity",
        'def f(x):\n    """Names are short for brevity."""\n    return x * 2\n',
        "python",
    ),
    (
        "real python function",
        'def add(a: int, b: int) -> int:\n    if not isinstance(a, int):\n        raise TypeError("a must be int")\n    return a + b\n',
        "python",
    ),
    (
        "real js handler",
        "function handler(req, res) {\n  const id = req.params.id;\n  res.json({ id });\n}\n",
        "javascript",
    ),
    # Guards on the xast engine's deliberate exemptions: anonymous no-op
    # callbacks and empty constructors are idioms, not stubs.
    ("anonymous noop callback", "emitter.on('error', function () {});\n", "javascript"),
    ("java empty constructor", "public class Widget {\n    public Widget() {\n    }\n}\n", "java"),
    # Deep-logic rules must warn (REVIEW), never FAIL, on judgement calls.
    ("noop default arrow", "const onClose = () => {};\n", "javascript"),
    ("busy wait loop", "function f() {\n  while (!ready()) {}\n  return done();\n}\n", "javascript"),
]


def verdict_prose_only(code, language):
    """Prose and structural rules alone: no CodebaseCSI, no AST analysis."""
    if language and language.lower() in ("python", "py", "python3"):
        spans = scanner._python_data_string_spans(code)
    else:
        spans = scanner._generic_data_string_spans(code)
    findings = scanner._prose_findings(code, spans)
    return "FAIL" if any(f["severity"] == "violation" for f in findings) else "PASS"


_CSI = MockCodeDetector()


def verdict_csi_only(code, language):
    """CodebaseCSI alone: any detected mock pattern counts as a flag."""
    result = _CSI.analyze(code, language=language or "python")
    return "FAIL" if result.get("patterns") else "PASS"


def verdict_union(code, language):
    """The shipped scanner."""
    return scanner.scan_code(code, language=language)["verdict"]


CONFIGURATIONS = (
    ("prose rules only", verdict_prose_only),
    ("codebase-csi only", verdict_csi_only),
    ("union (shipped)", verdict_union),
)


def main():
    total = len(VIOLATIONS) + len(LEGITIMATE)
    scores = {}

    for label, verdict_of in CONFIGURATIONS:
        correct = 0
        misses = []
        for name, code, language in VIOLATIONS:
            if verdict_of(code, language) == "FAIL":
                correct += 1
            else:
                misses.append(f"missed violation: {name}")
        for name, code, language in LEGITIMATE:
            if verdict_of(code, language) != "FAIL":
                correct += 1
            else:
                misses.append(f"false positive: {name}")
        scores[label] = (correct, misses)

    width = max(len(label) for label, _ in CONFIGURATIONS)
    print(
        f"Adversarial corpus: {len(VIOLATIONS)} violations, "
        f"{len(LEGITIMATE)} legitimate samples, {total} total\n"
    )
    for label, _ in CONFIGURATIONS:
        correct, misses = scores[label]
        print(f"  {label:<{width}}  {correct:>2}/{total}  ({100 * correct // total}%)")
        for miss in misses:
            print(f"  {'':<{width}}    - {miss}")

    union_correct = scores["union (shipped)"][0]
    print()
    if union_correct < UNION_BASELINE:
        print(
            f"REGRESSION: union scored {union_correct}/{total}, "
            f"below the recorded baseline of {UNION_BASELINE}."
        )
        return 1
    print(f"Union at or above baseline ({union_correct}/{total} >= {UNION_BASELINE}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
