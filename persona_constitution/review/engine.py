"""Diff-aware review engine: the deterministic core of the PR reviewer.

For every code file changed in a diff, the full scanner union (CodebaseCSI +
constitution prose rules + Python AST + tree-sitter xast) runs over the file,
and findings are then attributed to the diff:

  * A finding on a line the PR added is ATTRIBUTED - it gates the verdict.
  * A finding elsewhere in a touched file is PRE-EXISTING - it is counted and
    surfaced, but a PR is never failed for debt it did not introduce.

Scanning modes per file, in order of fidelity:

  * "full"  - the complete new-version file content was supplied, so all
    engines (including AST tiers) see real context. Findings carry exact
    new-file line numbers.
  * "hunk"  - only the diff was supplied; the added lines are scanned as a
    fragment. Prose/marker rules remain reliable; AST tiers usually report
    inactive on fragments. Findings are mapped back to new-file line numbers
    through the fragment's line map.
  * "skipped-<reason>" - deleted, binary, oversized, or not a code file.

The verdict contract matches scan_code: any attributed violation -> FAIL,
otherwise any attributed warning -> REVIEW, otherwise PASS. This engine is
necessary but not sufficient: gates G1-G5 (executability, completeness,
correctness, dependency honesty, problem fit) still require judgement, which
is the agent layer's job, not this module's.

Security scanning is deliberately absent here: the vendored CodebaseCSI
SecurityAnalyzer was evaluated and failed to flag plain os.system injection
and hardcoded credentials, so it is not trusted to gate merges.
"""

from fnmatch import fnmatch
from pathlib import PurePosixPath

from codebase_csi.parsers.ast_parser import LANGUAGE_EXTENSIONS

try:
    from ..scanner import scan_code
    from .diff import STATUS_DELETED, parse_unified_diff
except ImportError:  # pragma: no cover - direct module execution
    from persona_constitution.review.diff import STATUS_DELETED, parse_unified_diff
    from persona_constitution.scanner import scan_code

# Bounds (Power of 10 rule 3: bound all resource growth).
MAX_FILES = 400
MAX_FILE_BYTES = 2_000_000

MODE_FULL = "full"
MODE_HUNK = "hunk"

CLASS_TESTING = "C-03 - Testing Discipline"

# Test-file conventions across the supported ecosystems. Matched against the
# full path AND the basename, so `test_*.py` finds tests at any depth while
# `tests/*` claims whole trees. Projects extend this via config `test_globs`.
DEFAULT_TEST_GLOBS = (
    "test/*",
    "tests/*",
    "testing/*",
    "spec/*",
    "specs/*",
    "__tests__/*",
    "src/test/*",
    "conftest.py",
    "test_*.py",
    "*_test.py",
    "*_test.go",
    "*Test.java",
    "*Tests.java",
    "*IT.java",
    "*.spec.ts",
    "*.spec.tsx",
    "*.spec.js",
    "*.spec.jsx",
    "*.test.ts",
    "*.test.tsx",
    "*.test.js",
    "*.test.jsx",
    "*_spec.rb",
    "*_test.rb",
    "*_test.c",
    "*_test.cc",
    "*_test.cpp",
)


def is_test_path(path, extra_globs=()):
    """True when a path belongs to any recognised test convention."""
    basename = PurePosixPath(path).name
    for pattern in tuple(DEFAULT_TEST_GLOBS) + tuple(extra_globs):
        if fnmatch(path, pattern) or fnmatch(basename, pattern):
            return True
    return False


def language_for_path(path):
    """Map a file path to a scanner language hint via its extension.

    Returns None for files this engine does not treat as reviewable code
    (docs, configs, lockfiles, unknown extensions).
    """
    suffix = PurePosixPath(path).suffix.lower()
    return LANGUAGE_EXTENSIONS.get(suffix)


def _attribute_findings(all_findings, added_lines):
    """Split scanner findings into (attributed, pre_existing) by added lines."""
    attributed = []
    pre_existing = {"violations": 0, "warnings": 0}
    for finding in all_findings:
        if finding["line"] in added_lines:
            attributed.append(finding)
        elif finding["severity"] == "violation":
            pre_existing["violations"] += 1
        else:
            pre_existing["warnings"] += 1
    return attributed, pre_existing


def _scan_fragment(file_diff, language):
    """Hunk-only scan: added lines as a fragment, mapped to new-file lines."""
    line_numbers = sorted(file_diff.added_lines)
    fragment = "\n".join(file_diff.added_lines[number] for number in line_numbers)
    result = scan_code(fragment, language=language)
    findings = []
    for finding in result["findings"]:
        fragment_line = finding["line"]
        if 1 <= fragment_line <= len(line_numbers):
            mapped = dict(finding)
            mapped["line"] = line_numbers[fragment_line - 1]
            findings.append(mapped)
    return findings, result["engines"]


