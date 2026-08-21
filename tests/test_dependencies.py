#!/usr/bin/env python3
"""verify_dependencies contracts: extraction, tiers, honesty, bounds.

Every registry interaction is mocked at the module's single network
egress (_request_status) - the suite runs identically with the cable
unplugged, which is itself one of the behaviours under test: offline is
REVIEW ("unverifiable"), never PASS and never a crash.

The tier order is part of the contract and is asserted: excluded and
stdlib and first-party names must never generate a registry query at
all - the network is the last resort and package names are the only
thing that ever leaves the machine.

Run: python3 -m unittest discover -s tests -v
Dependencies: Python 3.9+ standard library only.
"""

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution import dependencies, server  # noqa: E402 - path first.


class _FakeRegistry:
    """URL -> status map that records every query it serves."""

    def __init__(self, statuses):
        self.statuses = statuses
        self.queried = []

    def __call__(self, url):
        self.queried.append(url)
        for fragment, status in self.statuses.items():
            if fragment in url:
                if status == "down":
                    raise dependencies.RegistryUnavailable("connection refused")
                return status
        raise AssertionError(f"unexpected registry query: {url}")


def _verify(statuses, **kwargs):
    registry = _FakeRegistry(statuses)
    with mock.patch.object(dependencies, "_request_status", registry):
        report = dependencies.verify_dependencies(**kwargs)
    return report, registry


def _status_of(report, name):
    for package in report["packages"]:
        if package["name"] == name:
            return package["status"]
    raise AssertionError(f"{name!r} not in report: {report['packages']}")


class TestPythonExtraction(unittest.TestCase):
    """The AST extractor sees every import form and skips the relative ones."""

    def test_import_forms(self):
        code = (
            "import requests\n"
            "import os.path\n"
            "from flask import Flask\n"
            "from . import sibling\n"
            "from ..pkg import thing\n"
            "import importlib\n"
            'plugin = importlib.import_module("dynamic_pkg")\n'
            'legacy = __import__("legacy_pkg")\n'
        )
        pairs = dependencies.extract_python_imports(code)
        names = {name for name, _ in pairs}
        self.assertEqual(names, {"requests", "os", "flask", "importlib", "dynamic_pkg", "legacy_pkg"})

    def test_lines_are_recorded(self):
        pairs = dict(dependencies.extract_python_imports("import a\n\nimport b\n"))
        self.assertEqual(pairs, {"a": 1, "b": 3})

    def test_unparseable_source_falls_back_to_line_regex(self):
        code = "import requests\ndef broken(:\n    from flask import x\n"
        names = {name for name, _ in dependencies.extract_python_imports(code)}
        self.assertEqual(names, {"requests", "flask"})


class TestJsExtraction(unittest.TestCase):
    """Specifier forms, scopes, subpaths; relative and alias paths skipped."""

    def test_specifier_forms(self):
        code = (
            'import express from "express";\n'
            "import { z } from 'zod/lib';\n"
            'import "@scope/pkg/deep/path";\n'
            'const local = require("./local");\n'
            'const abs = require("/abs/path");\n'
            'const aliased = require("#internal/alias");\n'
            'const fs = require("node:fs");\n'
            'export { thing } from "left-pad";\n'
            'const lazy = await import("lazy-pkg");\n'
        )
        names = {name for name, _ in dependencies.extract_js_imports(code)}
        self.assertEqual(names, {"express", "zod", "@scope/pkg", "node:fs", "left-pad", "lazy-pkg"})


