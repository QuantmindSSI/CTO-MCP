"""Unified diff parsing for the PR review engine.

Parses `git diff` / GitHub PR patch text into per-file structures that map
every added line to its line number in the NEW version of the file - the
coordinate system GitHub review comments and Actions annotations use.

Stdlib only. The parser is deliberately forgiving about content lines (a
malformed line inside a hunk terminates that hunk rather than aborting the
whole parse) but strict about resource bounds: input larger than
MAX_DIFF_BYTES is rejected up front.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from re import Match

# A PR diff larger than this is not reviewable line-by-line in any meaningful
# sense; the caller should review the PR's scope instead. 10 MB of diff text.
MAX_DIFF_BYTES = 10 * 1024 * 1024

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

STATUS_ADDED = "added"
STATUS_MODIFIED = "modified"
STATUS_DELETED = "deleted"
STATUS_RENAMED = "renamed"


@dataclass
class FileDiff:
    """One file's change within a unified diff.

    Attributes:
        path: Path of the NEW version (rename target for renames). For
            deletions this is the old path, so reports can still name the file.
        old_path: Path of the old version.
        status: One of the STATUS_* constants.
        is_binary: True when the diff declares binary content; such files
            carry no line information.
        added_lines: Mapping of new-file line number -> line text (without
            the leading '+').
    """

    path: str
    old_path: str
    status: str = STATUS_MODIFIED
    is_binary: bool = False
    added_lines: dict[int, str] = field(default_factory=dict)


_ESCAPE_BYTES: dict[str, int] = {
    "\\": 0x5C,
    '"': 0x22,
    "n": 0x0A,
    "t": 0x09,
    "r": 0x0D,
    "a": 0x07,
    "b": 0x08,
    "f": 0x0C,
    "v": 0x0B,
}


def _unquote_git_path(path: str) -> str:
    """Decode a git-quoted path: surrounding quotes, C escapes, \\NNN octal.

    Git quotes paths containing non-ASCII or special bytes (core.quotePath
    default) and encodes those bytes as three-digit octal escapes; the decoded
    byte sequence is UTF-8. Unquoted paths pass through untouched.
    """
    if not (path.startswith('"') and path.endswith('"') and len(path) >= 2):
        return path
    inner = path[1:-1]
    decoded = bytearray()
    index = 0
    while index < len(inner):
        char = inner[index]
        if char != "\\":
            decoded.extend(char.encode("utf-8"))
            index += 1
            continue
        index += 1
        if index >= len(inner):
            break
        escape = inner[index]
        if escape in _ESCAPE_BYTES:
            decoded.append(_ESCAPE_BYTES[escape])
            index += 1
        elif escape.isdigit():
            octal = inner[index : index + 3]
            decoded.append(int(octal, 8) & 0xFF)
            index += len(octal)
        else:
            decoded.extend(escape.encode("utf-8"))
            index += 1
    return decoded.decode("utf-8", errors="replace")


def _strip_prefix(path: str) -> str:
    """Strip the a/ or b/ prefix git puts on diff paths, and unquote."""
    path = _unquote_git_path(path)
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _split_git_header(line: str) -> tuple[str | None, str | None]:
    """Extract (old_path, new_path) from a `diff --git a/x b/y` line.

    Paths containing " b/" are ambiguous in this header; the authoritative
    `+++ b/...` line overrides this value later when present.
    """
    body = line[len("diff --git ") :]
    marker = body.find(" b/")
    if marker == -1:
        parts = body.split()
        if len(parts) >= 2:
            return _strip_prefix(parts[0]), _strip_prefix(parts[-1])
        return None, None
    return _strip_prefix(body[:marker]), _strip_prefix(body[marker + 1 :])


class _FileBuilder:
    """Accumulates header and hunk state for one file section."""

    def __init__(self, old_path: str | None, new_path: str | None) -> None:
        self.old_path = old_path
        self.new_path = new_path
        self.is_binary = False
        self.is_new = False
        self.is_deleted = False
        self.is_renamed = False
        self.added_lines: dict[int, str] = {}
        self._new_line = 0
        self._old_remaining = 0
        self._new_remaining = 0

    def _flag_header(self, line: str) -> bool:
        """Consume a status-flag header line. Returns True when it matched."""
        if line.startswith("new file mode"):
            self.is_new = True
        elif line.startswith("deleted file mode"):
            self.is_deleted = True
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            self.is_binary = True
        else:
            return False
        return True

    def header(self, line: str) -> None:
        """Consume one extended-header line."""
        if self._flag_header(line):
            return
        if line.startswith("rename from "):
            self.is_renamed = True
            self.old_path = _strip_prefix(line[len("rename from ") :])
        elif line.startswith("rename to "):
            self.is_renamed = True
            self.new_path = _strip_prefix(line[len("rename to ") :])
        elif line.startswith("--- ") and line[4:] != "/dev/null":
            self.old_path = _strip_prefix(line[4:].split("\t")[0])
        elif line.startswith("+++ ") and line[4:] != "/dev/null":
            self.new_path = _strip_prefix(line[4:].split("\t")[0])

    @property
    def in_hunk(self) -> bool:
        """True while either side of the current hunk has budget left."""
        return self._old_remaining > 0 or self._new_remaining > 0

    def start_hunk(self, match: Match[str]) -> None:
        """Arm the line budgets from an @@ header match."""
        self._new_line = int(match.group(3))
        self._old_remaining = int(match.group(2)) if match.group(2) is not None else 1
        self._new_remaining = int(match.group(4)) if match.group(4) is not None else 1

    def consume(self, raw: str) -> None:
        """Consume one content line inside a hunk.

        A hunk ends exactly when both sides' declared line budgets are
        consumed, so trailing '-' lines can never be mistaken for '---' file
        headers. "\\ No newline at end of file" advances neither side; a
        completely empty line is tolerated as empty context.
        """
        if raw.startswith("+"):
            self.added_lines[self._new_line] = raw[1:]
            self._new_line += 1
            self._new_remaining -= 1
        elif raw.startswith("-"):
            self._old_remaining -= 1
        elif not raw.startswith("\\"):
            self._new_line += 1
            self._old_remaining -= 1
            self._new_remaining -= 1

    def build(self) -> FileDiff:
        """Produce the immutable FileDiff."""
        if self.is_deleted:
            status = STATUS_DELETED
        elif self.is_new:
            status = STATUS_ADDED
        elif self.is_renamed:
            status = STATUS_RENAMED
        else:
            status = STATUS_MODIFIED
        path = self.old_path if self.is_deleted else (self.new_path or self.old_path)
        return FileDiff(
            path=path or "",
            old_path=self.old_path or "",
            status=status,
            is_binary=self.is_binary,
            added_lines=self.added_lines,
        )


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """Parse unified diff text into FileDiff records.

    Args:
        diff_text: Output of `git diff`, `gh pr diff`, or the GitHub
            `application/vnd.github.v3.diff` media type. Must be a str no
            larger than MAX_DIFF_BYTES when UTF-8 encoded.

    Returns:
        List of FileDiff in encounter order. Unrecognisable leading garbage
        (mail headers, commit messages) is skipped.

    Raises:
        ValueError: When the input exceeds MAX_DIFF_BYTES.

    Complexity: O(N) over input lines.
    """
    assert isinstance(diff_text, str), "diff_text must be a string"
    if len(diff_text.encode("utf-8", errors="replace")) > MAX_DIFF_BYTES:
        raise ValueError(f"diff exceeds MAX_DIFF_BYTES ({MAX_DIFF_BYTES} bytes); review scope instead")

    files: list[FileDiff] = []
    builder: _FileBuilder | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            if builder is not None:
                files.append(builder.build())
            old_path, new_path = _split_git_header(raw)
            builder = _FileBuilder(old_path, new_path)
            continue
        if builder is None:
            continue
        hunk = _HUNK_RE.match(raw)
        if hunk is not None:
            builder.start_hunk(hunk)
        elif builder.in_hunk:
            builder.consume(raw)
        else:
            builder.header(raw)

    if builder is not None:
        files.append(builder.build())
    return files
