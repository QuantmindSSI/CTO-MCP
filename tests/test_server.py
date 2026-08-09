#!/usr/bin/env python3
"""Test suite for the persona-constitution MCP server.

Two layers of verification:
  1. Unit tests that import the module directly and exercise the markdown
     extractors, the violation scanner, and the JSON-RPC dispatcher.
  2. End-to-end transport tests that spawn the server as a subprocess and
     drive it over real stdio with newline-delimited JSON-RPC frames.

Run: python3 -m unittest discover -s tests -v
 or: python3 tests/test_server.py
Dependencies: Python 3.9+ standard library only.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = PROJECT_ROOT / "persona_constitution" / "server.py"
CONSTITUTION_PATH = PROJECT_ROOT / "data" / "CONSTITUTION.md"

sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution import server  # noqa: E402 - path must be set before import.

STUB_CODE = '''def process(data):
    # TODO: implement this later
    pass


def handler(request):
    ...


def compute(values):
    raise NotImplementedError


try:
    run()
except Exception:
    pass

# The rest of the implementation follows the same pattern.
# This is a starting point you can build on.
# Error handling omitted for brevity.
'''

CLEAN_CODE = '''def add(a: int, b: int) -> int:
    """Return the sum of two integers.

    Raises TypeError if either argument is not an int. Complexity: O(1).
    """
    if not isinstance(a, int) or not isinstance(b, int):
        raise TypeError("add requires int arguments")
    return a + b


def safe_divide(numerator: float, denominator: float) -> float:
    """Return numerator / denominator, raising ZeroDivisionError explicitly."""
    if denominator == 0:
        raise ZeroDivisionError("denominator must be non-zero")
    return numerator / denominator
'''


def run_server(messages, env=None, timeout=30):
    """Spawn the server, feed it `messages`, and return the parsed responses.

    `messages` is a list of dicts (sent as newline-delimited JSON) or raw
    strings (sent verbatim, for malformed-input tests). Returns
    (responses, stderr_text, returncode).
    """
    payload = []
    for message in messages:
        payload.append(message if isinstance(message, str) else json.dumps(message))
    stdin_data = "\n".join(payload) + "\n"
    completed = subprocess.run(
        [sys.executable, str(SERVER_PATH)],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    return responses, completed.stderr, completed.returncode


def index_by_id(responses):
    """Return {id: response}. Responses with a null id are keyed under None."""
    return {response.get("id"): response for response in responses}


def tool_text(response):
    """Extract the text payload of a tools/call result."""
    return response["result"]["content"][0]["text"]


class TestConstitutionLoading(unittest.TestCase):
    def test_data_file_exists_and_is_substantial(self):
        self.assertTrue(CONSTITUTION_PATH.is_file(), f"missing {CONSTITUTION_PATH}")
        self.assertGreater(len(CONSTITUTION_PATH.read_text(encoding="utf-8")), 50_000)

    def test_load_constitution_returns_text(self):
        text = server.load_constitution(CONSTITUTION_PATH)
        self.assertIn("THE SUPREME LAW", text)

    def test_missing_file_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                server.load_constitution(Path(tmp) / "absent.md")

    def test_empty_file_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.md"
            empty.write_text("   \n", encoding="utf-8")
            with self.assertRaises(ValueError):
                server.load_constitution(empty)

    def test_env_override_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "custom.md"
            custom.write_text("## PART IX\n\ncontent\n", encoding="utf-8")
            import os

            previous = os.environ.get("PERSONA_CONSTITUTION_PATH")
            os.environ["PERSONA_CONSTITUTION_PATH"] = str(custom)
            try:
                self.assertEqual(server.resolve_constitution_path(), custom.resolve())
            finally:
                if previous is None:
                    del os.environ["PERSONA_CONSTITUTION_PATH"]
                else:
                    os.environ["PERSONA_CONSTITUTION_PATH"] = previous


class TestMarkdownExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = server.load_constitution(CONSTITUTION_PATH)

    def test_every_mapped_section_resolves(self):
        for key, prefix in server.SECTION_MAP.items():
            with self.subTest(section=key):
                extracted = server.find_section(self.text, prefix)
                self.assertIsNotNone(extracted, f"section '{key}' ({prefix}) not found")
                self.assertGreater(len(extracted), 200, f"section '{key}' suspiciously short")

    def test_all_eighteen_knowledge_areas_resolve(self):
        import re

        for number in range(1, 19):
            with self.subTest(ka=number):
                extracted = server.find_subsection(self.text, re.compile(rf"^KA-{number:02d}\b"))
                self.assertIsNotNone(extracted, f"KA-{number:02d} not found")
                self.assertIn(server.KA_TITLES[number], extracted)

    def test_all_ten_power_of_10_rules_resolve(self):
        import re

        part_ix = server.find_section(self.text, "PART IX")
        self.assertIsNotNone(part_ix)
        for number in range(1, 11):
            with self.subTest(rule=number):
                extracted = server.find_subsection(part_ix, re.compile(rf"^Rule {number}\b"))
                self.assertIsNotNone(extracted, f"Rule {number} not found")
                self.assertIn("Original Rule", extracted)

    def test_fenced_code_blocks_do_not_create_sections(self):
        sample = "## Real\n\nbody\n\n```\n## NotAHeading\n```\n\n## Second\n\nmore\n"
        headings = [heading for heading, _ in server.split_headings(sample, 2)]
        self.assertEqual(headings, ["Real", "Second"])

    def test_missing_section_returns_none(self):
        self.assertIsNone(server.find_section(self.text, "PART XCIX"))


class TestViolationScanner(unittest.TestCase):
    def test_clean_code_passes_with_no_findings(self):
        result = server.scan_code(CLEAN_CODE)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["findings"], [])

    def test_stub_code_fails(self):
        result = server.scan_code(STUB_CODE)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertGreater(len(result["findings"]), 5)

    def test_stub_code_detects_each_failure_class(self):
        classes = {finding["class"] for finding in server.scan_code(STUB_CODE)["findings"]}
        for expected in ("Class 1", "Class 2", "Class 3", "Class 5"):
            with self.subTest(failure_class=expected):
                self.assertTrue(any(expected in c for c in classes), f"{expected} not detected")

    def test_line_numbers_are_accurate(self):
        code = "line one\nline two\n# TODO: fix\nline four\n"
        findings = server.scan_code(code)["findings"]
        todo = [f for f in findings if "TODO" in f["finding"]]
        self.assertEqual(len(todo), 1)
        self.assertEqual(todo[0]["line"], 3)
        self.assertEqual(todo[0]["text"], "# TODO: fix")

    def test_warning_only_code_returns_review(self):
        result = server.scan_code("value = 1  # XXX revisit sizing\n")
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["severity"], "warning")

    def test_notimplementederror_stub_detected(self):
        result = server.scan_code("def f():\n    raise NotImplementedError\n")
        self.assertEqual(result["verdict"], "FAIL")

    def test_rust_todo_macro_detected(self):
        result = server.scan_code("fn parse(s: &str) -> u32 {\n    todo!()\n}\n")
        self.assertEqual(result["verdict"], "FAIL")

    def test_empty_js_catch_block_detected(self):
        result = server.scan_code("try {\n  work();\n} catch (e) {}\n")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("catch" in f["finding"] for f in result["findings"]))

    def test_findings_are_sorted_by_line(self):
        lines = [f["line"] for f in server.scan_code(STUB_CODE)["findings"]]
        self.assertEqual(lines, sorted(lines))

    def test_docstring_only_stub_detected(self):
        code = 'def f(a):\n    """Docstring only."""\n    pass\n'
        self.assertEqual(server.scan_code(code)["verdict"], "FAIL")


class TestDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = server.load_constitution(CONSTITUTION_PATH)

    def call(self, name, arguments):
        response = server.dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": name, "arguments": arguments}},
            self.text,
        )
        return response["result"]

    def test_toc_lists_all_sections_and_supreme_law(self):
        text = tool_text({"result": self.call("get_constitution", {})})
        for key in server.SECTION_MAP:
            self.assertIn(f"- {key}:", text)
        self.assertIn("SUPREME LAW", text)

    def test_full_returns_entire_document(self):
        self.assertEqual(tool_text({"result": self.call("get_constitution", {"section": "full"})}), self.text)

    def test_unknown_section_is_tool_error(self):
        result = self.call("get_constitution", {"section": "nonexistent"})
        self.assertTrue(result["isError"])
        self.assertIn("Unknown section", result["content"][0]["text"])

    def test_knowledge_area_by_number_and_name_agree(self):
        by_number = tool_text({"result": self.call("get_knowledge_area", {"ka": 13})})
        by_name = tool_text({"result": self.call("get_knowledge_area", {"ka": "Software Security"})})
        self.assertEqual(by_number, by_name)
        self.assertIn("STRIDE", by_number)

    def test_knowledge_area_accepts_ka_prefixed_string(self):
        self.assertIn("KA-05", tool_text({"result": self.call("get_knowledge_area", {"ka": "KA-05"})}))

    def test_knowledge_area_listing_when_omitted(self):
        text = tool_text({"result": self.call("get_knowledge_area", {})})
        for number in range(1, 19):
            self.assertIn(f"KA-{number:02d}", text)

    def test_knowledge_area_out_of_range_is_tool_error(self):
        self.assertTrue(self.call("get_knowledge_area", {"ka": 99})["isError"])

    def test_ambiguous_knowledge_area_name_is_tool_error(self):
        result = self.call("get_knowledge_area", {"ka": "Software Engineering"})
        self.assertTrue(result["isError"])
        self.assertIn("Ambiguous", result["content"][0]["text"])

    def test_power_of_10_single_rule(self):
        text = tool_text({"result": self.call("get_power_of_10", {"rule": 7})})
        self.assertIn("Rule 7", text)
        self.assertIn("Return Value Checking", text)

    def test_power_of_10_all_rules_when_omitted(self):
        text = tool_text({"result": self.call("get_power_of_10", {})})
        for number in range(1, 11):
            self.assertIn(f"Rule {number} —", text)

    def test_power_of_10_out_of_range_is_tool_error(self):
        self.assertTrue(self.call("get_power_of_10", {"rule": 11})["isError"])

    def test_verification_gates_contains_all_five(self):
        text = tool_text({"result": self.call("get_verification_gates", {})})
        for gate in ("G1", "G2", "G3", "G4", "G5"):
            self.assertIn(gate, text)

    def test_scan_tool_returns_parseable_json(self):
        payload = json.loads(tool_text({"result": self.call("scan_code_for_violations", {"code": STUB_CODE})}))
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertIn("summary", payload)

    def test_scan_tool_rejects_empty_code(self):
        self.assertTrue(self.call("scan_code_for_violations", {"code": "   "})["isError"])

    def test_scan_tool_rejects_oversized_code(self):
        oversized = "x = 1\n" * 400_000
        self.assertGreater(len(oversized), server.MAX_SCAN_BYTES)
        self.assertTrue(self.call("scan_code_for_violations", {"code": oversized})["isError"])

    def test_unknown_tool_is_protocol_error(self):
        response = server.dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "no_such_tool"}},
            self.text,
        )
        self.assertEqual(response["error"]["code"], server.INVALID_PARAMS)

    def test_notifications_receive_no_response(self):
        self.assertIsNone(server.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.text))

    def test_unknown_method_returns_method_not_found(self):
        response = server.dispatch({"jsonrpc": "2.0", "id": 9, "method": "does/not/exist"}, self.text)
        self.assertEqual(response["error"]["code"], server.METHOD_NOT_FOUND)

    def test_non_jsonrpc_message_is_invalid_request(self):
        response = server.dispatch({"id": 1, "method": "ping"}, self.text)
        self.assertEqual(response["error"]["code"], server.INVALID_REQUEST)

    def test_non_object_params_is_invalid_params(self):
        response = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": [1, 2]}, self.text)
        self.assertEqual(response["error"]["code"], server.INVALID_PARAMS)


class TestToolSchemas(unittest.TestCase):
    def test_every_tool_has_description_and_object_schema(self):
        for name, spec in server.TOOLS.items():
            with self.subTest(tool=name):
                self.assertGreater(len(spec["description"]), 80)
                self.assertEqual(spec["inputSchema"]["type"], "object")
                self.assertIn("properties", spec["inputSchema"])
                self.assertTrue(callable(spec["handler"]))

    def test_section_enum_matches_section_map(self):
        enum = server.TOOLS["get_constitution"]["inputSchema"]["properties"]["section"]["enum"]
        self.assertEqual(set(enum), set(server.SECTION_MAP) | {"full", "toc"})

    def test_scan_tool_requires_code(self):
        self.assertEqual(server.TOOLS["scan_code_for_violations"]["inputSchema"]["required"], ["code"])


class TestStdioTransport(unittest.TestCase):
    def test_initialize_handshake(self):
        responses, _, code = run_server([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"}}},
        ])
        self.assertEqual(code, 0)
        result = responses[0]["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "persona-constitution")
        self.assertIn("tools", result["capabilities"])
        self.assertIn("no placeholders", result["instructions"])

    def test_tools_list_advertises_all_five_tools(self):
        responses, _, _ = run_server([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
        names = {tool["name"] for tool in responses[0]["result"]["tools"]}
        self.assertEqual(names, set(server.TOOLS))

    def test_notification_produces_no_frame(self):
        responses, _, _ = run_server([
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        ])
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 1)

    def test_malformed_line_returns_parse_error_and_stream_survives(self):
        responses, _, code = run_server([
            "this is not json",
            {"jsonrpc": "2.0", "id": 5, "method": "ping"},
        ])
        self.assertEqual(code, 0)
        by_id = index_by_id(responses)
        self.assertEqual(by_id[None]["error"]["code"], server.PARSE_ERROR)
        self.assertEqual(by_id[5]["result"], {})

    def test_blank_lines_are_ignored(self):
        responses, _, _ = run_server(["", "   ", {"jsonrpc": "2.0", "id": 2, "method": "ping"}])
        self.assertEqual(len(responses), 1)

    def test_full_session_end_to_end(self):
        responses, stderr, code = run_server([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "get_constitution", "arguments": {"section": "invariants"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "get_knowledge_area", "arguments": {"ka": 2}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "get_power_of_10", "arguments": {"rule": 10}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
             "params": {"name": "get_verification_gates", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
             "params": {"name": "scan_code_for_violations", "arguments": {"code": CLEAN_CODE}}},
        ])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        by_id = index_by_id(responses)
        self.assertEqual(len(responses), 7)
        self.assertIn("Implementation is the only proof", tool_text(by_id[3]))
        self.assertIn("Software Architecture", tool_text(by_id[4]))
        self.assertIn("Zero Warnings", tool_text(by_id[5]))
        self.assertIn("G5", tool_text(by_id[6]))
        self.assertEqual(json.loads(tool_text(by_id[7]))["verdict"], "PASS")

    def test_missing_constitution_exits_nonzero_with_stderr(self):
        import os

        env = dict(os.environ, PERSONA_CONSTITUTION_PATH="/nonexistent/path/CONSTITUTION.md")
        _, stderr, code = run_server([{"jsonrpc": "2.0", "id": 1, "method": "ping"}], env=env)
        self.assertEqual(code, 1)
        self.assertIn("fatal", stderr)

    def test_stdout_carries_only_protocol_frames(self):
        completed = subprocess.run(
            [sys.executable, str(SERVER_PATH)],
            input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
            capture_output=True, text=True, timeout=30,
        )
        for line in completed.stdout.splitlines():
            if line.strip():
                parsed = json.loads(line)
                self.assertEqual(parsed["jsonrpc"], "2.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