class TestClassificationTiers(unittest.TestCase):
    """Local tiers answer without the network; the order is the contract."""

    def test_stdlib_never_queries_a_registry(self):
        report, registry = _verify({}, code="import json, os, tomllib\n", language="python")
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(registry.queried, [])
        self.assertEqual(_status_of(report, "json"), dependencies.STATUS_STDLIB)
        self.assertEqual(_status_of(report, "tomllib"), dependencies.STATUS_STDLIB)

    def test_node_builtins_never_query(self):
        code = 'const fs = require("fs");\nconst nfs = require("node:fs");\n'
        report, registry = _verify({}, code=code, language="javascript")
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(registry.queried, [])
        self.assertEqual(_status_of(report, "fs"), dependencies.STATUS_BUILTIN)
        self.assertEqual(_status_of(report, "node:fs"), dependencies.STATUS_BUILTIN)

    def test_excluded_globs_never_query(self):
        report, registry = _verify(
            {}, code="import internal_billing\n", language="python", exclude=["internal_*"]
        )
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(registry.queried, [])
        self.assertEqual(_status_of(report, "internal_billing"), dependencies.STATUS_EXCLUDED)

    def test_diff_provided_modules_are_first_party(self):
        diff = (
            "diff --git a/helpers.py b/helpers.py\n"
            "--- a/helpers.py\n+++ b/helpers.py\n@@ -0,0 +1,1 @@\n+def assist(): return 1\n"
            "diff --git a/main.py b/main.py\n"
            "--- a/main.py\n+++ b/main.py\n@@ -0,0 +1,2 @@\n+import helpers\n+import json\n"
        )
        report, registry = _verify({}, diff=diff)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(registry.queried, [])
        self.assertEqual(_status_of(report, "helpers"), dependencies.STATUS_FIRST_PARTY)


class TestRegistryVerdicts(unittest.TestCase):
    """Existence, alias resolution, hallucination, and offline honesty."""

    def test_existing_package_passes(self):
        report, registry = _verify(
            {"pypi.org/simple/requests/": 200}, code="import requests\n", language="python"
        )
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(_status_of(report, "requests"), dependencies.STATUS_EXISTS)
        self.assertEqual(len(registry.queried), 1)

    def test_alias_resolves_as_exists_as(self):
        statuses = {"pypi.org/simple/yaml/": 404, "pypi.org/simple/pyyaml/": 200}
        report, _ = _verify(statuses, code="import yaml\n", language="python")
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(_status_of(report, "yaml"), dependencies.STATUS_EXISTS_AS)
        detail = report["packages"][0]["detail"]
        self.assertIn("PyYAML", detail)

    def test_hallucinated_package_fails(self):
        report, _ = _verify(
            {"pypi.org/simple/flask-gpt-magic/": 404},
            code="import flask_gpt_magic\n",
            language="python",
        )
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(_status_of(report, "flask_gpt_magic"), dependencies.STATUS_MISSING)
        self.assertIn("slopsquatting", report["summary"])

    def test_npm_scoped_package_is_url_encoded(self):
        statuses = {"registry.npmjs.org/@scope%2Fpkg": 200}
        report, registry = _verify(statuses, code='import x from "@scope/pkg";\n', language="javascript")
        self.assertEqual(report["verdict"], "PASS")
        self.assertIn("registry.npmjs.org/@scope%2Fpkg", registry.queried[0])

    def test_offline_is_review_never_pass(self):
        report, _ = _verify(
            {"pypi.org/simple/requests/": "down"}, code="import requests\n", language="python"
        )
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertEqual(_status_of(report, "requests"), dependencies.STATUS_UNVERIFIABLE)
        self.assertIn("Unverified is not verified", report["summary"])

    def test_unexpected_status_is_unverifiable_not_missing(self):
        report, _ = _verify({"pypi.org/simple/requests/": 403}, code="import requests\n", language="python")
        self.assertEqual(_status_of(report, "requests"), dependencies.STATUS_UNVERIFIABLE)

    def test_invalid_npm_name_is_review_without_query(self):
        report, registry = _verify({}, code='import x from "Not_Valid_Upper";\n', language="javascript")
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertEqual(registry.queried, [])
        self.assertEqual(_status_of(report, "Not_Valid_Upper"), dependencies.STATUS_INVALID_NAME)

    def test_missing_beats_unverifiable_in_the_verdict(self):
        statuses = {"pypi.org/simple/ghost-pkg/": 404, "pypi.org/simple/requests/": "down"}
        report, _ = _verify(statuses, code="import ghost_pkg\nimport requests\n", language="python")
        self.assertEqual(report["verdict"], "FAIL")


class TestDiffModeLines(unittest.TestCase):
    """Findings carry new-file line numbers, like the review engine."""

    def test_new_file_line_numbers(self):
        diff = (
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n+++ b/app.py\n@@ -0,0 +40,3 @@\n"
            "+import json\n"
            "+import ghost_pkg\n"
            "+x = 1\n"
        )
        report, _ = _verify({"pypi.org/simple/ghost-pkg/": 404}, diff=diff)
        ghost = next(p for p in report["packages"] if p["name"] == "ghost_pkg")
        self.assertEqual(ghost["line"], 41)
        self.assertEqual(report["verdict"], "FAIL")


