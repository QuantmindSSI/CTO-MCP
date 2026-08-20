#!/usr/bin/env python3
"""Integration suite for the two-factor review gate.

Factor 1a is the staged gate (pre-commit), factor 1b the PR gate - the same
engine and the same .persona-review.json policy at both moments. This file
proves the factors against real git repositories:

  * Policy config: strict schema, loud failures, defaults.
  * C-03 test-presence enforcement at the engine level.
  * Staged gate correctness: the INDEX is the authority - a fixed worktree
    with a broken index must still fail.
  * Hook installer contract and a genuine `git commit` blocked by the
    installed hook (executed through a PATH shim onto this interpreter).
  * The PR-side flow over the same repository state (factor parity).

Run: python3 -m unittest discover -s tests -v
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution.review import cli, engine  # noqa: E402 - path first.
from persona_constitution.review.config import CONFIG_FILENAME, load_config  # noqa: E402

STUB_SOURCE = "def process(data):\n    # TODO: implement later\n    pass\n"
CLEAN_SOURCE = (
    "def add(a, b):\n"
    "    if not isinstance(a, int) or not isinstance(b, int):\n"
    "        raise TypeError('add requires integers')\n"
    "    return a + b\n"
)
CLEAN_TEST_SOURCE = (
    "import unittest\n"
    "from svc.calc import add\n"
    "\n"
    "\n"
    "class TestAdd(unittest.TestCase):\n"
    "    def test_adds(self):\n"
    "        self.assertEqual(add(2, 3), 5)\n"
    "\n"
    "    def test_rejects_non_int(self):\n"
    "        with self.assertRaises(TypeError):\n"
    "            add('2', 3)\n"
)


def run_cli(argv):
    """Invoke cli.main with output captured; returns (exit_code, stdout)."""
    import contextlib
    import io

    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(argv)
    return code, stdout.getvalue()


def git(repo, *arguments):
    """Run git in a temp repo; raises on failure."""
    subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
    )


def make_repo(tmp):
    """Initialise a committable git repository."""
    repo = Path(tmp)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "gate@example.invalid")
    git(repo, "config", "user.name", "gate")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo


class TestConfigContract(unittest.TestCase):
    def test_defaults_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(tmp)
        self.assertEqual(config["require_tests"], "warn")
        self.assertEqual(config["exclude"], [])
        self.assertFalse(config["fail_on_review"])

    def test_valid_file_is_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / CONFIG_FILENAME).write_text(
                json.dumps({"require_tests": "fail", "exclude": ["vendor/*"]}), encoding="utf-8"
            )
            config = load_config(tmp)
        self.assertEqual(config["require_tests"], "fail")
        self.assertEqual(config["exclude"], ["vendor/*"])
        self.assertEqual(config["min_test_trigger_lines"], 5)

    def test_unknown_key_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / CONFIG_FILENAME).write_text(json.dumps({"reqire_tests": "warn"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(tmp)

    def test_bad_enum_and_bad_json_fail_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / CONFIG_FILENAME
            path.write_text(json.dumps({"require_tests": "maybe"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(tmp)
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(tmp)

    def test_this_repository_config_is_valid(self):
        config = load_config(PROJECT_ROOT)
        self.assertIn("business_logic", config)
        self.assertTrue(config["business_logic"]["critical_paths"])


class TestTestPresencePolicy(unittest.TestCase):
    """C-03: production logic changes must be accompanied by test changes."""

    @staticmethod
    def _prod_diff(lines=6):
        body = [f"    step_{i}()" for i in range(lines - 1)]
        added = ["def pipeline():", *body]
        header = (
            "diff --git a/svc/pipeline.py b/svc/pipeline.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/svc/pipeline.py\n"
            f"@@ -0,0 +1,{len(added)} @@\n"
        )
        return header + "".join(f"+{line}\n" for line in added)

    @staticmethod
    def _test_diff():
        return (
            "diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/tests/test_pipeline.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+def test_pipeline():\n"
            "+    assert pipeline() is None\n"
        )

    def test_warn_mode_flags_untested_logic(self):
        review = engine.review_patch(self._prod_diff(), require_tests="warn")
        self.assertEqual(review["verdict"], "REVIEW")
        findings = review["files"][0]["findings"]
        self.assertTrue(any(f["class"] == engine.CLASS_TESTING for f in findings))
        self.assertIn("constitution-policy", review["engines"])

    def test_fail_mode_gates_untested_logic(self):
        review = engine.review_patch(self._prod_diff(), require_tests="fail")
        self.assertEqual(review["verdict"], "FAIL")

    def test_touching_tests_satisfies_the_policy(self):
        review = engine.review_patch(self._prod_diff() + self._test_diff(), require_tests="warn")
        classes = [f["class"] for report in review["files"] for f in report["findings"]]
        self.assertNotIn(engine.CLASS_TESTING, classes)
        self.assertEqual(review["verdict"], "PASS")

    def test_below_threshold_changes_are_not_flagged(self):
        review = engine.review_patch(self._prod_diff(lines=3), require_tests="warn")
        self.assertEqual(review["verdict"], "PASS")

    def test_custom_test_globs_are_recognised(self):
        qa_diff = (
            "diff --git a/qa/pipeline_check.py b/qa/pipeline_check.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/qa/pipeline_check.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+CHECKS = ['pipeline']\n"
        )
        review = engine.review_patch(self._prod_diff() + qa_diff, require_tests="warn", test_globs=["qa/*"])
        self.assertEqual(review["verdict"], "PASS")

    def test_is_test_path_conventions(self):
        for path in (
            "tests/test_x.py",
            "src/module/test_thing.py",
            "pkg/handler_test.go",
            "web/src/App.test.tsx",
            "src/test/java/AppTest.java",
            "spec/models/user_spec.rb",
        ):
            self.assertTrue(engine.is_test_path(path), path)
        for path in ("svc/pipeline.py", "src/testing_utils_prod.py", "contest.py"):
            self.assertFalse(engine.is_test_path(path), path)


class TestStagedGate(unittest.TestCase):
    """Factor 1a: the index, not the worktree, is what gets judged."""

    def test_staged_stub_fails_and_clean_worktree_does_not_mask_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            target = repo / "svc"
            target.mkdir()
            (target / "handler.py").write_text(STUB_SOURCE, encoding="utf-8")
            git(repo, "add", "svc/handler.py")
            code, stdout = run_cli(["--staged", "--root", str(repo), "--json"])
            self.assertEqual(code, cli.EXIT_GATE_FAILED)
            self.assertEqual(json.loads(stdout)["verdict"], "FAIL")

            # Fix the worktree WITHOUT re-staging: the index still holds the
            # stub, so the gate must still fail. This is the property that
            # makes the staged gate trustworthy.
            (target / "handler.py").write_text(CLEAN_SOURCE, encoding="utf-8")
            code, stdout = run_cli(["--staged", "--root", str(repo), "--json"])
            self.assertEqual(code, cli.EXIT_GATE_FAILED, "worktree state masked the staged stub")
            review = json.loads(stdout)
            self.assertEqual(review["files"][0]["mode"], "full")

    def test_clean_staged_change_with_tests_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            (repo / "svc").mkdir()
            (repo / "svc" / "calc.py").write_text(CLEAN_SOURCE, encoding="utf-8")
            (repo / "tests").mkdir()
            (repo / "tests" / "test_calc.py").write_text(CLEAN_TEST_SOURCE, encoding="utf-8")
            git(repo, "add", ".")
            code, stdout = run_cli(["--staged", "--root", str(repo), "--json"])
            self.assertEqual(code, cli.EXIT_OK)
            self.assertEqual(json.loads(stdout)["verdict"], "PASS")

    def test_staged_untested_logic_warns_under_default_policy(self):
        untested = (
            "def convert(amount, rate):\n"
            "    if rate <= 0:\n"
            "        raise ValueError('rate must be positive')\n"
            "    gross = amount * rate\n"
            "    net = round(gross, 2)\n"
            "    return net\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            (repo / "svc").mkdir()
            (repo / "svc" / "calc.py").write_text(untested, encoding="utf-8")
            git(repo, "add", ".")
            code, stdout = run_cli(["--staged", "--root", str(repo), "--json"])
            self.assertEqual(code, cli.EXIT_OK)  # warning, not gate failure
            review = json.loads(stdout)
            self.assertEqual(review["verdict"], "REVIEW")
            classes = [f["class"] for report in review["files"] for f in report["findings"]]
            self.assertIn(engine.CLASS_TESTING, classes)


class TestHookInstallerAndCommitBlocking(unittest.TestCase):
    def test_install_refuses_foreign_hook_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            hooks = repo / ".git" / "hooks"
            hooks.mkdir(exist_ok=True)
            foreign = hooks / "pre-commit"
            foreign.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            code, _ = run_cli(["--install-hook", "--root", str(repo)])
            self.assertEqual(code, cli.EXIT_OPERATIONAL_ERROR)
            code, _ = run_cli(["--install-hook", "--root", str(repo), "--force"])
            self.assertEqual(code, cli.EXIT_OK)
            content = foreign.read_text(encoding="utf-8")
            self.assertIn("persona-pr-review pre-commit gate", content)
            if os.name == "posix":
                # Execute bits are a POSIX concept; NTFS has none and
                # os.chmod on Windows only toggles the read-only flag.
                # Git for Windows runs hooks through sh regardless, so the
                # executable requirement is real only where the bit exists.
                self.assertTrue(foreign.stat().st_mode & stat.S_IXUSR)

    def test_installed_hook_blocks_a_real_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            code, _ = run_cli(["--install-hook", "--root", str(repo)])
            self.assertEqual(code, cli.EXIT_OK)

            # The installer bakes the installing interpreter into the hook as
            # a fallback, so the gate must work even though this test env has
            # no `persona-pr-review` on PATH and no PYTHONPATH.
            hook_text = (repo / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
            self.assertIn(sys.executable, hook_text)
            env = {
                key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "VIRTUAL_ENV")
            }
            env.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})

            (repo / "bad.py").write_text(STUB_SOURCE, encoding="utf-8")
            subprocess.run(["git", "add", "bad.py"], cwd=repo, check=True, capture_output=True)
            blocked = subprocess.run(
                ["git", "commit", "-m", "should be blocked"],
                cwd=repo,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertNotEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)

            # Replace with clean code plus tests: the same hook must let it through.
            subprocess.run(
                ["git", "rm", "-q", "--cached", "bad.py"], cwd=repo, check=True, capture_output=True
            )
            (repo / "bad.py").unlink()
            (repo / "svc").mkdir()
            (repo / "svc" / "calc.py").write_text(CLEAN_SOURCE, encoding="utf-8")
            (repo / "tests").mkdir()
            (repo / "tests" / "test_calc.py").write_text(CLEAN_TEST_SOURCE, encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            allowed = subprocess.run(
                ["git", "commit", "-m", "clean with tests"],
                cwd=repo,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)


class TestFactorParity(unittest.TestCase):
    """The PR-side gate must reach the same verdict as the staged gate."""

    def test_pr_gate_agrees_with_staged_gate_on_the_same_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            (repo / "svc").mkdir()
            (repo / "svc" / "handler.py").write_text(STUB_SOURCE, encoding="utf-8")
            git(repo, "add", ".")
            staged_code, staged_out = run_cli(["--staged", "--root", str(repo), "--json"])
            git(repo, "commit", "-qm", "stub landed anyway (bypassed hook)")

            pr_code, pr_out = run_cli(["--git", "HEAD~1...HEAD", "--root", str(repo), "--json"])
            self.assertEqual(staged_code, cli.EXIT_GATE_FAILED)
            self.assertEqual(pr_code, cli.EXIT_GATE_FAILED)
            staged_review, pr_review = json.loads(staged_out), json.loads(pr_out)
            self.assertEqual(staged_review["verdict"], pr_review["verdict"])
            staged_findings = {
                (f["class"], f["finding"]) for report in staged_review["files"] for f in report["findings"]
            }
            pr_findings = {
                (f["class"], f["finding"]) for report in pr_review["files"] for f in report["findings"]
            }
            self.assertEqual(staged_findings, pr_findings)


if __name__ == "__main__":
    unittest.main()
