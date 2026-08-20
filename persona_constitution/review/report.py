"""Renderers for review results: human text, GitHub Actions annotations, and
GitHub pull-request review payloads.

All three consume the dict produced by engine.review_patch and are pure
functions of it - no I/O, no network. The GitHub payload builder enforces the
platform's practical limits (bounded inline comments) and never emits an
APPROVE event: a deterministic scanner can prove absence of markers, not
presence of correctness, so approval authority stays with humans and the
agent layer's judgement.
"""

from __future__ import annotations

from typing import Any

# GitHub rejects review payloads with excessive comment counts and truncates
# noisy reviews into uselessness; cap and summarise the overflow instead.
MAX_INLINE_COMMENTS = 50

_SEVERITY_TO_ANNOTATION = {"violation": "error", "warning": "warning"}


def _escape_annotation_message(text: str) -> str:
    """Escape message text per the Actions workflow-command grammar."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_annotation_property(text: str) -> str:
    """Escape property values (file, title) per the Actions grammar."""
    return _escape_annotation_message(text).replace(":", "%3A").replace(",", "%2C")


def to_annotations(review: dict[str, Any]) -> list[str]:
    """Render a review as GitHub Actions workflow commands, one per finding.

    Returns a list of `::error`/`::warning` command strings with file and
    line coordinates, followed by a `::notice` carrying the overall verdict.
    """
    commands: list[str] = []
    for file_report in review["files"]:
        for finding in file_report["findings"]:
            level = _SEVERITY_TO_ANNOTATION[finding["severity"]]
            commands.append(
                f"::{level} file={_escape_annotation_property(file_report['path'])},"
                f"line={finding['line']},"
                f"title={_escape_annotation_property(finding['class'])}::"
                f"{_escape_annotation_message(finding['finding'] + ' [' + finding['source'] + ']')}"
            )
    commands.append(
        f"::notice title=persona-pr-review::verdict={review['verdict']} "
        f"{_escape_annotation_message(review['summary'])}"
    )
    return commands


def _comment_body(finding: dict[str, Any]) -> str:
    """One inline review comment for one finding."""
    severity = finding["severity"].upper()
    return (
        f"**{severity}** - {finding['class']}\n\n"
        f"{finding['finding']}\n\n"
        f"`engine: {finding['source']}` - Zero Framework Tolerance: a flagged "
        "line must be implemented completely, not patched around."
    )


def to_github_review(
    review: dict[str, Any], commit_sha: str, max_comments: int = MAX_INLINE_COMMENTS
) -> dict[str, Any]:
    """Build the payload for POST /repos/{owner}/{repo}/pulls/{n}/reviews.

    Args:
        review: engine.review_patch output.
        commit_sha: Head commit the review applies to (required by the API
            to anchor line comments reliably).
        max_comments: Inline comment budget; excess findings are summarised
            in the review body.

    Returns:
        dict payload: event is REQUEST_CHANGES for FAIL and COMMENT
        otherwise. Never APPROVE, by design.
    """
    assert commit_sha, "commit_sha is required to anchor review comments"
    comments: list[dict[str, Any]] = []
    overflow = 0
    for file_report in review["files"]:
        for finding in file_report["findings"]:
            if len(comments) < max_comments:
                comments.append(
                    {
                        "path": file_report["path"],
                        "line": finding["line"],
                        "side": "RIGHT",
                        "body": _comment_body(finding),
                    }
                )
            else:
                overflow += 1

    return {
        "commit_id": commit_sha,
        "event": "REQUEST_CHANGES" if review["verdict"] == "FAIL" else "COMMENT",
        "body": _review_body(review, overflow),
        "comments": comments,
    }


def _review_body(review: dict[str, Any], overflow: int) -> str:
    """The consolidated review body posted alongside inline comments."""
    totals = review["totals"]
    lines = [
        "## persona-pr-review - deterministic constitution gate",
        "",
        f"**Verdict: {review['verdict']}**",
        "",
        review["summary"],
        "",
        f"- Files reviewed: {totals['files_reviewed']} (skipped: {totals['files_skipped']})",
        f"- Violations on changed lines: {totals['violations']}",
        f"- Warnings on changed lines: {totals['warnings']}",
        f"- Engines: {', '.join(review['engines']) or 'none'}",
    ]
    if totals["pre_existing_violations"] or totals["pre_existing_warnings"]:
        lines.append(
            f"- Pre-existing debt in touched files (not gated): "
            f"{totals['pre_existing_violations']} violation(s), "
            f"{totals['pre_existing_warnings']} warning(s)"
        )
    if overflow:
        lines.append(f"- {overflow} further finding(s) exceeded the inline comment budget")
    lines += [
        "",
        "_A PASS from this gate is necessary but not sufficient: gates G1-G5_",
        "_(executability, completeness, correctness, dependency honesty, problem fit)_",
        "_still apply and are the reviewing agent's responsibility._",
    ]
    return "\n".join(lines)


def to_text(review: dict[str, Any]) -> str:
    """Plain-text report for terminals and logs."""
    lines = [f"verdict: {review['verdict']}", review["summary"], ""]
    for file_report in review["files"]:
        if file_report["mode"].startswith("skipped-"):
            continue
        lines.append(f"{file_report['path']} [{file_report['mode']}] -> {file_report['verdict']}")
        for finding in file_report["findings"]:
            lines.append(
                f"  {file_report['path']}:{finding['line']} {finding['severity'].upper()} "
                f"{finding['class']}: {finding['finding']} ({finding['source']})"
            )
    totals = review["totals"]
    lines.append("")
    lines.append(
        f"files reviewed={totals['files_reviewed']} skipped={totals['files_skipped']} "
        f"violations={totals['violations']} warnings={totals['warnings']} "
        f"pre-existing={totals['pre_existing_violations']}v/{totals['pre_existing_warnings']}w"
    )
    return "\n".join(lines)
