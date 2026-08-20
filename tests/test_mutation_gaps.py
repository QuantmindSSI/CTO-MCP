#!/usr/bin/env python3
"""Tests written to kill specific surviving mutants from the nightly run.

The first full mutation run (2138 mutants over the detector core) killed
70% and left clusters of survivors that are genuine contract gaps, not
equivalent mutants. Every test here was derived from an actual surviving
mutant diff (`mutmut show <id>`) and asserts the behaviour that mutant
falsifies:

  - engine._escalate_verdict: the C-03 policy escalation state machine
    (warn never downgrades or over-escalates, fail always gates).
  - engine._attribute_findings: pre-existing findings are counted by
    severity, and never leak into the gating totals.
  - diff._unquote_git_path: git's C-style/octal path quoting decodes to
    the exact path, so findings land on the right file.
  - scanner string-span masking: markers inside data strings are
    suppressed, markers in comments are reported - in both the Python
    and the generic tier.
  - engine._skip/_coverage_finding: the skip-report and C-03 finding
    shapes the renderers and GitHub payloads depend on.
  - ast_bridge metrics: the Po10 complexity/length limits fire exactly
    at their boundaries with exact numbers in the message.

Run: python3 -m unittest discover -s tests -v
Dependencies: Python 3.9+ standard library only (tree-sitter tests skip
without the `ast` extra).
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution import ast_bridge  # noqa: E402 - path must be set first.
from persona_constitution.review.diff import parse_unified_diff  # noqa: E402
from persona_constitution.review.engine import review_patch  # noqa: E402
from persona_constitution.scanner import scan_code  # noqa: E402

XAST_ACTIVE = ast_bridge.xast_findings("function probe() {\n}\n", "javascript")[1]
NEEDS_TREE_SITTER = unittest.skipUnless(
    XAST_ACTIVE, "optional `ast` extra (tree-sitter + grammars) not installed"
)


def _diff_for(path, added_lines, start_line=1):
    """A minimal one-hunk unified diff adding `added_lines` to `path`."""
    count = len(added_lines)
    body = "\n".join("+" + line for line in added_lines)
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +{start_line},{count} @@\n"
        f"{body}\n"
    )


class TestEscalateVerdictStateMachine(unittest.TestCase):
    """Kills the _escalate_verdict boolean-operator mutants: every
    (severity, prior verdict) combination is pinned."""

    def _review(self, require_tests, file_lines):
        diff = _diff_for("prod.py", file_lines)
        return review_patch(diff, require_tests=require_tests, min_test_trigger_lines=1)

    def test_warn_policy_escalates_clean_file_to_review_only(self):
        review = self._review("warn", ["x = 1", "y = 2"])
        self.assertEqual(review["verdict"], "REVIEW")
        self.assertEqual(review["files"][0]["verdict"], "REVIEW")
        self.assertEqual(review["totals"]["violations"], 0)

    def test_fail_policy_escalates_clean_file_to_fail(self):
        review = self._review("fail", ["x = 1", "y = 2"])
        self.assertEqual(review["verdict"], "FAIL")
        self.assertEqual(review["files"][0]["verdict"], "FAIL")

    def test_warn_policy_never_upgrades_a_failing_file_to_anything_else(self):
        """A file that already FAILs on its own violations stays FAIL under
        the warn policy - and the policy warning is still appended."""
        review = self._review("warn", ["def f():", "    pass  # TODO implement this later"])
        self.assertEqual(review["files"][0]["verdict"], "FAIL")
        classes = [finding["class"] for finding in review["files"][0]["findings"]]
        self.assertIn("C-03 - Testing Discipline", classes)

    def test_off_policy_never_escalates(self):
        review = self._review("off", ["x = 1", "y = 2"])
        self.assertEqual(review["verdict"], "PASS")
        self.assertEqual(review["files"][0]["findings"], [])

    def test_touching_tests_disarms_the_policy_entirely(self):
        diff = _diff_for("prod.py", ["x = 1", "y = 2"]) + _diff_for(
            "tests/test_prod.py", ["def test_x():", "    assert True"]
        )
        review = review_patch(diff, require_tests="fail", min_test_trigger_lines=1)
        self.assertEqual(review["verdict"], "PASS")


class TestPreExistingSeveritySplit(unittest.TestCase):
    """Kills the _attribute_findings severity-comparison mutants: the
    pre-existing counters are split by severity and never gate."""

    def test_pre_existing_violations_and_warnings_counted_separately(self):
        # The diff adds only line 1; the supplied full file carries a
        # violation (TODO marker) on line 3 and a warning (bare except:
        # pass without comment) on lines 5-6 - all outside the change.
        source = (
            "x = 1\n"
            "y = 2\n"
            "# TODO implement the cache eviction\n"
            "def f():\n"
            "    try:\n"
            "        return g()\n"
            "    except Exception:\n"
            "        pass\n"
        )
        diff = _diff_for("legacy.py", ["x = 1"])
        review = review_patch(diff, file_contents={"legacy.py": source})

        totals = review["totals"]
        self.assertEqual(review["verdict"], "PASS", review)
        self.assertEqual(totals["violations"], 0)
        self.assertEqual(totals["warnings"], 0)
        self.assertGreaterEqual(totals["pre_existing_violations"], 1)
        self.assertGreaterEqual(totals["pre_existing_warnings"], 1)

    def test_violation_on_added_line_is_attributed_not_pre_existing(self):
        source = "# TODO implement the cache eviction\nx = 1\n"
        diff = _diff_for("fresh.py", ["# TODO implement the cache eviction", "x = 1"])
        review = review_patch(diff, file_contents={"fresh.py": source})
        self.assertEqual(review["verdict"], "FAIL")
        self.assertEqual(review["totals"]["pre_existing_violations"], 0)
        self.assertGreaterEqual(review["totals"]["violations"], 1)


class TestGitPathUnquoting(unittest.TestCase):
    """Kills the _unquote_git_path decode-table mutants with exact paths."""

    def _single_path(self, quoted):
        diff = (
            f'diff --git "a/{quoted}" "b/{quoted}"\n'
            f'--- "a/{quoted}"\n'
            f'+++ "b/{quoted}"\n'
            "@@ -0,0 +1,1 @@\n"
            "+x = 1\n"
        )
        files = parse_unified_diff(diff)
        self.assertEqual(len(files), 1)
        return files[0].path

    def test_octal_escapes_decode_to_utf8(self):
        # \303\244 is UTF-8 for a-umlaut.
        self.assertEqual(self._single_path("p\\303\\244th.py"), "päth.py")

    def test_c_escapes_decode(self):
        self.assertEqual(self._single_path("tab\\there.py"), "tab\there.py")

    def test_escaped_backslash_and_quote(self):
        self.assertEqual(self._single_path('back\\\\slash\\"q.py'), 'back\\slash"q.py')

    def test_unquoted_path_passes_through(self):
        diff = _diff_for("plain/path.py", ["x = 1"])
        self.assertEqual(parse_unified_diff(diff)[0].path, "plain/path.py")


class TestStringSpanSuppression(unittest.TestCase):
    """Kills span-computation mutants in both string-masking tiers: a
    marker inside a data string is data; the same marker in a comment is
    a finding, at the exact line."""

    def _lines_flagged(self, code, language):
        result = scan_code(code, language=language)
        return {finding["line"] for finding in result["findings"]}

    def test_python_marker_in_string_suppressed_in_comment_reported(self):
        code = 'message = "TODO: not a real deferral"\n# TODO implement retry\nx = 1\n'
        flagged = self._lines_flagged(code, "python")
        self.assertNotIn(1, flagged)
        self.assertIn(2, flagged)

    def test_generic_single_and_double_quoted_strings_suppressed(self):
        # "left as an exercise" is a suppressible prose rule: the exact same
        # marker must be data inside quotes and a finding in a comment.
        code = (
            'const a = "left as an exercise";\n'
            "const b = 'left as an exercise';\n"
            "// left as an exercise for the reader\n"
        )
        flagged = self._lines_flagged(code, "javascript")
        self.assertNotIn(1, flagged)
        self.assertNotIn(2, flagged)
        self.assertIn(3, flagged)

    def test_generic_escaped_quote_does_not_end_the_string_early(self):
        code = 'const s = "escaped \\" left as an exercise inside";\nlet x = 1;\n'
        flagged = self._lines_flagged(code, "javascript")
        self.assertNotIn(1, flagged)


class TestSkipAndCoverageFindingShapes(unittest.TestCase):
    """Kills the dict-literal mutants in _skip and _coverage_finding: the
    renderers and GitHub payload builders consume these exact shapes."""

    def test_skip_report_shape(self):
        diff = _diff_for("notes.md", ["just prose"])
        review = review_patch(diff)
        report = review["files"][0]
        self.assertEqual(report["path"], "notes.md")
        self.assertEqual(report["mode"], "skipped-not-code")
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["pre_existing"], {"violations": 0, "warnings": 0})
        self.assertEqual(review["totals"]["files_skipped"], 1)
        self.assertEqual(review["totals"]["files_reviewed"], 0)

    def test_excluded_report_shape(self):
        diff = _diff_for("generated/schema.py", ["x = 1"])
        review = review_patch(diff, exclude=["generated/*"])
        self.assertEqual(review["files"][0]["mode"], "skipped-excluded")

    def test_coverage_finding_anchors_first_added_line_and_class(self):
        diff = _diff_for("prod.py", ["alpha = 1", "beta = 2"], start_line=41)
        review = review_patch(diff, require_tests="warn", min_test_trigger_lines=1)
        policy = [
            finding
            for finding in review["files"][0]["findings"]
            if finding["class"] == "C-03 - Testing Discipline"
        ]
        self.assertEqual(len(policy), 1)
        self.assertEqual(policy[0]["line"], 41)
        self.assertEqual(policy[0]["severity"], "warning")
        self.assertEqual(policy[0]["source"], "constitution-policy")
        self.assertIn("2 line(s) of production logic", policy[0]["finding"])
        self.assertEqual(policy[0]["text"], "alpha = 1")

    def test_min_trigger_lines_boundary(self):
        """Exactly at the threshold fires; one below does not."""
        two_lines = _diff_for("prod.py", ["a = 1", "b = 2"])
        at_threshold = review_patch(two_lines, require_tests="warn", min_test_trigger_lines=2)
        below = review_patch(two_lines, require_tests="warn", min_test_trigger_lines=3)
        self.assertEqual(at_threshold["verdict"], "REVIEW")
        self.assertEqual(below["verdict"], "PASS")


@NEEDS_TREE_SITTER
class TestXastMetricBoundaries(unittest.TestCase):
    """Kills off-by-one mutants in ast_bridge complexity/length metrics."""

    @staticmethod
    def _js_function_with_ifs(if_count):
        branches = "".join(f"  if (x === {i}) {{ x += {i}; }}\n" for i in range(if_count))
        return f"function judge(x) {{\n{branches}  return x;\n}}\n"

    def _findings(self, code):
        findings, active = ast_bridge.xast_findings(code, "javascript")
        assert active, "xast engine reported inactive despite passing the probe"
        return findings

    def test_complexity_eleven_is_flagged_with_exact_number(self):
        findings = self._findings(self._js_function_with_ifs(10))  # 1 + 10 = 11
        messages = [f["finding"] for f in findings if "complexity" in f["finding"]]
        self.assertEqual(len(messages), 1)
        self.assertIn("complexity 11", messages[0])
        self.assertIn("'judge'", messages[0])

    def test_complexity_ten_is_not_flagged(self):
        findings = self._findings(self._js_function_with_ifs(9))  # 1 + 9 = 10
        self.assertEqual([f for f in findings if "complexity" in f["finding"]], [])

    def test_length_fifty_one_is_flagged_fifty_is_not(self):
        def function_of(total_lines):
            filler = "".join(f"  x += {i};\n" for i in range(total_lines - 3))
            return f"function long(x) {{\n{filler}  return x;\n}}\n"

        at_limit = self._findings(function_of(50))
        over = self._findings(function_of(51))
        self.assertEqual([f for f in at_limit if "lines long" in f["finding"]], [])
        over_messages = [f["finding"] for f in over if "lines long" in f["finding"]]
        self.assertEqual(len(over_messages), 1)
        self.assertIn("51 lines long", over_messages[0])


if __name__ == "__main__":
    unittest.main()
