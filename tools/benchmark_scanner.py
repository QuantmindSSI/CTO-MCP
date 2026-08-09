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

# Baseline the union must not regress below. Update only with evidence.
UNION_BASELINE = 26

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
    ("rest of implementation", "def a():\n    return 1\n# rest of the implementation follows the same pattern\n", "python"),
    ("left as an exercise", "// Error handling is left as an exercise for the reader\n", "javascript"),
    ("starting point", "# This is a starting point; you can extend this to handle retries\n", "python"),
    ("rust todo macro", "fn parse(s: &str) -> Ast {\n    todo!()\n}\n", "rust"),
    ("omitted for brevity", "// remaining handlers omitted for brevity\n", "javascript"),
    # Known miss: graded REVIEW, not FAIL. A body of `return null;` is a stub in
    # generated code but legitimate in hand-written lookups, so it is reported as
    # a warning. Retained in the corpus so the union's score stays honest.
    ("hardcoded null return", "function getUser(id) {\n  return null;\n}\n", "javascript"),
]

# (name, source, language) for legitimate code that must NOT produce a FAIL.
LEGITIMATE = [
    ("react placeholder attr", 'export const F = () => <input placeholder="Enter email" />;\n', "javascript"),
    ("sql bind parameter", 'query = "SELECT * FROM t WHERE id = %s"\n', "python"),
    ("linter matching TODO",
     'def check(line):\n    if "TODO" in line:\n        report(line)\n        return 1\n    return 0\n', "python"),
    ("typing.Protocol stub",
     "from typing import Protocol\nclass Repo(Protocol):\n    def get(self, k: str) -> bytes:\n        ...\n", "python"),
    ("abstractmethod stub",
     "import abc\nclass B(abc.ABC):\n    @abc.abstractmethod\n    def run(self): ...\n", "python"),
    ("documented except pass",
     "def shut(sock):\n    try:\n        sock.close()\n    except OSError:\n        pass  # already closed by peer\n", "python"),
    ("docstring says brevity",
     'def f(x):\n    """Names are short for brevity."""\n    return x * 2\n', "python"),
    ("real python function",
     'def add(a: int, b: int) -> int:\n    if not isinstance(a, int):\n        raise TypeError("a must be int")\n    return a + b\n', "python"),
    ("real js handler",
     "function handler(req, res) {\n  const id = req.params.id;\n  res.json({ id });\n}\n", "javascript"),
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
    print(f"Adversarial corpus: {len(VIOLATIONS)} violations, "
          f"{len(LEGITIMATE)} legitimate samples, {total} total\n")
    for label, _ in CONFIGURATIONS:
        correct, misses = scores[label]
        print(f"  {label:<{width}}  {correct:>2}/{total}  ({100 * correct // total}%)")
        for miss in misses:
            print(f"  {'':<{width}}    - {miss}")

    union_correct = scores["union (shipped)"][0]
    print()
    if union_correct < UNION_BASELINE:
        print(f"REGRESSION: union scored {union_correct}/{total}, "
              f"below the recorded baseline of {UNION_BASELINE}.")
        return 1
    print(f"Union at or above baseline ({union_correct}/{total} >= {UNION_BASELINE}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
