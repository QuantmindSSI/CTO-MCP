"""G4 - Dependency Honesty - made mechanical: hallucinated-package detection.

LLMs hallucinate package names, and attackers register those names
("slopsquatting"), so an import of a package that does not exist on its
registry is both an incompleteness defect and a supply-chain attack
surface. This module extracts external dependencies from source or from a
unified diff and verifies each against its public registry.

Classification runs cheapest-and-most-private first; the network is the
last resort and package names are the only data that ever leaves the
machine:

  1. excluded    - caller-supplied globs (private registries, internal names)
  2. stdlib      - Python standard library / Node built-ins
  3. first-party - modules the diff itself provides (diff mode only)
  4. registry    - PyPI (PEP 503 simple index) / npm registry existence

Network honesty: this is the only capability in the package that touches
the network besides the GitHub review client, and it never lies about it.
A registry 404 is "missing" (hallucinated or misspelled - the gate
fails). Timeouts, 5xx after bounded retries, and offline operation are
"unverifiable" (the gate demands review, never passes silently).
scan_code and review_patch remain fully offline; this tool is invoked
explicitly.

Import-name vs distribution-name: a small, curated alias table covers the
well-known mismatches (yaml -> PyYAML, cv2 -> opencv-python, ...). A name
that misses PyPI directly but resolves through the table is reported as
"exists-as" with the distribution named, so the caller can pin the right
requirement.
"""

from __future__ import annotations

import ast
import re
import sys
import time
import urllib.error
import urllib.request
from fnmatch import fnmatch
from typing import Any

try:
    from .review.diff import parse_unified_diff
    from .scanner import PARSER_REFUSALS
except ImportError:  # pragma: no cover - direct module execution
    from persona_constitution.review.diff import parse_unified_diff
    from persona_constitution.scanner import PARSER_REFUSALS

Report = dict[str, Any]

# ---------------------------------------------------------------------------
# Bounds (Power of 10 rule 3). The per-call package cap keeps this tool from
# being usable as a registry-scanning amplifier; the timeout and retry
# ceilings mirror review/github_client.py.
# ---------------------------------------------------------------------------
MAX_PACKAGES_PER_CALL = 50
REQUEST_TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.5
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

PYPI_SIMPLE_URL = "https://pypi.org/simple/{name}/"
NPM_REGISTRY_URL = "https://registry.npmjs.org/{name}"

STATUS_EXCLUDED = "excluded"
STATUS_STDLIB = "stdlib"
STATUS_BUILTIN = "builtin"
STATUS_FIRST_PARTY = "first-party"
STATUS_EXISTS = "exists"
STATUS_EXISTS_AS = "exists-as"
STATUS_MISSING = "missing"
STATUS_UNVERIFIABLE = "unverifiable"
STATUS_INVALID_NAME = "invalid-name"

