#!/usr/bin/env python3
"""Test suite for the diff-aware PR review stack.

Covers, bottom-up:
  * review.diff       - unified diff parsing: line attribution, renames,
                        binary/deleted files, hunk-boundary edge cases, bounds
  * review.engine     - attribution of findings to added lines, pre-existing
                        debt separation, per-file modes, verdict aggregation
  * review.report     - Actions annotation escaping, GitHub review payloads,
                        the never-APPROVE invariant, comment budgets
  * review.cli        - end-to-end runs against real temp worktrees and a real
                        temp git repository, exit-code contract
  * server tool       - review_patch over the JSON-RPC dispatcher

Run: python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution import server  # noqa: E402 - path must be set before import.
from persona_constitution.review import cli, diff, engine, report  # noqa: E402

XAST_ACTIVE = __import__("persona_constitution.ast_bridge", fromlist=["xast_findings"]).xast_findings(
    "function probe() {\n}\n", "javascript"
)[1]


def make_diff(path, added_lines, new_start=1, old_path=None, new_file=False):
    """Build a minimal single-file unified diff whose hunk adds given lines."""
    old_path = old_path or path
    count = len(added_lines)
    header = [f"diff --git a/{old_path} b/{path}"]
    if new_file:
        header.append("new file mode 100644")
        header.append("index 0000000..1111111")
        header.append("--- /dev/null")
    else:
        header.append("index 2222222..3333333 100644")
        header.append(f"--- a/{old_path}")
    header.append(f"+++ b/{path}")
    header.append(f"@@ -{0 if new_file else new_start},0 +{new_start},{count} @@")
    return "\n".join(header + [f"+{line}" for line in added_lines]) + "\n"


class TestDiffParsing(unittest.TestCase):
    def test_added_lines_carry_new_file_numbers(self):
        text = (
            "diff --git a/pkg/mod.py b/pkg/mod.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/pkg/mod.py\n"
            "+++ b/pkg/mod.py\n"
            "@@ -10,3 +10,5 @@ def context():\n"
            " kept = 1\n"
            "+added_a = 2\n"
            " kept2 = 3\n"
            "+added_b = 4\n"
            "-removed = 5\n"
            " kept3 = 6\n"
        )
        parsed = diff.parse_unified_diff(text)
        self.assertEqual(len(parsed), 1)
        record = parsed[0]
        self.assertEqual(record.path, "pkg/mod.py")
        self.assertEqual(record.status, diff.STATUS_MODIFIED)
        self.assertEqual(record.added_lines, {11: "added_a = 2", 13: "added_b = 4"})

    def test_new_deleted_renamed_binary(self):
        text = (
            "diff --git a/new.py b/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+x = 1\n"
            "diff --git a/gone.py b/gone.py\n"
            "deleted file mode 100644\n"
            "--- a/gone.py\n"
            "+++ /dev/null\n"
            "@@ -1,1 +0,0 @@\n"
            "-x = 1\n"
            "diff --git a/old_name.py b/new_name.py\n"
            "similarity index 90%\n"
            "rename from old_name.py\n"
            "rename to new_name.py\n"
            "--- a/old_name.py\n"
            "+++ b/new_name.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-y = 1\n"
            "+y = 2\n"
            "diff --git a/img.png b/img.png\n"
            "Binary files a/img.png and b/img.png differ\n"
        )
        new, gone, renamed, binary = diff.parse_unified_diff(text)
        self.assertEqual((new.status, new.added_lines), (diff.STATUS_ADDED, {1: "x = 1"}))
        self.assertEqual((gone.status, gone.path, gone.added_lines), (diff.STATUS_DELETED, "gone.py", {}))
        self.assertEqual(
            (renamed.status, renamed.old_path, renamed.path, renamed.added_lines),
            (diff.STATUS_RENAMED, "old_name.py", "new_name.py", {1: "y = 2"}),
        )
        self.assertTrue(binary.is_binary)

    def test_trailing_deletions_are_not_headers(self):
        # A hunk ending in removed lines that resemble '---' headers must not
        # corrupt path state.
        text = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1,3 +1,1 @@\n"
            "+kept = 1\n"
            "--- not a header, a removed line\n"
            "-- another removed line\n"
            "-last removed\n"
        )
        parsed = diff.parse_unified_diff(text)
        self.assertEqual(parsed[0].path, "a.py")
        self.assertEqual(parsed[0].added_lines, {1: "kept = 1"})

    def test_no_newline_marker_is_neutral(self):
        text = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1,1 +1,1 @@\n"
            "+x = 1\n"
            "\\ No newline at end of file\n"
        )
        self.assertEqual(diff.parse_unified_diff(text)[0].added_lines, {1: "x = 1"})

    def test_oversized_diff_rejected(self):
        with self.assertRaises(ValueError):
            diff.parse_unified_diff("x" * (diff.MAX_DIFF_BYTES + 1))

    def test_git_octal_quoted_unicode_path(self):
        text = (
            'diff --git "a/caf\\303\\251/mod\\303\\250le.py" "b/caf\\303\\251/mod\\303\\250le.py"\n'
            '--- "a/caf\\303\\251/mod\\303\\250le.py"\n'
            '+++ "b/caf\\303\\251/mod\\303\\250le.py"\n'
            "@@ -1,1 +1,1 @@\n"
            "+x = 1\n"
        )
        parsed = diff.parse_unified_diff(text)
        self.assertEqual(parsed[0].path, "caf\u00e9/mod\u00e8le.py")
        self.assertEqual(parsed[0].added_lines, {1: "x = 1"})

    def test_submodule_and_mode_only_changes_are_harmless(self):
        text = (
            "diff --git a/vendor/lib b/vendor/lib\n"
            "index 1111111..2222222 160000\n"
            "--- a/vendor/lib\n"
            "+++ b/vendor/lib\n"
            "@@ -1 +1 @@\n"
            "-Subproject commit 1111111111111111111111111111111111111111\n"
            "+Subproject commit 2222222222222222222222222222222222222222\n"
            "diff --git a/run.sh b/run.sh\n"
            "old mode 100644\n"
            "new mode 100755\n"
        )
        submodule, mode_only = diff.parse_unified_diff(text)
        self.assertEqual(submodule.path, "vendor/lib")
        self.assertEqual(
            list(submodule.added_lines.values()),
            ["Subproject commit 2222222222222222222222222222222222222222"],
        )
        self.assertEqual(mode_only.added_lines, {})
        review = engine.review_patch(text)
        self.assertEqual(review["verdict"], "PASS")
        self.assertEqual(review["totals"]["files_skipped"], 2)

    def test_crlf_diff_lines_are_clean(self):
        text = "diff --git a/m.py b/m.py\r\n--- a/m.py\r\n+++ b/m.py\r\n@@ -0,0 +1,1 @@\r\n+value = 1\r\n"
        parsed = diff.parse_unified_diff(text)
        self.assertEqual(parsed[0].added_lines, {1: "value = 1"})

    def test_hunk_headers_with_omitted_counts(self):
        text = "diff --git a/one.py b/one.py\n--- a/one.py\n+++ b/one.py\n@@ -1 +1 @@\n-old = 1\n+new = 2\n"
        self.assertEqual(diff.parse_unified_diff(text)[0].added_lines, {1: "new = 2"})

    def test_garbage_prefix_and_lying_headers_never_crash(self):
        adversarial = [
            "From: mailer\nSubject: [PATCH] x\n\ndiff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,99 +1,99 @@\n+only = 1\n",
            "diff --git a/a.py b/a.py\n@@ -1,2 +1,2 @@\n+x = 1\n@@ garbage @@\n",
            "diff --git a/a.py b/a.py\n--- a/a.py\n",
            "not a diff at all\njust text\n",
            "",
        ]
        for text in adversarial:
            parsed = diff.parse_unified_diff(text)
            self.assertIsInstance(parsed, list)


class TestReviewEngine(unittest.TestCase):
    def test_added_stub_fails_in_hunk_mode(self):
        text = make_diff("svc/handler.py", ["def process(data):", "    # TODO: implement later", "    pass"])
        review = engine.review_patch(text)
        self.assertEqual(review["verdict"], "FAIL")
        self.assertEqual(review["totals"]["files_reviewed"], 1)
        self.assertEqual(review["files"][0]["mode"], engine.MODE_HUNK)
        lines = {finding["line"] for finding in review["files"][0]["findings"]}
        self.assertTrue(lines & {1, 2, 3}, f"findings must map to added lines, got {lines}")

    def test_full_mode_attributes_only_added_lines(self):
        source = (
            "def old_stub():\n    pass  # TODO: implement later\n\n\ndef fresh(a, b):\n    return a + b\n"
        )
        text = make_diff("svc/mod.py", ["def fresh(a, b):", "    return a + b"], new_start=5)
        review = engine.review_patch(text, file_contents={"svc/mod.py": source})
        file_report = review["files"][0]
        self.assertEqual(file_report["mode"], engine.MODE_FULL)
        self.assertEqual(review["verdict"], "PASS", review)
        self.assertGreater(
            file_report["pre_existing"]["violations"] + file_report["pre_existing"]["warnings"], 0
        )

    def test_full_mode_fails_on_added_violation(self):
        source = "def save(record):\n    raise NotImplementedError\n"
        text = make_diff("svc/save.py", ["def save(record):", "    raise NotImplementedError"])
        review = engine.review_patch(text, file_contents={"svc/save.py": source})
        self.assertEqual(review["verdict"], "FAIL")
        self.assertEqual(review["totals"]["pre_existing_violations"], 0)

    def test_non_code_and_deleted_files_are_skipped(self):
        text = make_diff("README.md", ["## TODO: implement later"]) + (
            "diff --git a/dead.py b/dead.py\n"
            "deleted file mode 100644\n"
            "--- a/dead.py\n"
            "+++ /dev/null\n"
            "@@ -1,1 +0,0 @@\n"
            "-x = 1\n"
        )
        review = engine.review_patch(text)
        self.assertEqual(review["verdict"], "PASS")
        self.assertEqual(review["totals"]["files_skipped"], 2)
        modes = {f["path"]: f["mode"] for f in review["files"]}
        self.assertEqual(modes["README.md"], "skipped-not-code")
        self.assertEqual(modes["dead.py"], "skipped-deleted")

    def test_warning_only_yields_review(self):
        text = make_diff("svc/w.py", ["# XXX revisit this ordering"])
        review = engine.review_patch(text)
        self.assertEqual(review["verdict"], "REVIEW")

    def test_max_files_bound(self):
        text = "".join(make_diff(f"f{i}.py", ["x = 1"]) for i in range(engine.MAX_FILES + 1))
        with self.assertRaises(ValueError):
            engine.review_patch(text)

    def test_exclude_globs_skip_fixture_corpora(self):
        stub_lines = ["def process(data):", "    # TODO: implement later", "    pass"]
        text = make_diff("tests/fixtures.py", stub_lines) + make_diff("svc/real.py", stub_lines)
        review = engine.review_patch(text, exclude=["tests/*"])
        modes = {f["path"]: f["mode"] for f in review["files"]}
        self.assertEqual(modes["tests/fixtures.py"], "skipped-excluded")
        self.assertEqual(review["verdict"], "FAIL")
        self.assertEqual(review["totals"]["files_reviewed"], 1)
        fully_excluded = engine.review_patch(text, exclude=["tests/*", "svc/*"])
        self.assertEqual(fully_excluded["verdict"], "PASS")

    @unittest.skipUnless(XAST_ACTIVE, "optional `ast` extra not installed")
    def test_full_mode_js_null_stub_fails_via_xast(self):
        source = "function getUser(id) {\n  return null;\n}\n"
        text = make_diff("web/user.js", ["function getUser(id) {", "  return null;", "}"], new_file=True)
        review = engine.review_patch(text, file_contents={"web/user.js": source})
        self.assertEqual(review["verdict"], "FAIL")
        self.assertIn("constitution-xast", review["engines"])


class TestReportRenderers(unittest.TestCase):
    def _review(self):
        text = make_diff("svc/handler.py", ["def process(d):", "    pass  # TODO: implement later"])
        return engine.review_patch(text)

    def test_annotations_shape_and_escaping(self):
        annotations = report.to_annotations(self._review())
        errors = [a for a in annotations if a.startswith("::error ")]
        self.assertTrue(errors, annotations)
        self.assertIn("file=svc/handler.py", errors[0])
        self.assertIn("line=", errors[0])
        self.assertTrue(annotations[-1].startswith("::notice "))
        escaped = report._escape_annotation_message("a%b\nc")
        self.assertEqual(escaped, "a%25b%0Ac")

    def test_github_payload_fail_requests_changes_and_never_approves(self):
        payload = report.to_github_review(self._review(), "deadbeef")
        self.assertEqual(payload["event"], "REQUEST_CHANGES")
        self.assertEqual(payload["commit_id"], "deadbeef")
        self.assertTrue(payload["comments"])
        first = payload["comments"][0]
        self.assertEqual(first["side"], "RIGHT")
        self.assertEqual(first["path"], "svc/handler.py")
        clean = engine.review_patch(make_diff("svc/ok.py", ["VALUE = 1"]))
        self.assertEqual(report.to_github_review(clean, "deadbeef")["event"], "COMMENT")

    def test_comment_budget_overflows_into_body(self):
        lines = [f"# TODO: implement part {i}" for i in range(60)]
        review = engine.review_patch(make_diff("svc/big.py", lines))
        payload = report.to_github_review(review, "deadbeef", max_comments=5)
        self.assertEqual(len(payload["comments"]), 5)
        self.assertIn("exceeded the inline comment budget", payload["body"])

    def test_text_report_names_files_and_lines(self):
        text = report.to_text(self._review())
        self.assertIn("verdict: FAIL", text)
        self.assertIn("svc/handler.py:", text)


class TestCli(unittest.TestCase):
    @staticmethod
    def _run_cli(argv):
        """Invoke cli.main with stdout/stderr captured; returns (code, stdout)."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue()

    def _write_worktree(self, tmp):
        worktree = Path(tmp)
        target = worktree / "svc"
        target.mkdir()
        (target / "handler.py").write_text(
            "def process(data):\n    # TODO: implement later\n    pass\n", encoding="utf-8"
        )
        diff_path = worktree / "change.diff"
        diff_path.write_text(
            make_diff(
                "svc/handler.py",
                ["def process(data):", "    # TODO: implement later", "    pass"],
                new_file=True,
            ),
            encoding="utf-8",
        )
        return worktree, diff_path

    def test_diff_mode_fails_gate_with_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree, diff_path = self._write_worktree(tmp)
            code, stdout = self._run_cli(["--diff", str(diff_path), "--root", str(worktree), "--json"])
            self.assertEqual(code, cli.EXIT_GATE_FAILED)
            self.assertEqual(json.loads(stdout)["verdict"], "FAIL")

    def test_annotate_mode_emits_workflow_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree, diff_path = self._write_worktree(tmp)
            code, stdout = self._run_cli(["--diff", str(diff_path), "--root", str(worktree), "--annotate"])
            self.assertEqual(code, cli.EXIT_GATE_FAILED)
            self.assertIn("::error file=svc/handler.py", stdout)

    def test_git_mode_reviews_working_tree_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env_commands = [
                ["git", "init", "-q"],
                ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"],
            ]
            for command in env_commands:
                subprocess.run(command, cwd=repo, check=True, capture_output=True)
            module = repo / "mod.py"
            module.write_text("def ok():\n    return 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, capture_output=True)
            module.write_text(
                "def ok():\n    return 1\n\n\ndef added():\n    raise NotImplementedError\n",
                encoding="utf-8",
            )
            code, stdout = self._run_cli(["--git", "HEAD", "--root", str(repo), "--json"])
            self.assertEqual(code, cli.EXIT_GATE_FAILED)
            review = json.loads(stdout)
            self.assertEqual(review["files"][0]["mode"], engine.MODE_FULL)

    def test_clean_change_passes_with_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            (worktree / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
            diff_path = worktree / "ok.diff"
            diff_path.write_text(make_diff("ok.py", ["VALUE = 1"], new_file=True), encoding="utf-8")
            code, stdout = self._run_cli(["--diff", str(diff_path), "--root", str(worktree), "--json"])
            self.assertEqual(code, cli.EXIT_OK)
            self.assertEqual(json.loads(stdout)["verdict"], "PASS")

    def test_post_without_github_is_operational_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, diff_path = self._write_worktree(tmp)
            code, _ = self._run_cli(["--diff", str(diff_path), "--post"])
            self.assertEqual(code, cli.EXIT_OPERATIONAL_ERROR)

    def test_malformed_github_spec_is_operational_error(self):
        code, _ = self._run_cli(["--github", "not-a-spec"])
        self.assertEqual(code, cli.EXIT_OPERATIONAL_ERROR)


class TestServerReviewPatchTool(unittest.TestCase):
    def setUp(self):
        self.text = server.load_constitution(
            PROJECT_ROOT / "persona_constitution" / "data" / "CONSTITUTION.md"
        )

    def _call(self, arguments, request_id=1):
        return server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": "review_patch", "arguments": arguments},
            },
            self.text,
        )

    def test_review_patch_tool_end_to_end(self):
        arguments = {
            "diff": make_diff(
                "svc/handler.py", ["def process(data):", "    # TODO: implement later", "    pass"]
            )
        }
        response = self._call(arguments)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertTrue(response["result"].get("isError") is None or not response["result"]["isError"])

    def test_review_patch_requires_diff(self):
        response = self._call({})
        self.assertTrue(response["result"]["isError"])

    def test_review_patch_rejects_non_dict_files(self):
        response = self._call({"diff": make_diff("a.py", ["x = 1"]), "files": "nope"})
        self.assertTrue(response["result"]["isError"])

    def test_review_patch_rejects_bad_require_tests(self):
        response = self._call({"diff": make_diff("a.py", ["x = 1"]), "require_tests": "always"})
        self.assertTrue(response["result"]["isError"])

    def test_review_patch_enforces_test_presence_when_asked(self):
        lines = [f"value_{i} = {i}" for i in range(6)]
        response = self._call({"diff": make_diff("svc/mod.py", lines), "require_tests": "fail"})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["verdict"], "FAIL")
        classes = [f["class"] for report in payload["files"] for f in report["findings"]]
        self.assertIn("C-03 - Testing Discipline", classes)

    def test_tool_is_listed(self):
        response = server.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, self.text)
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("review_patch", names)


if __name__ == "__main__":
    unittest.main()
