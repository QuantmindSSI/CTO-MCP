"""Diff-aware PR review: deterministic constitution gate over unified diffs.

Public surface:
    review_patch       - engine.review_patch: diff (+optional contents) -> review dict
    parse_unified_diff - diff.parse_unified_diff: diff text -> [FileDiff]
    to_annotations / to_github_review / to_text - report renderers
"""

from .diff import FileDiff, parse_unified_diff
from .engine import review_patch
from .report import to_annotations, to_github_review, to_text

__all__ = [
    "FileDiff",
    "parse_unified_diff",
    "review_patch",
    "to_annotations",
    "to_github_review",
    "to_text",
]