class TestBoundsAndArguments(unittest.TestCase):
    """Input validation fails loudly, before any network is touched."""

    def test_both_code_and_diff_rejected(self):
        with self.assertRaises(ValueError):
            dependencies.verify_dependencies(code="import a\n", language="python", diff="diff")

    def test_neither_rejected(self):
        with self.assertRaises(ValueError):
            dependencies.verify_dependencies()

    def test_code_without_language_rejected(self):
        with self.assertRaises(ValueError):
            dependencies.verify_dependencies(code="import a\n")

    def test_unsupported_language_rejected(self):
        with self.assertRaises(ValueError):
            dependencies.verify_dependencies(code="import a", language="cobol")

    def test_package_cap_enforced_before_any_query(self):
        code = "\n".join(f"import fake_pkg_{i}" for i in range(dependencies.MAX_PACKAGES_PER_CALL + 1))
        registry = _FakeRegistry({})
        with (
            mock.patch.object(dependencies, "_request_status", registry),
            self.assertRaises(ValueError) as ctx,
        ):
            dependencies.verify_dependencies(code=code, language="python")
        self.assertIn("per-call limit", str(ctx.exception))
        self.assertEqual(registry.queried, [])


class TestRetryBehaviour(unittest.TestCase):
    """_request_status retries transient failures and gives up honestly."""

    def _fake_urlopen(self, effects):
        calls = []

        def opener(request, timeout):  # noqa: ARG001 - urlopen signature
            calls.append(request.full_url)
            effect = effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            response = mock.MagicMock()
            response.status = effect
            response.__enter__ = lambda s: s
            response.__exit__ = lambda s, *a: False  # noqa: ARG005 - context manager shape
            return response

        return opener, calls

    def test_retries_5xx_then_succeeds(self):
        effects = [
            urllib.error.HTTPError("u", 503, "unavailable", None, None),
            200,
        ]
        opener, calls = self._fake_urlopen(effects)
        with (
            mock.patch.object(dependencies.urllib.request, "urlopen", opener),
            mock.patch.object(dependencies.time, "sleep"),
        ):
            status = dependencies._request_status("https://pypi.org/simple/x/")
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 2)

    def test_404_is_definitive_no_retry(self):
        effects = [urllib.error.HTTPError("u", 404, "nope", None, None)]
        opener, calls = self._fake_urlopen(effects)
        with mock.patch.object(dependencies.urllib.request, "urlopen", opener):
            status = dependencies._request_status("https://pypi.org/simple/x/")
        self.assertEqual(status, 404)
        self.assertEqual(len(calls), 1)

    def test_persistent_network_failure_raises_registry_unavailable(self):
        effects = [urllib.error.URLError("refused")] * dependencies.MAX_ATTEMPTS
        opener, calls = self._fake_urlopen(effects)
        with (
            mock.patch.object(dependencies.urllib.request, "urlopen", opener),
            mock.patch.object(dependencies.time, "sleep"),
            self.assertRaises(dependencies.RegistryUnavailable),
        ):
            dependencies._request_status("https://pypi.org/simple/x/")
        self.assertEqual(len(calls), dependencies.MAX_ATTEMPTS)


class TestServerTool(unittest.TestCase):
    """The MCP tool validates at the boundary and returns the JSON report."""

    def test_tool_end_to_end_with_mocked_registry(self):
        registry = _FakeRegistry({"pypi.org/simple/ghost-pkg/": 404})
        with mock.patch.object(dependencies, "_request_status", registry):
            text = server.tool_verify_dependencies(
                "unused", {"code": "import ghost_pkg\n", "language": "python"}
            )
        report = json.loads(text)
        self.assertEqual(report["verdict"], "FAIL")

    def test_tool_rejects_both_modes(self):
        with self.assertRaises(ValueError):
            server.tool_verify_dependencies("unused", {"code": "x", "language": "python", "diff": "d"})

    def test_tool_rejects_oversized_code(self):
        with mock.patch.object(server, "MAX_SCAN_BYTES", 10), self.assertRaises(ValueError):
            server.tool_verify_dependencies("unused", {"code": "import aaaaaaaaaa\n", "language": "python"})

    def test_tool_is_advertised_with_network_notice(self):
        spec = server.TOOLS["verify_dependencies"]
        self.assertIn("NETWORK NOTICE", spec["description"])
        self.assertIs(spec["inputSchema"]["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