def _skip(path, language, reason):
    """Record a file the engine did not scan, and why."""
    return {
        "path": path,
        "language": language,
        "mode": f"skipped-{reason}",
        "verdict": "PASS",
        "findings": [],
        "pre_existing": {"violations": 0, "warnings": 0},
    }


def _is_excluded(path, exclude):
    """True when the path matches any exclusion glob.

    fnmatch semantics: `*` crosses directory separators, so `tests/*`
    excludes the whole tests tree and `*_fixtures.py` matches at any depth.
    """
    return any(fnmatch(path, pattern) for pattern in exclude)


def _skip_reason(file_diff, language, exclude):
    """Why this file is outside the gate's jurisdiction, or None to scan it."""
    if exclude and _is_excluded(file_diff.path, exclude):
        return "excluded"
    if file_diff.status == STATUS_DELETED:
        return "deleted"
    if file_diff.is_binary:
        return "binary"
    if language is None:
        return "not-code"
    if not file_diff.added_lines:
        return "no-added-lines"
    return None


def _scan_file(file_diff, source, language):
    """Scan one file in full or hunk mode. Returns (findings, pre_existing, engines, mode)."""
    if source is not None:
        result = scan_code(source, language=language)
        findings, pre_existing = _attribute_findings(result["findings"], file_diff.added_lines)
        return findings, pre_existing, result["engines"], MODE_FULL
    findings, engines = _scan_fragment(file_diff, language)
    return findings, {"violations": 0, "warnings": 0}, engines, MODE_HUNK


def _review_file(file_diff, contents, exclude):
    """Review one FileDiff. Returns (file_report, engines_used)."""
    language = language_for_path(file_diff.path)
    reason = _skip_reason(file_diff, language, exclude)
    if reason is not None:
        return _skip(file_diff.path, language, reason), []

    source = contents.get(file_diff.path) if contents else None
    if source is not None and len(source.encode("utf-8", errors="replace")) > MAX_FILE_BYTES:
        return _skip(file_diff.path, language, "oversized"), []

    findings, pre_existing, engines, mode = _scan_file(file_diff, source, language)
    violations = sum(1 for item in findings if item["severity"] == "violation")
    if violations:
        verdict = "FAIL"
    elif findings:
        verdict = "REVIEW"
    else:
        verdict = "PASS"

    return {
        "path": file_diff.path,
        "language": language,
        "mode": mode,
        "verdict": verdict,
        "findings": findings,
        "pre_existing": pre_existing,
    }, engines


def _coverage_finding(file_diff, severity):
    """Build the C-03 finding for one uncovered production file."""
    first_added = min(file_diff.added_lines)
    return {
        "line": first_added,
        "class": CLASS_TESTING,
        "finding": (
            f"{len(file_diff.added_lines)} line(s) of production logic changed with no "
            "accompanying test changes in this diff (C-03: non-trivial code ships with "
            "tests - unit, integration, e2e, or regression as appropriate)"
        ),
        "severity": severity,
        "source": "constitution-policy",
        "text": file_diff.added_lines[first_added].strip()[:200],
    }


def _escalate_verdict(report, severity):
    """Raise a file verdict to match a policy finding's severity."""
    if severity == "violation" and report["verdict"] != "FAIL":
        report["verdict"] = "FAIL"
    elif severity == "warning" and report["verdict"] == "PASS":
        report["verdict"] = "REVIEW"


def _flag_uncovered_report(report, diffs_by_path, globs, severity, min_lines):
    """Apply the C-03 finding to one file report when it qualifies."""
    if report["mode"].startswith("skipped-") or is_test_path(report["path"], globs):
        return
    file_diff = diffs_by_path.get(report["path"])
    if file_diff is None or len(file_diff.added_lines) < min_lines:
        return
    report["findings"].append(_coverage_finding(file_diff, severity))
    _escalate_verdict(report, severity)


def _coverage_policy_findings(reports, file_diffs, require_tests, test_globs, min_lines):
    """C-03 findings: production logic changed with no test changes anywhere.

    The deterministic contract is deliberately diff-global: if the change
    touches at least `min_lines` of production code in some file and touches
    zero test files, every such production file is flagged. Mapping WHICH
    tests cover WHICH changed behaviour is judgement work that belongs to the
    agent layer's business-logic research, not to a glob matcher.
    """
    assert require_tests in ("warn", "fail"), "caller filters 'off' before this point"
    globs = tuple(test_globs or ())
    tests_touched = any(
        is_test_path(file_diff.path, globs) and file_diff.added_lines for file_diff in file_diffs
    )
    if tests_touched:
        return
    severity = "warning" if require_tests == "warn" else "violation"
    diffs_by_path = {file_diff.path: file_diff for file_diff in file_diffs}
    for report in reports:
        _flag_uncovered_report(report, diffs_by_path, globs, severity, min_lines)


