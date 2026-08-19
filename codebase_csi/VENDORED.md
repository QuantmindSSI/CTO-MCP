# Vendored: CodebaseCSI

This directory is a vendored copy of the `codebase_csi` package.

- Upstream: https://github.com/Thundastormgod/CodebaseCSI
- Revision: `8aa23f7da15e567f23972a3da4731b53942490c7` (package version 1.1.0)
- Source path in upstream: `src/codebase_csi/`
- License: MIT (c) 2025 AI Code Detector Team - reproduced in this
  repository's top-level `LICENSE` file.

Local modifications relative to upstream are listed here. Keep this list
accurate: it is the merge ledger for any future upstream sync.

| File | Change | Reason |
|------|--------|--------|
| `parsers/ast_parser.py` | `TreeSitterParser.get_parser`: wrap the grammar's `language()` PyCapsule in `tree_sitter.Language`, broaden the except clause from `(ImportError, AttributeError)` to `Exception`, and cache load failures. | Upstream passes the raw capsule to `Parser()`, which raises `TypeError` on py-tree-sitter >= 0.22 and, because `TypeError` was uncaught, crashed the entire scan instead of degrading to the regex fallback. Verified against tree-sitter 0.23.2. |
| `analyzers/mock_detector.py` | `TODO_PATTERNS` `docstring_todo` regex rewritten with a tempered dot so a match cannot cross a triple-quote boundary. | The upstream greedy `.*` with `re.S` matched from a file's first docstring to its last triple-quote, so any Python file with two or more docstrings and a trigger word anywhere between them was flagged at line 1. |

Update procedure:
1. Clone upstream and check out the target revision.
2. `diff -r` upstream `src/codebase_csi` against this directory, excluding
   `__pycache__` and this file.
3. Re-apply every local modification in the table above, or retire it if
   upstream absorbed the fix.
4. Update the revision recorded above and run the full test suite and
   `tools/benchmark_scanner.py`.