# ---------------------------------------------------------------------------
# Python standard library, top-level names. sys.stdlib_module_names exists
# from 3.10; the frozen fallback below is its 3.12 value plus every module
# that shipped in 3.9 but was later removed (PEP 594 et al.). The union is
# used even when the runtime attribute exists, because the code under
# verification targets ITS interpreter, not ours: treating tomllib as
# stdlib on a 3.9 host is correct for the 3.11-targeting code importing it,
# and a hallucination named after a real stdlib module is impossible by
# definition. Generated, not hand-typed; regenerate with
#   python3.12 -c "import sys; print(sorted(sys.stdlib_module_names))"
# plus the removed-module addendum in the comment above each era.
# ---------------------------------------------------------------------------
_STDLIB_FALLBACK = frozenset(
    {
        "abc",
        "aifc",
        "antigravity",
        "argparse",
        "array",
        "ast",
        "asynchat",
        "asyncio",
        "asyncore",
        "atexit",
        "audioop",
        "base64",
        "bdb",
        "binascii",
        "binhex",
        "bisect",
        "builtins",
        "bz2",
        "cProfile",
        "calendar",
        "cgi",
        "cgitb",
        "chunk",
        "cmath",
        "cmd",
        "code",
        "codecs",
        "codeop",
        "collections",
        "colorsys",
        "compileall",
        "concurrent",
        "configparser",
        "contextlib",
        "contextvars",
        "copy",
        "copyreg",
        "crypt",
        "csv",
        "ctypes",
        "curses",
        "dataclasses",
        "datetime",
        "dbm",
        "decimal",
        "difflib",
        "dis",
        "distutils",
        "doctest",
        "email",
        "encodings",
        "ensurepip",
        "enum",
        "errno",
        "faulthandler",
        "fcntl",
        "filecmp",
        "fileinput",
        "fnmatch",
        "formatter",
        "fractions",
        "ftplib",
        "functools",
        "gc",
        "genericpath",
        "getopt",
        "getpass",
        "gettext",
        "glob",
        "graphlib",
        "grp",
        "gzip",
        "hashlib",
        "heapq",
        "hmac",
        "html",
        "http",
        "idlelib",
        "imaplib",
        "imghdr",
        "imp",
        "importlib",
        "inspect",
        "io",
        "ipaddress",
        "itertools",
        "json",
        "keyword",
        "lib2to3",
        "linecache",
        "locale",
        "logging",
        "lzma",
        "mailbox",
        "mailcap",
        "marshal",
        "math",
        "mimetypes",
        "mmap",
        "modulefinder",
        "msilib",
        "msvcrt",
        "multiprocessing",
        "netrc",
        "nis",
        "nntplib",
        "nt",
        "ntpath",
        "nturl2path",
        "numbers",
        "opcode",
        "operator",
        "optparse",
        "os",
        "ossaudiodev",
        "parser",
        "pathlib",
        "pdb",
        "pickle",
        "pickletools",
        "pipes",
        "pkgutil",
        "platform",
        "plistlib",
        "poplib",
        "posix",
        "posixpath",
        "pprint",
        "profile",
        "pstats",
        "pty",
        "pwd",
        "py_compile",
        "pyclbr",
        "pydoc",
        "pydoc_data",
        "pyexpat",
        "queue",
        "quopri",
        "random",
        "re",
        "readline",
        "reprlib",
        "resource",
        "rlcompleter",
        "runpy",
        "sched",
        "secrets",
        "select",
        "selectors",
        "shelve",
        "shlex",
        "shutil",
        "signal",
        "site",
        "smtpd",
        "smtplib",
        "sndhdr",
        "socket",
        "socketserver",
        "spwd",
        "sqlite3",
        "sre_compile",
        "sre_constants",
        "sre_parse",
        "ssl",
        "stat",
        "statistics",
        "string",
        "stringprep",
        "struct",
        "subprocess",
        "sunau",
        "symbol",
        "symtable",
        "sys",
        "sysconfig",
        "syslog",
        "tabnanny",
        "tarfile",
        "telnetlib",
        "tempfile",
        "termios",
        "textwrap",
        "this",
        "threading",
        "time",
        "timeit",
        "tkinter",
        "token",
        "tokenize",
        "tomllib",
        "trace",
        "traceback",
        "tracemalloc",
        "tty",
        "turtle",
        "turtledemo",
        "types",
        "typing",
        "unicodedata",
        "unittest",
        "urllib",
        "uu",
        "uuid",
        "venv",
        "warnings",
        "wave",
        "weakref",
        "webbrowser",
        "winreg",
        "winsound",
        "wsgiref",
        "xdrlib",
        "xml",
        "xmlrpc",
        "zipapp",
        "zipfile",
        "zipimport",
        "zlib",
        "zoneinfo",
    }
)

_PYTHON_STDLIB = frozenset(getattr(sys, "stdlib_module_names", frozenset())) | _STDLIB_FALLBACK

# Node.js built-in modules (bare and node:-prefixed forms both appear).
_NODE_BUILTINS = frozenset(
    {
        "assert",
        "async_hooks",
        "buffer",
        "child_process",
        "cluster",
        "console",
        "constants",
        "crypto",
        "dgram",
        "diagnostics_channel",
        "dns",
        "domain",
        "events",
        "fs",
        "http",
        "http2",
        "https",
        "inspector",
        "module",
        "net",
        "os",
        "path",
        "perf_hooks",
        "process",
        "punycode",
        "querystring",
        "readline",
        "repl",
        "stream",
        "string_decoder",
        "sys",
        "timers",
        "tls",
        "trace_events",
        "tty",
        "url",
        "util",
        "v8",
        "vm",
        "wasi",
        "worker_threads",
        "zlib",
    }
)