def _summary(verdict, totals):
    """Human-readable disposition mirroring scan_code's contract."""
    if verdict == "FAIL":
        return (
            f"{totals['violations']} violation(s) on lines this change introduces "
            f"across {totals['files_failed']} file(s). Per the Anti-Deception "
            "Enforcement Protocol the change must be regenerated complete: do not "
            "merge, do not patch the framework."
        )
    if verdict == "REVIEW":
        return (
            f"No violations, but {totals['warnings']} warning(s) on changed lines "
            "require judgement. Confirm each flagged line is genuinely complete, "
            "then run gates G1-G5."
        )
    return (
        "No placeholder, stub, scaffold, or deferral markers on any changed line. "
        "This gate is necessary but not sufficient: run gates G1-G5 "
        "(executability, completeness, correctness, dependency honesty, problem "
        "fit) before approving."
    )


def _aggregate(files):
    """Fold per-file reports into the totals dict."""
    totals = {
        "violations": 0,
        "warnings": 0,
        "files_reviewed": 0,
        "files_skipped": 0,
        "files_failed": 0,
        "pre_existing_violations": 0,
        "pre_existing_warnings": 0,
    }
    for report in files:
        if report["mode"].startswith("skipped-"):
            totals["files_skipped"] += 1
            continue
        totals["files_reviewed"] += 1
        totals["violations"] += sum(1 for f in report["findings"] if f["severity"] == "violation")
        totals["warnings"] += sum(1 for f in report["findings"] if f["severity"] == "warning")
        totals["pre_existing_violations"] += report["pre_existing"]["violations"]
        totals["pre_existing_warnings"] += report["pre_existing"]["warnings"]
        if report["verdict"] == "FAIL":
            totals["files_failed"] += 1
    return totals


def _review_files(file_diffs, file_contents, exclude):
    """Review every FileDiff. Returns (file reports, engines used)."""
    files = []
    engines_used = set()
    for file_diff in file_diffs:
        report, engines = _review_file(file_diff, file_contents, exclude)
        engines_used.update(engines)
        files.append(report)
    return files, engines_used


def review_patch(
    diff_text,
    file_contents=None,
    exclude=None,
    require_tests="off",
    test_globs=None,
    min_test_trigger_lines=5,
):
    """Review a unified diff against the Zero-Framework-Tolerance rules.

    Args:
        diff_text: Unified diff text (git diff / GitHub .diff media type), at
            most MAX_DIFF_BYTES.
        file_contents: Optional map of new-version path -> full file text;
            upgrades those files from "hunk" to "full" fidelity.
        exclude: Optional fnmatch globs the gate must not judge (rule
            definitions and fixture corpora contain hunted patterns as data).
        require_tests: C-03 enforcement - "off", "warn", or "fail" - flagging
            production-logic changes when the diff touches zero test files.
        test_globs: Project test path globs added to DEFAULT_TEST_GLOBS.
        min_test_trigger_lines: Added-line threshold per file before C-03
            applies (filters one-line fixes out of the policy).

    Returns:
        dict with keys: verdict, summary, files, totals, engines. Every
        finding carries line (new-file numbering), class, finding, severity,
        source, and text.

    Raises:
        ValueError: Oversized diff, or more than MAX_FILES changed files.

    Complexity: O(total diff size + sum of scanned file sizes).
    """
    assert isinstance(diff_text, str), "diff_text must be a string"
    assert file_contents is None or isinstance(file_contents, dict), "file_contents must be a dict"
    assert exclude is None or isinstance(exclude, list), "exclude must be a list of glob strings"
    assert require_tests in ("off", "warn", "fail"), "require_tests must be off|warn|fail"

    file_diffs = parse_unified_diff(diff_text)
    if len(file_diffs) > MAX_FILES:
        raise ValueError(f"{len(file_diffs)} changed files exceeds MAX_FILES ({MAX_FILES})")

    files, engines_used = _review_files(file_diffs, file_contents, exclude)
    if require_tests != "off":
        _coverage_policy_findings(files, file_diffs, require_tests, test_globs, min_test_trigger_lines)
        engines_used.add("constitution-policy")
    return _assemble_review(files, engines_used)


def _assemble_review(files, engines_used):
    """Fold file reports into the final review dict."""
    totals = _aggregate(files)
    verdict = _overall_verdict(totals)
    return {
        "verdict": verdict,
        "summary": _summary(verdict, totals),
        "files": files,
        "totals": totals,
        "engines": sorted(engines_used),
    }


def _overall_verdict(totals):
    """FAIL on any attributed violation, REVIEW on warnings, else PASS."""
    if totals["violations"] > 0:
        return "FAIL"
    if totals["warnings"] > 0:
        return "REVIEW"
    return "PASS"
