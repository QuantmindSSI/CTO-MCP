"""persona-pr-review: command-line front end for the two-factor review gate.

Factor 1a runs at staging time (pre-commit hook), factor 1b at PR time - the
same deterministic engine at both moments. Input modes:

  --staged               review `git diff --cached`; file contents come from
                         the INDEX (`git show :0:path`), not the worktree, so
                         what is judged is exactly what would be committed
  --diff PATH|-          review an existing unified diff (file or stdin);
                         file contents resolved from --root for full fidelity
  --git RANGE            run `git diff RANGE` in --root (use base...head for
                         PR semantics) and review the result
  --github OWNER/REPO#N  fetch the PR diff and head file contents from the
                         GitHub API (token from GITHUB_TOKEN or GH_TOKEN)
  --install-hook         install the pre-commit gate into .git/hooks

Policy comes from .persona-review.json in --root (exclusions, C-03
require_tests, project test globs, business-logic hints for the agent);
command-line flags override the file.

Output selectors: --json (machine), --annotate (GitHub Actions workflow
commands), default human text. --post additionally submits the review to the
PR (github mode only): REQUEST_CHANGES on FAIL, COMMENT otherwise, never
APPROVE.

Exit codes: 0 verdict PASS (or REVIEW without fail-on-review),
1 verdict FAIL (or REVIEW with fail-on-review), 2 usage error (argparse),
3 operational error (git/API/filesystem/config failure).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from .config import REQUIRE_TESTS_MODES, load_config
    from .engine import MAX_FILE_BYTES, language_for_path, review_patch
    from .github_client import GitHubClient, GitHubError
    from .report import to_annotations, to_github_review, to_text
except ImportError:  # pragma: no cover - direct script execution
    from persona_constitution.review.config import REQUIRE_TESTS_MODES, load_config
    from persona_constitution.review.engine import MAX_FILE_BYTES, language_for_path, review_patch
    from persona_constitution.review.github_client import GitHubClient, GitHubError
    from persona_constitution.review.report import to_annotations, to_github_review, to_text

_PR_SPEC_RE = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_OPERATIONAL_ERROR = 3


def _add_source_arguments(parser):
    """The mutually exclusive input modes."""
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--diff", metavar="PATH", help="unified diff file, or '-' for stdin")
    source.add_argument("--git", metavar="RANGE", help="git diff RANGE (e.g. origin/main...HEAD)")
    source.add_argument("--github", metavar="OWNER/REPO#N", help="review a GitHub pull request")
    source.add_argument(
        "--staged", action="store_true", help="review staged changes (contents read from the index)"
    )
    source.add_argument(
        "--install-hook",
        action="store_true",
        help="install the pre-commit staged gate into this repository's hooks",
    )


def _add_policy_and_output_arguments(parser):
    """Policy overrides and output selectors."""
    parser.add_argument(
        "--root",
        default=".",
        metavar="DIR",
        help="working tree used to resolve full file contents (default: cwd)",
    )
    parser.add_argument("--json", action="store_true", help="emit the full review as JSON")
    parser.add_argument(
        "--annotate", action="store_true", help="emit GitHub Actions error/warning annotations"
    )
    parser.add_argument("--post", action="store_true", help="post the review to the PR (--github mode only)")
    parser.add_argument("--fail-on-review", action="store_true", help="exit 1 when the verdict is REVIEW")
    parser.add_argument(
        "--max-comments", type=int, default=50, help="inline comment budget for --post (default 50)"
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help=(
            "path glob this gate must not judge (repeatable, appended to the config file's "
            "excludes); use for detector rule definitions and fixture corpora"
        ),
    )
    parser.add_argument(
        "--require-tests",
        choices=REQUIRE_TESTS_MODES,
        default=None,
        help="C-03 enforcement: off, warn, or fail (default: .persona-review.json, else warn)",
    )
    parser.add_argument(
        "--force", action="store_true", help="with --install-hook: overwrite a foreign pre-commit hook"
    )


def build_parser():
    """Construct the argument parser (kept separate for testability)."""
    parser = argparse.ArgumentParser(
        prog="persona-pr-review",
        description="Deterministic Zero-Framework-Tolerance gate for staged changes and pull requests.",
    )
    _add_source_arguments(parser)
    _add_policy_and_output_arguments(parser)
    return parser


def _read_diff_argument(diff_argument):
    """Load diff text from a file path or stdin ('-')."""
    if diff_argument == "-":
        return sys.stdin.read()
    return Path(diff_argument).read_text(encoding="utf-8", errors="replace")


def _run_git_diff(range_expression, root):
    """Produce diff text via git; raises RuntimeError with stderr on failure."""
    return _git_output(["diff", "--no-color", "--find-renames", range_expression], root)


def _contents_from_worktree(diff_text, root):
    """Resolve full new-version contents for changed code files from disk."""
    from .diff import parse_unified_diff  # local import avoids cycle at module load

    contents = {}
    root_path = Path(root)
    for file_diff in parse_unified_diff(diff_text):
        if file_diff.status == "deleted" or file_diff.is_binary:
            continue
        if language_for_path(file_diff.path) is None:
            continue
        candidate = root_path / file_diff.path
        if not candidate.is_file():
            continue
        if candidate.stat().st_size > MAX_FILE_BYTES:
            continue
        contents[file_diff.path] = candidate.read_text(encoding="utf-8", errors="replace")
    return contents


def _git_output(arguments, root, timeout=120):
    """Run one git command; raises RuntimeError with stderr on failure."""
    completed = subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, text=True, timeout=timeout, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(f"`git {' '.join(arguments)}` failed: {completed.stderr.strip()}")
    return completed.stdout


def _contents_from_index(diff_text, root):
    """Resolve staged (index) contents for changed code files.

    `git show :0:path` reads stage 0 of the index - exactly the bytes that
    would be committed, which may differ from the worktree. A path that fails
    to resolve (e.g. intent-to-add of an unreadable file) is scanned in hunk
    mode rather than aborting the gate.
    """
    from .diff import parse_unified_diff  # local import avoids cycle at module load

    contents = {}
    for file_diff in parse_unified_diff(diff_text):
        if file_diff.status == "deleted" or file_diff.is_binary:
            continue
        if language_for_path(file_diff.path) is None:
            continue
        try:
            text = _git_output(["show", f":0:{file_diff.path}"], root)
        except RuntimeError:
            continue
        if len(text.encode("utf-8", errors="replace")) <= MAX_FILE_BYTES:
            contents[file_diff.path] = text
    return contents


_HOOK_MARKER = "# persona-pr-review pre-commit gate"

_HOOK_TEMPLATE = f"""#!/bin/sh
{_HOOK_MARKER}
# Factor 1 of the two-factor review: staged changes are scanned before every
# commit with the same engine that reviews pull requests. Policy comes from
# .persona-review.json. Bypass once with `git commit --no-verify` - the PR
# gate (factor 1b) and the agent review (factor 2) still stand.
if command -v persona-pr-review >/dev/null 2>&1; then
    exec persona-pr-review --staged
