#!/usr/bin/env python3
"""CWE tagging and SARIF rendering contracts.

CWE: every finding carries a MITRE weakness ID exactly when a defensible
mapping exists - CWE-546 for deferral prose/markers, CWE-1071 for empty
bodies, CWE-1069 for empty exception handling, CWE-684 for stubs that
fake their contract, CWE-561/570/571 for dead and constant branches,
CWE-1120/1121 for the Po10 metrics. The engines attach identical IDs to
byte-identical finding texts, so deduplication can never merge findings
that disagree about their weakness class. Absence of `cwe` is a
statement ("no honest mapping"), never an omission - and these tests pin
both directions.

SARIF: `to_sarif` renders a review as a SARIF 2.1.0 log suitable for
GitHub code scanning - stable ruleIds, level mapping, real line
coordinates, CWE tags on rules and results, and nothing from skipped
files or pre-existing debt (SARIF gates exactly what the verdict gates).

Run: python3 -m unittest discover -s tests -v
Dependencies: Python 3.9+ standard library only (tree-sitter tests skip
without the `ast` extra).
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution import ast_bridge, scanner  # noqa: E402 - path first.
from persona_constitution._version import __version__  # noqa: E402
from persona_constitution.review import cli  # noqa: E402
from persona_constitution.review.engine import review_patch  # noqa: E402
from persona_constitution.review.report import to_sarif  # noqa: E402

XAST_ACTIVE = ast_bridge.xast_findings("function probe() {\n}\n", "javascript")[1]
NEEDS_TREE_SITTER = unittest.skipUnless(
    XAST_ACTIVE, "optional `ast` extra (tree-sitter + grammars) not installed"
)


def _cwe_for(code, language, needle):
    """The cwe of the first finding whose text contains `needle`."""
    result = scanner.scan_code(code, language=language)
    for finding in result["findings"]:
        if needle in finding["finding"]:
            return finding.get("cwe")
    raise AssertionError(f"no finding containing {needle!r} in {result['findings']}")


class TestCweAssignments(unittest.TestCase):
    """Each weakness family carries its documented CWE, per engine."""

    def test_deferral_prose_is_suspicious_comment(self):
        self.assertEqual(_cwe_for("// left as an exercise\n", "javascript", "exercise"), "CWE-546")

    def test_todo_marker_is_suspicious_comment(self):
        self.assertEqual(_cwe_for("# TODO implement retry\nx = 1\n", "python", "marker: todo"), "CWE-546")

    def test_empty_catch_is_empty_exception_block(self):
        code = "try { f(); } catch (e) {}\n"
        self.assertEqual(_cwe_for(code, "javascript", "catch"), "CWE-1069")

    def test_bare_except_pass_is_empty_exception_block(self):
        code = "try:\n    f()\nexcept:\n    pass\n"
        self.assertEqual(_cwe_for(code, "python", "except: pass"), "CWE-1069")

    def test_python_stub_body_is_empty_code_block(self):
        code = "def f():\n    pass\n"
        self.assertEqual(_cwe_for(code, "python", "no implementation"), "CWE-1071")

    def test_not_implemented_throw_is_incorrect_provision(self):
        code = 'function f() { throw new Error("not implemented"); }\n'
        self.assertEqual(_cwe_for(code, "javascript", "exception stub"), "CWE-684")

    def test_unreachable_code_is_dead_code(self):
        code = "def f():\n    return 1\n    x = 2\n"
        self.assertEqual(_cwe_for(code, "python", "Unreachable"), "CWE-561")

    def test_constant_condition_polarity_selects_the_variant(self):
        always_true = "def f():\n    if True:\n        return 1\n    return 2\n"
        always_false = "def f():\n    if False:\n        return 1\n    return 2\n"
        self.assertEqual(_cwe_for(always_true, "python", "constant"), "CWE-571")
        self.assertEqual(_cwe_for(always_false, "python", "constant"), "CWE-570")

    def test_complexity_metric_is_cwe_1121(self):
        branches = "".join(f"    if x == {i}:\n        x += {i}\n" for i in range(11))
        code = f"def f(x):\n{branches}    return x\n"
        self.assertEqual(_cwe_for(code, "python", "cyclomatic complexity"), "CWE-1121")

    def test_csi_prefix_mapping_and_honest_absence(self):
        self.assertEqual(scanner._csi_cwe("todo_docstring_todo"), "CWE-546")
        self.assertEqual(scanner._csi_cwe("empty_function"), "CWE-1071")
        self.assertEqual(scanner._csi_cwe("stub_implementation"), "CWE-684")
        # No defensible MITRE weakness exists for these; absence is the
        # honest answer and must stay absent.
        self.assertIsNone(scanner._csi_cwe("mock_data_generation"))
        self.assertIsNone(scanner._csi_cwe("always_success"))
        self.assertIsNone(scanner._csi_cwe(None))


@NEEDS_TREE_SITTER
class TestCrossEngineCweConsistency(unittest.TestCase):
    """The xast tier and the regex tier attach the same CWE to the same
    finding text, so the deduplicated finding is unambiguous."""

    def test_empty_function_agrees_across_engines(self):
        result = scanner.scan_code("function f() {\n}\n", language="javascript")
        empties = [f for f in result["findings"] if "empty body" in f["finding"]]
        self.assertEqual(len(empties), 1, "dedupe must collapse the engines' findings")
        self.assertEqual(empties[0].get("cwe"), "CWE-1071")

    def test_prose_rules_and_xast_constants_never_disagree(self):
        """Every finding text the xast engine shares with PROSE_RULES must
        carry the same CWE in the rule table as the bridge attaches."""
        prose_cwe_by_text = {rule[2]: rule[5] for rule in scanner.PROSE_RULES}
        shared = {
            ast_bridge.TEXT_EMPTY_FUNCTION: "CWE-1071",
            ast_bridge.TEXT_HARDCODED_RETURN: "CWE-684",
            ast_bridge.TEXT_EMPTY_CATCH: "CWE-1069",
            ast_bridge.TEXT_NOT_IMPLEMENTED: "CWE-684",
            ast_bridge.TEXT_PANIC_STUB: "CWE-684",
            ast_bridge.TEXT_RUST_MACRO: "CWE-684",
        }
        for text, expected in shared.items():
            with self.subTest(text=text):
                self.assertEqual(prose_cwe_by_text[text], expected)


def _diff_for(path, added_lines):
    body = "\n".join("+" + line for line in added_lines)
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(added_lines)} @@\n"
        f"{body}\n"
    )


def _sample_review():
    """A review with one violation, one warning, and one skipped file."""
    diff = _diff_for("prod.py", ["# TODO implement retry", "x = 1"]) + _diff_for("notes.md", ["prose only"])
    return review_patch(diff, require_tests="warn", min_test_trigger_lines=1)


class TestSarifRendering(unittest.TestCase):
    """The SARIF log is valid, complete, and gated exactly like the verdict."""

    def setUp(self):
        self.review = _sample_review()
        self.sarif = to_sarif(self.review, "9.9.9")

    def test_envelope(self):
        self.assertEqual(self.sarif["version"], "2.1.0")
        self.assertIn("sarif-schema-2.1.0", self.sarif["$schema"])
        driver = self.sarif["runs"][0]["tool"]["driver"]
        self.assertEqual(driver["name"], "persona-pr-review")
        self.assertEqual(driver["version"], "9.9.9")
        json.dumps(self.sarif)  # must be serialisable as-is

    def test_results_match_attributed_findings_exactly(self):
        expected = sum(
            len(report["findings"])
            for report in self.review["files"]
            if not report["mode"].startswith("skipped-")
        )
        results = self.sarif["runs"][0]["results"]
        self.assertEqual(len(results), expected)
        self.assertGreater(expected, 0)
        # The skipped markdown file contributes nothing.
        uris = {
            location["physicalLocation"]["artifactLocation"]["uri"]
            for result in results
            for location in result["locations"]
        }
        self.assertEqual(uris, {"prod.py"})

    def test_levels_map_severities(self):
        levels = {result["level"] for result in self.sarif["runs"][0]["results"]}
        self.assertEqual(levels, {"error", "warning"})

    def test_rule_ids_are_stable_slugs_and_indexed(self):
        run = self.sarif["runs"][0]
        rules = run["tool"]["driver"]["rules"]
        rule_ids = [rule["id"] for rule in rules]
        self.assertEqual(rule_ids, sorted(rule_ids))
        for rule_id in rule_ids:
            self.assertRegex(rule_id, r"^persona\.[a-z0-9-]+$")
        for result in run["results"]:
            self.assertEqual(rules[result["ruleIndex"]]["id"], result["ruleId"])

    def test_cwe_travels_on_rules_and_results(self):
        run = self.sarif["runs"][0]
        tagged_rules = [
            rule
            for rule in run["tool"]["driver"]["rules"]
            if any(tag.startswith("CWE-") for tag in rule["properties"]["tags"])
        ]
        self.assertTrue(tagged_rules, "no rule carries a CWE tag")
        tagged_results = [result for result in run["results"] if "cwe" in result["properties"]]
        self.assertTrue(tagged_results, "no result carries a CWE property")
        self.assertRegex(tagged_results[0]["properties"]["cwe"], r"^CWE-\d+$")

    def test_line_coordinates_are_positive_and_real(self):
        for result in self.sarif["runs"][0]["results"]:
            start = result["locations"][0]["physicalLocation"]["region"]["startLine"]
            self.assertGreaterEqual(start, 1)


class TestCliSarifFile(unittest.TestCase):
    """--sarif-file writes a parseable log and fails operationally when
    the path cannot be written."""

    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_writes_valid_sarif_alongside_text_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            diff_path = Path(tmp) / "change.diff"
            diff_path.write_text(_diff_for("prod.py", ["# TODO implement retry"]), encoding="utf-8")
            sarif_path = Path(tmp) / "out.sarif"
            code, out, err = self._run(
                ["--diff", str(diff_path), "--root", tmp, "--sarif-file", str(sarif_path)]
            )
            self.assertEqual(code, cli.EXIT_GATE_FAILED)  # the TODO is a violation
            self.assertIn("verdict: FAIL", out)
            self.assertIn(f"SARIF written to {sarif_path}", err)
            document = json.loads(sarif_path.read_text(encoding="utf-8"))
            self.assertEqual(document["version"], "2.1.0")
            self.assertEqual(document["runs"][0]["tool"]["driver"]["version"], __version__)
            self.assertTrue(document["runs"][0]["results"])

    def test_unwritable_sarif_path_is_an_operational_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            diff_path = Path(tmp) / "change.diff"
            diff_path.write_text(_diff_for("prod.py", ["x = 1"]), encoding="utf-8")
            missing_dir = Path(tmp) / "does" / "not" / "exist" / "out.sarif"
            code, _, err = self._run(
                ["--diff", str(diff_path), "--root", tmp, "--sarif-file", str(missing_dir)]
            )
            self.assertEqual(code, cli.EXIT_OPERATIONAL_ERROR)
            self.assertIn("persona-pr-review:", err)


if __name__ == "__main__":
    unittest.main()