# Import name -> PyPI distribution name, for the well-known mismatches. Kept
# deliberately small and curated: every entry is a widely used package whose
# import name misses PyPI directly. A wrong alias would convert real
# hallucinations into false "exists-as" verdicts, so additions need the same
# evidence discipline as detector rules.
_PYPI_ALIASES = {
    "attr": "attrs",
    "bs4": "beautifulsoup4",
    "Crypto": "pycryptodome",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "fitz": "PyMuPDF",
    "git": "GitPython",
    "github": "PyGithub",
    "jwt": "PyJWT",
    "kafka": "kafka-python",
    "magic": "python-magic",
    "MySQLdb": "mysqlclient",
    "OpenSSL": "pyOpenSSL",
    "PIL": "Pillow",
    "pptx": "python-pptx",
    "serial": "pyserial",
    "sklearn": "scikit-learn",
    "usb": "pyusb",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "yaml": "PyYAML",
}

_PY_IMPORT_LINE_RE = re.compile(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import\b)")
_JS_IMPORT_RES = (
    re.compile(r"""\bimport\s+(?:[\w{}\s,*$]+\s+from\s+)?["']([^"']+)["']"""),
    re.compile(r"""\bexport\s+[\w{}\s,*$]+\s+from\s+["']([^"']+)["']"""),
    re.compile(r"""\b(?:require|import)\s*\(\s*["']([^"']+)["']\s*\)"""),
)
_NPM_NAME_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
_PY_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")


class RegistryUnavailable(RuntimeError):
    """The registry could not give a definitive answer (network/5xx/429)."""


def _request_status(url: str) -> int:
    """Status code for a GET of `url`, with bounded retries on transient
    failures. The response body is never read: existence is the question,
    the status line is the answer."""
    last_reason = "no attempts made"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(url, method="GET")
        request.add_header("User-Agent", "persona-constitution-verify-dependencies")
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return int(response.status)
        except urllib.error.HTTPError as error:
            if error.code in _RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                last_reason = f"HTTP {error.code}"
                time.sleep(BACKOFF_SECONDS * attempt)
                continue
            return int(error.code)
        except urllib.error.URLError as error:
            if attempt < MAX_ATTEMPTS:
                last_reason = str(error.reason)
                time.sleep(BACKOFF_SECONDS * attempt)
                continue
            raise RegistryUnavailable(str(error.reason)) from error
    raise RegistryUnavailable(last_reason)


