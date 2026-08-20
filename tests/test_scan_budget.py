#!/usr/bin/env python3
"""Adversarial-input wall-clock budgets for the violation scanner.

The scanner runs inside CI gates over hostile input (any PR author controls
the bytes it scans). A regex with pathological backtracking turns that into
a denial of service on every consumer's pipeline: before the bounded
empty-catch pattern, the "catch bomb" below hung the scanner for minutes
(quadratic re-scanning to end-of-input at each unclosed "catch {/*").

Each case must finish inside HANG_BUDGET_SECONDS. The budget is deliberately
generous - an order of magnitude above the measured times on a laptop
(<= ~5 s) and far below hang-class behaviour (minutes) - so this suite is
immune to slow CI runners while still failing loudly on any reintroduced
catastrophic pattern.

The detection-contract tests pin what the bounded pattern must still catch,
so the DoS fix can never silently become a detection loss.

Run: python3 -m unittest discover -s tests -v
Dependencies: Python 3.9+ standard library only.
"""

import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution.scanner import scan_code  # noqa: E402 - path first.

HANG_BUDGET_SECONDS = 60.0

# Name -> adversarial input. Every case is at or under MAX_SCAN_BYTES, the
# size the server admits, so these are exactly the payloads a tool call can
# deliver.
PATHOLOGICAL_CASES = {
    "one megabyte on a single line": "x" * 1_000_000,
    "near-miss marker flood": "TOD" * 300_000,
    # The historical killer: unclosed block comments after catch braces.
    "unclosed catch-comment bomb": "catch {/*x " * 80_000,
    "modifier keyword chain flood": "public private static " * 45_000,
    "unclosed brace flood": "{" * 1_000_000,
    "half megabyte of honest python": "def f():\n    return 1\n" * 22_000,
}


class TestScannerTimeBudget(unittest.TestCase):
    """No admissible input may push the scanner into hang-class runtime."""

    def setUp(self):
        # Wall-clock budgets are meaningless under a tracer: coverage
        # instrumentation multiplies the scanner's regex/AST loops by one to
        # two orders of magnitude, so the same inputs that pass in seconds
        # here would time a coverage job out entirely. The detection-contract
        # tests below still run under coverage; only the stopwatch is
        # disarmed.
        if sys.gettrace() is not None or "coverage" in sys.modules:
            self.skipTest("wall-clock budgets are meaningless under a tracer")

    def test_pathological_inputs_complete_within_budget(self):
        for name, code in PATHOLOGICAL_CASES.items():
            with self.subTest(case=name):
                start = time.monotonic()
                result = scan_code(code)
                elapsed = time.monotonic() - start
                self.assertLess(
                    elapsed,
                    HANG_BUDGET_SECONDS,
                    f"{name!r} took {elapsed:.1f}s - hang-class regression",
                )
                self.assertIn("verdict", result)


class TestEmptyCatchDetectionContract(unittest.TestCase):
    """The bounded empty-catch pattern must keep catching what the unbounded
    one caught. If a future edit trades detection for speed, fail here."""

    def _catch_findings(self, code):
        result = scan_code(code, language="javascript")
        return [
            finding
            for finding in result["findings"]
            if "catch" in str(finding.get("rule", "")).lower()
            or "catch" in str(finding.get("detail", "")).lower()
            or "catch" in str(finding).lower()
        ]

    def test_bare_empty_catch_detected(self):
        self.assertTrue(self._catch_findings("try { f(); } catch (e) {\n}\n"))

    def test_single_line_comment_only_catch_detected(self):
        self.assertTrue(self._catch_findings("try { f(); } catch (e) { /* ignored */ }"))

    def test_multi_line_comment_only_catch_detected(self):
        code = "try { f(); } catch (e) {\n  /* deliberately\n     ignored */\n}\n"
        self.assertTrue(self._catch_findings(code))

    def test_handled_catch_not_flagged_as_empty(self):
        code = "try { f(); } catch (e) { report(e); rethrow(e); }"
        self.assertFalse(self._catch_findings(code))


if __name__ == "__main__":
    unittest.main()