fi
# PATH does not carry the console script (e.g. the virtualenv is not
# activated in this shell); fall back to the interpreter that installed
# this hook, recorded at install time.
if [ -x "{{python}}" ]; then
    exec "{{python}}" -m persona_constitution.review.cli --staged
fi
echo "persona-pr-review: not on PATH and the recorded interpreter is gone;" >&2
echo "failing closed. Reinstall with --install-hook. Bypass once: git commit --no-verify" >&2
exit 1
"""


def _install_hook(root, force):
    """Install the pre-commit staged gate; returns the hook path.

    Refuses to overwrite a hook this tool did not write unless force is set -
    silently clobbering a team's existing hook would be its own violation.
    The current interpreter's path is baked in as a fallback so the gate
    works even in shells where the virtualenv is not on PATH.
    """
    hooks_dir = Path(_git_output(["rev-parse", "--git-path", "hooks"], root).strip())
    if not hooks_dir.is_absolute():
        hooks_dir = Path(root) / hooks_dir
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "pre-commit"
    is_foreign = hook_path.exists() and _HOOK_MARKER not in hook_path.read_text(
        encoding="utf-8", errors="replace"
    )
    if is_foreign and not force:
        raise RuntimeError(
            f"{hook_path} exists and was not installed by persona-pr-review; "
            "chain it manually or rerun with --force to overwrite"
        )
    hook_path.write_text(_HOOK_TEMPLATE.format(python=sys.executable), encoding="utf-8")
    hook_path.chmod(0o755)
    return hook_path


def _github_token():
    """Token from the conventional environment variables."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


