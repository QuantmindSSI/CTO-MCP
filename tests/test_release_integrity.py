#!/usr/bin/env python3
"""Release-integrity tests: the version is declared once and reported truthfully.

pyproject.toml is the single declaration point. The package (__version__),
the MCP handshake (serverInfo.version), and the resolver behind them must
all agree with it, in a source checkout and in an installed wheel alike.
These tests kill the drift class where the server announces one version
while the package ships another (which existed: 3.2.0 was triplicated
across pyproject.toml, server.py, and __init__.py).

Run: python3 -m unittest discover -s tests -v
Dependencies: Python 3.9+ standard library only.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import persona_constitution  # noqa: E402 - path must be set before import.
from persona_constitution import _version, server  # noqa: E402

PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def _pyproject_version_independent():
    """Read the declared version with an implementation independent of the
    resolver under test (a deliberately different parsing strategy)."""
    text = PYPROJECT.read_text(encoding="utf-8")
    project_table = text.split("[project]", 1)[1].split("\n[", 1)[0]
    match = re.search(r'^version\s*=\s*"([^"]+)"', project_table, re.MULTILINE)
    assert match is not None, "pyproject.toml declares no [project] version"
    return match.group(1)


class TestSingleSourcedVersion(unittest.TestCase):
    """Every surface reports the version pyproject.toml declares."""

    def setUp(self):
        self.declared = _pyproject_version_independent()

    def test_package_dunder_version_matches_pyproject(self):
        self.assertEqual(persona_constitution.__version__, self.declared)

    def test_server_info_matches_pyproject(self):
        self.assertEqual(server.SERVER_INFO["version"], self.declared)

    def test_initialize_handshake_reports_declared_version(self):
        response = server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": server.PROTOCOL_VERSION},
            },
            "unused constitution text",
        )
        self.assertEqual(response["result"]["serverInfo"]["version"], self.declared)

    def test_version_is_pep440_release_shaped(self):
        """Guards against a placeholder or a parse artefact escaping into
        the handshake (e.g. an empty string or a TOML fragment)."""
        self.assertRegex(self.declared, r"^\d+\.\d+\.\d+")

    def test_changelog_has_a_section_for_the_declared_version(self):
        """The release workflow refuses a tag with no changelog section;
        this makes the same discipline fail earlier, at test time. Bumping
        pyproject.toml without writing the changelog is an incomplete
        release, so it is an incomplete change."""
        changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(
            f"## [{self.declared}]",
            changelog,
            f"CHANGELOG.md has no section for version {self.declared}",
        )


class TestVersionResolver(unittest.TestCase):
    """parse_pyproject_version trusts only this project's own declaration."""

    def _write(self, content):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "pyproject.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_reads_project_version(self):
        path = self._write(
            '[build-system]\nrequires = ["setuptools"]\n\n'
            '[project]\nname = "persona-constitution-mcp"\nversion = "9.9.9"\n'
        )
        self.assertEqual(_version.parse_pyproject_version(path), "9.9.9")

    def test_rejects_foreign_project(self):
        """A pyproject.toml for some other package must never supply our
        version, no matter where the package directory happens to sit."""
        path = self._write('[project]\nname = "somebody-else"\nversion = "1.0.0"\n')
        self.assertIsNone(_version.parse_pyproject_version(path))

    def test_rejects_version_outside_project_table(self):
        path = self._write(
            '[tool.poetry]\nversion = "0.0.1"\n\n[project]\nname = "persona-constitution-mcp"\n'
        )
        self.assertIsNone(_version.parse_pyproject_version(path))

    def test_missing_file_returns_none(self):
        missing = Path(tempfile.mkdtemp()) / "pyproject.toml"
        self.assertIsNone(_version.parse_pyproject_version(missing))

    def test_resolver_returns_the_checkout_version(self):
        """In this checkout, the resolver must return exactly the declared
        version (the metadata fallback only applies to installed wheels)."""
        self.assertEqual(_version.resolve_version(), _pyproject_version_independent())


if __name__ == "__main__":
    unittest.main()
