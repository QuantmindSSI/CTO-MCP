#!/usr/bin/env python3
"""Smoke suite: the critical path of every delivery surface, in seconds.

Purpose: catch a broken install/wiring immediately - before the deeper unit,
integration, e2e, and regression layers spend their time. Everything here
must stay fast; anything slow belongs in the other suites.

Covered surfaces:
  * package import + version coherence,
  * scanner verdict on one stub and one clean input,
  * review engine verdict on one stub diff,
  * the persona-pr-review console entry point (as `python -m`),
  * the MCP server over real stdio: initialize + tools/list.

Run: python3 -m unittest tests.test_smoke -v
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = PROJECT_ROOT / "persona_constitution" / "server.py"
sys.path.insert(0, str(PROJECT_ROOT))

import persona_constitution  # noqa: E402 - path must be set before import.

EXPECTED_TOOLS = {
    "get_constitution",
    "get_knowledge_area",
    "get_power_of_10",
    "get_verification_gates",
    "scan_code_for_violations",
    "review_patch",
    "verify_dependencies",
}


class TestSmoke(unittest.TestCase):
    def test_package_imports_with_coherent_version(self):
        self.assertEqual(persona_constitution.__version__, persona_constitution.SERVER_INFO["version"])

    def test_scanner_critical_path(self):
        stub = persona_constitution.scan_code("def f():\n    pass  # TODO: implement later\n")
        self.assertEqual(stub["verdict"], "FAIL")
        clean = persona_constitution.scan_code("def double(x):\n    return x * 2\n")
        self.assertEqual(clean["verdict"], "PASS")

    def test_review_engine_critical_path(self):
        diff_text = (
            "diff --git a/svc/h.py b/svc/h.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/svc/h.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+def handle(evt):\n"
            "+    raise NotImplementedError\n"
        )
        review = persona_constitution.review_patch(diff_text)
        self.assertEqual(review["verdict"], "FAIL")

    def test_console_entry_point_responds(self):
        completed = subprocess.run(
            [sys.executable, "-m", "persona_constitution.review.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=PROJECT_ROOT,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--staged", completed.stdout)
        self.assertIn("--install-hook", completed.stdout)

    def test_mcp_server_stdio_handshake_and_tool_list(self):
        frames = "\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "smoke", "version": "1"},
                        },
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            ]
        )
        completed = subprocess.run(
            [sys.executable, str(SERVER_PATH)],
            input=frames + "\n",
            capture_output=True,
            text=True,
            timeout=30,
            cwd=PROJECT_ROOT,
        )
        responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        by_id = {response.get("id"): response for response in responses}
        self.assertIn(1, by_id, completed.stderr)
        listed = {tool["name"] for tool in by_id[2]["result"]["tools"]}
        self.assertEqual(listed, EXPECTED_TOOLS)


if __name__ == "__main__":
    unittest.main()