def _resolve_policy(arguments):
    """Merge .persona-review.json with command-line overrides.

    Returns (engine_kwargs, fail_on_review). Raises ValueError on a malformed
    config file - a broken policy stops the gate rather than weakening it.
    """
    config = load_config(arguments.root)
    engine_kwargs = {
        "exclude": config["exclude"] + arguments.exclude,
        "require_tests": arguments.require_tests or config["require_tests"],
        "test_globs": config["test_globs"],
        "min_test_trigger_lines": config["min_test_trigger_lines"],
    }
    return engine_kwargs, (arguments.fail_on_review or config["fail_on_review"])


def _review_github_pr(spec, post, max_comments, engine_kwargs):
    """Fetch, review, and optionally post. Returns (review, posted: bool)."""
    match = _PR_SPEC_RE.match(spec)
    if match is None:
        raise RuntimeError(f"--github expects OWNER/REPO#NUMBER, got {spec!r}")
    owner, repo, number = match.group(1), match.group(2), int(match.group(3))

    token = _github_token()
    if not token:
        raise RuntimeError("GITHUB_TOKEN (or GH_TOKEN) is required for --github mode")
    client = GitHubClient(token)

    pull_request = client.get_pull_request(owner, repo, number)
    head_sha = pull_request["head"]["sha"]
    diff_text = client.get_pull_request_diff(owner, repo, number)

    from .diff import parse_unified_diff  # local import avoids cycle at module load

    contents = {}
    for file_diff in parse_unified_diff(diff_text):
        if file_diff.status == "deleted" or file_diff.is_binary:
            continue
        if language_for_path(file_diff.path) is None:
            continue
        text = client.get_file_content(owner, repo, file_diff.path, head_sha)
        if text is not None:
            contents[file_diff.path] = text

    review = review_patch(diff_text, file_contents=contents, **engine_kwargs)

    posted = False
    if post:
        payload = to_github_review(review, head_sha, max_comments=max_comments)
        client.post_review(owner, repo, number, payload)
        posted = True
    return review, posted


def _emit(review, arguments, posted):
    """Write the selected output format(s) to stdout."""
    if arguments.json:
        print(json.dumps(review, indent=2))
    elif arguments.annotate:
        for command in to_annotations(review):
            print(command)
    else:
        print(to_text(review))
    if posted:
        print("review posted to GitHub", file=sys.stderr)


def _local_review(arguments, engine_kwargs):
    """Run the diff/git/staged modes against local state."""
    if arguments.post:
        raise RuntimeError("--post requires --github mode")
    if arguments.staged:
        diff_text = _git_output(["diff", "--cached", "--no-color", "--find-renames"], arguments.root)
        contents = _contents_from_index(diff_text, arguments.root)
    elif arguments.diff:
        diff_text = _read_diff_argument(arguments.diff)
        contents = _contents_from_worktree(diff_text, arguments.root)
    else:
        diff_text = _run_git_diff(arguments.git, arguments.root)
        contents = _contents_from_worktree(diff_text, arguments.root)
    return review_patch(diff_text, file_contents=contents, **engine_kwargs)


def main(argv=None):
    """Entry point. Returns the process exit code."""
    arguments = build_parser().parse_args(argv)
    posted = False
    try:
        if arguments.install_hook:
            hook_path = _install_hook(arguments.root, arguments.force)
            print(f"pre-commit gate installed: {hook_path}")
            return EXIT_OK
        engine_kwargs, fail_on_review = _resolve_policy(arguments)
        if arguments.github:
            review, posted = _review_github_pr(
                arguments.github, arguments.post, arguments.max_comments, engine_kwargs
            )
        else:
            review = _local_review(arguments, engine_kwargs)
    except (GitHubError, RuntimeError, OSError, ValueError) as error:
        print(f"persona-pr-review: {error}", file=sys.stderr)
        return EXIT_OPERATIONAL_ERROR

    _emit(review, arguments, posted)

    if review["verdict"] == "FAIL":
        return EXIT_GATE_FAILED
    if review["verdict"] == "REVIEW" and fail_on_review:
        return EXIT_GATE_FAILED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
