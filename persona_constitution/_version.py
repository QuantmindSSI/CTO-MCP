"""Single source of truth for the package version.

The version is declared exactly once, in pyproject.toml. Everything else
(the MCP initialize handshake's serverInfo, ``persona_constitution.__version__``,
the wheel metadata) derives from it through this module, so the class of
defect where the server announces one version while the package ships
another cannot exist.

Resolution order, and why:

1. The ``pyproject.toml`` sitting next to the package (a source checkout,
   including editable installs). This wins over installed metadata because
   ``pip install -e`` records the version at install time: after a bump, the
   metadata is stale until reinstall, while the checkout file is always
   current. The file must declare ``name = "persona-constitution-mcp"`` -
   an unrelated pyproject.toml that happens to share a parent directory is
   rejected rather than trusted.

2. ``importlib.metadata`` for the installed-wheel case, where pyproject.toml
   does not ship.

3. Neither resolving is a broken installation and raises: a server that
   cannot state its own version truthfully must not pretend to (the same
   contract as the missing-CONSTITUTION.md fatal in server.py).

Leaf module by design: imports nothing from this package, so both server.py
(which the package __init__ imports) and __init__.py itself can use it
without an import cycle.
"""

import re
from pathlib import Path

PACKAGE_DIST_NAME = "persona-constitution-mcp"

_KEY_VALUE_RE = re.compile(r'^(name|version)\s*=\s*"([^"]+)"\s*(?:#.*)?$')


def parse_pyproject_version(pyproject_path):
    """Return the [project] version from a pyproject.toml, or None.

    None when the file is absent, unreadable, does not declare the
    ``[project]`` table, or declares a project other than
    ``persona-constitution-mcp`` (the name guard: never report a foreign
    project's version as ours).
    """
    try:
        text = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        return None

    in_project = False
    name = None
    version = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_project = line == "[project]"
            continue
        if not in_project:
            continue
        match = _KEY_VALUE_RE.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2)
        if key == "name":
            name = value
        else:
            version = value
        if name is not None and version is not None:
            break

    if name != PACKAGE_DIST_NAME:
        return None
    return version


def resolve_version():
    """Resolve the canonical package version. Raises RuntimeError when the
    installation is too broken to know it (no checkout pyproject.toml and no
    installed distribution metadata)."""
    checkout_version = parse_pyproject_version(Path(__file__).resolve().parent.parent / "pyproject.toml")
    if checkout_version is not None:
        return checkout_version

    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError as exc:  # pragma: no cover - stdlib since 3.8
        raise RuntimeError(f"importlib.metadata unavailable: {exc}") from exc
    try:
        return version(PACKAGE_DIST_NAME)
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "cannot resolve the package version: no source checkout "
            "pyproject.toml above the package and no installed distribution "
            f"metadata for {PACKAGE_DIST_NAME!r}. Reinstall the package."
        ) from exc


__version__ = resolve_version()