def _pep503(name: str) -> str:
    """PyPI simple-index name normalisation (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _registry_has(url: str) -> bool:
    """True for 200, False for 404; anything else is not an answer."""
    status = _request_status(url)
    if status == 200:
        return True
    if status == 404:
        return False
    raise RegistryUnavailable(f"HTTP {status}")


def extract_python_imports(code: str) -> list[tuple[str, int]]:
    """(top-level module name, line) pairs imported by Python source.

    Full fidelity via the AST: plain imports, from-imports (relative ones
    skipped - they are first-party by construction), and literal-argument
    importlib.import_module()/__import__() calls. Source the parser
    refuses falls back to line-regex extraction - the same fidelity trade
    the review engine makes for hunk mode.
    """
    try:
        tree = ast.parse(code)
    except PARSER_REFUSALS:
        fallback_pairs: list[tuple[str, int]] = []
        for number, line in enumerate(code.splitlines(), start=1):
            match = _PY_IMPORT_LINE_RE.match(line)
            if match:
                dotted = match.group(1) or match.group(2)
                fallback_pairs.append((dotted.split(".")[0], number))
        return fallback_pairs

    pairs: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            pairs.extend((alias.name.split(".")[0], node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                pairs.append((node.module.split(".")[0], node.lineno))
        elif isinstance(node, ast.Call):
            callee = node.func
            is_import_module = (
                isinstance(callee, ast.Attribute)
                and callee.attr == "import_module"
                and isinstance(callee.value, ast.Name)
                and callee.value.id == "importlib"
            )
            is_dunder_import = isinstance(callee, ast.Name) and callee.id == "__import__"
            if (is_import_module or is_dunder_import) and node.args:
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    pairs.append((argument.value.split(".")[0], node.lineno))
    return pairs


def _js_package_name(specifier: str) -> str | None:
    """Package name from an import specifier, None for non-package paths."""
    if specifier.startswith((".", "/", "#")):
        return None
    if specifier.startswith("node:"):
        return specifier  # kept whole; classified as builtin later
    segments = specifier.split("/")
    if specifier.startswith("@"):
        return "/".join(segments[:2]) if len(segments) >= 2 else None
    return segments[0]


def extract_js_imports(code: str) -> list[tuple[str, int]]:
    """(package name, line) pairs from JavaScript/TypeScript source, via
    string-literal specifiers in import/export/require forms. Relative,
    absolute, and subpath-alias (#) specifiers are skipped."""
    pairs: list[tuple[str, int]] = []
    for number, line in enumerate(code.splitlines(), start=1):
        for pattern in _JS_IMPORT_RES:
            for match in pattern.finditer(line):
                name = _js_package_name(match.group(1))
                if name is not None:
                    pairs.append((name, number))
    return pairs


def _dedupe_keep_first_line(pairs: list[tuple[str, int]]) -> list[tuple[str, int]]:
    seen: dict[str, int] = {}
    for name, line in pairs:
        if name not in seen:
            seen[name] = line
    return sorted(seen.items(), key=lambda item: item[1])


def _verify_python_name(name: str) -> tuple[str, str]:
    """(status, detail) for one Python import name, network last."""
    if name in _PYTHON_STDLIB:
        return STATUS_STDLIB, "Python standard library"
    if not _PY_MODULE_RE.match(name):
        return STATUS_INVALID_NAME, "not a valid Python module name"
    if _registry_has(PYPI_SIMPLE_URL.format(name=_pep503(name))):
        return STATUS_EXISTS, f"PyPI: {_pep503(name)}"
    alias = _PYPI_ALIASES.get(name)
    if alias is not None and _registry_has(PYPI_SIMPLE_URL.format(name=_pep503(alias))):
        return STATUS_EXISTS_AS, f"import name for PyPI distribution '{alias}'"
    return STATUS_MISSING, "no such distribution on PyPI"


def _verify_js_name(name: str) -> tuple[str, str]:
    """(status, detail) for one npm package name, network last."""
    if name.startswith("node:") or name in _NODE_BUILTINS:
        return STATUS_BUILTIN, "Node.js built-in module"
    if len(name) > 214 or not _NPM_NAME_RE.match(name):
        return STATUS_INVALID_NAME, "not a valid npm package name"
    quoted = name.replace("/", "%2F") if name.startswith("@") else name
    if _registry_has(NPM_REGISTRY_URL.format(name=quoted)):
        return STATUS_EXISTS, f"npm: {name}"
    return STATUS_MISSING, "no such package on the npm registry"


def _gather_from_code(code: str, language: str) -> tuple[list[tuple[str, int, str]], set[str]]:
    normalized = language.strip().lower()
    if normalized in ("python", "py"):
        pairs = _dedupe_keep_first_line(extract_python_imports(code))
        return [(name, line, "python") for name, line in pairs], set()
    if normalized in ("javascript", "js", "jsx", "typescript", "ts", "tsx", "node"):
        pairs = _dedupe_keep_first_line(extract_js_imports(code))
        return [(name, line, "npm") for name, line in pairs], set()
    raise ValueError(f"Unsupported language {language!r}: use python, javascript, or typescript.")


def _python_modules_provided(path: str, provided: set[str]) -> None:
    """Record the top-level import names a changed Python file provides:
    its own stem, and its top-level package directory when packaged."""
    stem = path.rsplit("/", 1)[-1]
    if stem.endswith(".py"):
        provided.add(stem[: -len(".py")])
    if "/" in path:
        provided.add(path.split("/")[0])


def _gather_from_diff(diff_text: str) -> tuple[list[tuple[str, int, str]], set[str]]:
    """Names from a unified diff's added lines, with new-file line numbers,
    plus the set of top-level Python modules the diff itself provides
    (those are first-party, not registry candidates)."""
    gathered: list[tuple[str, int, str]] = []
    provided: set[str] = set()
    for file_diff in parse_unified_diff(diff_text):
        path = file_diff.path
        if path.endswith(".py"):
            _python_modules_provided(path, provided)
        if not file_diff.added_lines:
            continue
        line_numbers = sorted(file_diff.added_lines)
        if path.endswith(".py"):
            fragment = "\n".join(file_diff.added_lines[number] for number in line_numbers)
            for name, fragment_line in extract_python_imports(fragment):
                if 1 <= fragment_line <= len(line_numbers):
                    gathered.append((name, line_numbers[fragment_line - 1], "python"))
        elif path.endswith(_JS_EXTENSIONS):
            for number in line_numbers:
                for pattern in _JS_IMPORT_RES:
                    for match in pattern.finditer(file_diff.added_lines[number]):
                        package_name = _js_package_name(match.group(1))
                        if package_name is not None:
                            gathered.append((package_name, number, "npm"))
    deduped: dict[tuple[str, str], int] = {}
    for name, line, ecosystem in gathered:
        key = (name, ecosystem)
        if key not in deduped:
            deduped[key] = line
    ordered = sorted(deduped.items(), key=lambda item: item[1])
    return [(name, line, ecosystem) for (name, ecosystem), line in ordered], provided


def _verify_one(name: str, ecosystem: str, provided: set[str], exclude: list[str]) -> tuple[str, str]:
    """Classification tiers for one name; the registry is consulted last."""
    if any(fnmatch(name, pattern) for pattern in exclude):
        return STATUS_EXCLUDED, "matched an exclude glob; not sent to any registry"
    if ecosystem == "python" and name in provided:
        return STATUS_FIRST_PARTY, "module provided by this change"
    try:
        if ecosystem == "python":
            return _verify_python_name(name)
        return _verify_js_name(name)
    except RegistryUnavailable as error:
        return STATUS_UNVERIFIABLE, f"registry gave no definitive answer: {error}"


def verify_dependencies(
    code: str | None = None,
    language: str | None = None,
    diff: str | None = None,
    exclude: list[str] | None = None,
) -> Report:
    """Verify that every external dependency a change introduces exists.

    Args:
        code: Source text to extract imports from (requires `language`).
        language: "python", "javascript", or "typescript" (with `code`).
        diff: Unified diff; imports are extracted from added lines of
            Python/JS/TS files with new-file line numbers. Exactly one of
            `code` and `diff` must be supplied.
        exclude: fnmatch globs for names that must never be sent to a
            registry (private/internal packages).

    Returns:
        dict with `verdict` (FAIL when anything is missing from its
        registry, REVIEW when anything was unverifiable or invalidly
        named, PASS otherwise), `summary`, `packages` (name, ecosystem,
        line, status, detail), and `totals` by status.

    Raises:
        ValueError: Both or neither of code/diff, an unsupported
            language, or more than MAX_PACKAGES_PER_CALL distinct names.

    Network: package names (nothing else) are sent to pypi.org and
    registry.npmjs.org over HTTPS, bounded by REQUEST_TIMEOUT_SECONDS and
    MAX_ATTEMPTS. Offline yields REVIEW, never PASS.
    """
    if (code is None) == (diff is None):
        raise ValueError("Supply exactly one of 'code' (with 'language') or 'diff'.")
    if code is not None:
        if not language:
            raise ValueError("'language' is required with 'code'.")
        names, provided = _gather_from_code(code, language)
    else:
        assert diff is not None
        names, provided = _gather_from_diff(diff)

    if len(names) > MAX_PACKAGES_PER_CALL:
        raise ValueError(
            f"{len(names)} distinct packages exceeds the per-call limit of "
            f"{MAX_PACKAGES_PER_CALL}; verify the change in smaller units."
        )

    packages: list[Report] = []
    totals: dict[str, int] = {}
    for name, line, ecosystem in names:
        status, detail = _verify_one(name, ecosystem, provided, list(exclude or []))
        totals[status] = totals.get(status, 0) + 1
        packages.append(
            {"name": name, "ecosystem": ecosystem, "line": line, "status": status, "detail": detail}
        )

    missing = totals.get(STATUS_MISSING, 0)
    undecided = totals.get(STATUS_UNVERIFIABLE, 0) + totals.get(STATUS_INVALID_NAME, 0)
    if missing:
        verdict = "FAIL"
        summary = (
            f"{missing} dependency(ies) do not exist on their registry - hallucinated or "
            "misspelled, and either way a supply-chain attack surface (slopsquatting). "
            "G4 fails: the change references dependencies that cannot be installed."
        )
    elif undecided:
        verdict = "REVIEW"
        summary = (
            f"{undecided} dependency(ies) could not be verified (network unavailable, registry "
            "errors, or invalid names). Unverified is not verified: re-run with connectivity "
            "or vet these names by hand before trusting G4."
        )
    else:
        verdict = "PASS"
        summary = (
            "Every external dependency resolves: standard library, first-party, or present on "
            "its registry. G4's existence half is satisfied; version pinning and integrity "
            "remain the reviewer's judgement."
        )

    return {
        "verdict": verdict,
        "summary": summary,
        "packages": packages,
        "totals": totals,
    }
