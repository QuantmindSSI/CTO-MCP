#!/usr/bin/env python3
"""Protocol conformance and fuzzing for the JSON-RPC/MCP boundary.

The dispatcher and the stdio loop are the only code that touches bytes an
arbitrary client controls, so they get the adversarial treatment the
scanner corpus gets:

  Conformance - the shapes the MCP spec promises are pinned exactly:
  initialize, tools/list, tools/call results, error objects, and the
  notification silence rule.

  Fuzzing - a seeded generator mutates valid frames and invents invalid
  ones (wrong types everywhere, deep nesting, unicode noise, huge-ish
  strings), and three invariants must hold for every single frame:
    1. the server never raises;
    2. anything with an id gets exactly one response carrying that id and
       exactly one of result/error;
    3. anything without an id gets silence.

  The seed is fixed: a failure reproduces by running the test again, not
  by hoping. Grow MUTATION_COUNT before trusting a protocol refactor.

Run: python3 -m unittest discover -s tests -v
Dependencies: Python 3.9+ standard library only.
"""

import io
import json
import random
import string
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution import server  # noqa: E402 - path must be set before import.

CONSTITUTION = server.load_constitution()

FUZZ_SEED = 0xC70  # fixed: failures must reproduce
MUTATION_COUNT = 600


def dispatch(message):
    return server.dispatch(message, CONSTITUTION)


class TestInitializeConformance(unittest.TestCase):
    """The initialize result carries exactly the promised members."""

    def setUp(self):
        self.result = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": server.PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "conformance", "version": "0"},
                },
            }
        )["result"]

    def test_protocol_version_is_a_supported_string(self):
        self.assertIsInstance(self.result["protocolVersion"], str)
        self.assertIn(self.result["protocolVersion"], server.SUPPORTED_PROTOCOL_VERSIONS)

    def test_capabilities_advertise_tools(self):
        self.assertIsInstance(self.result["capabilities"], dict)
        self.assertIn("tools", self.result["capabilities"])

    def test_server_info_names_and_versions_itself(self):
        info = self.result["serverInfo"]
        self.assertEqual(info["name"], "persona-constitution")
        self.assertIsInstance(info["version"], str)
        self.assertTrue(info["version"])

    def test_instructions_are_nonempty_text(self):
        self.assertIsInstance(self.result["instructions"], str)
        self.assertTrue(self.result["instructions"].strip())


class TestToolsListConformance(unittest.TestCase):
    """Every advertised tool is completely described and schema-valid."""

    def setUp(self):
        self.tools = dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]

    def test_every_registered_tool_is_advertised(self):
        self.assertEqual({t["name"] for t in self.tools}, set(server.TOOLS))

    def test_every_tool_has_description_and_object_schema(self):
        for tool in self.tools:
            with self.subTest(tool=tool["name"]):
                self.assertTrue(tool["description"].strip())
                schema = tool["inputSchema"]
                self.assertEqual(schema["type"], "object")
                self.assertIsInstance(schema.get("properties", {}), dict)
                # Every schema rejects unknown arguments: silent typo
                # tolerance is how wrong scans pass as clean ones.
                self.assertIs(schema["additionalProperties"], False)

    def test_required_properties_exist_in_properties(self):
        for tool in self.tools:
            schema = tool["inputSchema"]
            for required in schema.get("required", []):
                with self.subTest(tool=tool["name"], required=required):
                    self.assertIn(required, schema["properties"])


class TestToolsCallConformance(unittest.TestCase):
    """tools/call results are content arrays with an isError verdict."""

    def _call(self, name, arguments):
        return dispatch(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )["result"]

    def test_success_shape(self):
        result = self._call("get_power_of_10", {"rule": 4})
        self.assertIs(result["isError"], False)
        self.assertEqual(len(result["content"]), 1)
        self.assertEqual(result["content"][0]["type"], "text")
        self.assertIn("Rule 4", result["content"][0]["text"])

    def test_tool_error_shape_is_a_result_not_a_protocol_error(self):
        """Bad arguments are the model's mistake to read and correct, so
        they surface inside a result per MCP, not as a JSON-RPC error."""
        result = self._call("get_power_of_10", {"rule": 999})
        self.assertIs(result["isError"], True)
        self.assertTrue(result["content"][0]["text"].startswith("Error:"))

    def test_unknown_tool_is_a_protocol_error(self):
        response = dispatch(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "no_such_tool"}}
        )
        self.assertEqual(response["error"]["code"], server.INVALID_PARAMS)


class TestNotificationSilence(unittest.TestCase):
    """Silence is exactly for well-formed notifications; malformed objects
    get an id-null Invalid Request, as the JSON-RPC spec's examples do."""

    def test_notification_method_is_silent(self):
        self.assertIsNone(dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unknown_notification_is_silent(self):
        self.assertIsNone(dispatch({"jsonrpc": "2.0", "method": "does/not/exist"}))

    def test_malformed_method_without_id_gets_id_null_error(self):
        """The spec's own example: {"jsonrpc": "2.0", "method": 1} is
        answered with an id-null -32600, not treated as a notification."""
        response = dispatch({"jsonrpc": "2.0", "method": 42})
        self.assertIsNotNone(response)
        self.assertEqual(response["error"]["code"], server.INVALID_REQUEST)
        self.assertIsNone(response["id"])

    def test_malformed_jsonrpc_without_id_gets_id_null_error(self):
        response = dispatch({"jsonrpc": "1.0", "method": "ping"})
        self.assertIsNotNone(response)
        self.assertEqual(response["error"]["code"], server.INVALID_REQUEST)
        self.assertIsNone(response["id"])


def _random_json_value(rng, depth=0):
    """A random JSON value, biased toward the shapes that break parsers."""
    choices = ["null", "bool", "int", "float", "string", "unicode"]
    if depth < 3:
        choices += ["array", "object"]
    kind = rng.choice(choices)
    if kind == "null":
        return None
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "int":
        return rng.choice([0, -1, 1, 2**31, -(2**63), 999999999999])
    if kind == "float":
        return rng.choice([0.0, -0.5, 1e308, 1e-308])
    if kind == "string":
        return "".join(rng.choices(string.printable, k=rng.randint(0, 40)))
    if kind == "unicode":
        return "".join(chr(rng.randint(1, 0x10FFFF)) for _ in range(rng.randint(0, 12)))
    if kind == "array":
        return [_random_json_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {
        "".join(rng.choices(string.ascii_letters, k=rng.randint(1, 8))): _random_json_value(rng, depth + 1)
        for _ in range(rng.randint(0, 4))
    }


def _random_frame(rng):
    """Either a mutation of a valid frame or arbitrary JSON junk."""
    if rng.random() < 0.5:
        frame = {
            "jsonrpc": rng.choice(["2.0", "2.0", "2.0", "1.0", 2.0, None]),
            "method": rng.choice(
                [
                    "initialize",
                    "tools/list",
                    "tools/call",
                    "ping",
                    "notifications/initialized",
                    "",
                    "no/such/method",
                    42,
                    None,
                    ["tools/list"],
                ]
            ),
        }
        if rng.random() < 0.8:
            frame["id"] = rng.choice([1, 0, -5, "abc", None, 2**53, 1.5])
        if rng.random() < 0.8:
            frame["params"] = rng.choice(
                [
                    {},
                    {"name": "scan_code_for_violations", "arguments": {"code": "x = 1"}},
                    {"name": "get_constitution", "arguments": {"section": "invariants"}},
                    {"name": 42, "arguments": []},
                    {"arguments": {"code": "x"}},
                    _random_json_value(rng),
                ]
            )
        return frame
    return _random_json_value(rng)


class TestDispatchFuzzInvariants(unittest.TestCase):
    """The three transport invariants hold for every generated frame."""

    def test_fuzzed_frames_never_break_the_invariants(self):
        rng = random.Random(FUZZ_SEED)
        for index in range(MUTATION_COUNT):
            frame = _random_frame(rng)
            with self.subTest(index=index, frame=repr(frame)[:120]):
                # Internal errors print a diagnostic to stderr by design;
                # keep fuzz output readable.
                with redirect_stderr(io.StringIO()):
                    response = dispatch(frame)  # invariant 1: never raises
                well_formed = (
                    isinstance(frame, dict)
                    and frame.get("jsonrpc") == "2.0"
                    and isinstance(frame.get("method"), str)
                )
                if well_formed and "id" not in frame:
                    # Invariant 3: well-formed notifications get silence.
                    self.assertIsNone(response)
                else:
                    # Everything else - requests and malformed objects
                    # alike - gets exactly one response.
                    self.assertIsNotNone(response)
                if response is not None:
                    # Invariant 2: well-formed JSON-RPC, serialisable,
                    # exactly one of result/error, id echoed (null when
                    # the frame had none to echo).
                    self.assertEqual(response["jsonrpc"], "2.0")
                    self.assertIn("id", response)
                    self.assertEqual(
                        ("result" in response) + ("error" in response),
                        1,
                        f"response must carry exactly one of result/error: {response}",
                    )
                    json.dumps(response)
                    expected_id = frame.get("id") if isinstance(frame, dict) else None
                    self.assertEqual(response["id"], expected_id)


class TestServeTransportFuzz(unittest.TestCase):
    """The line loop survives byte-level garbage and keeps serving."""

    def _serve(self, text, debug=False):
        stdout = io.StringIO()
        with redirect_stderr(io.StringIO()) as stderr:
            server.serve(io.StringIO(text), stdout, CONSTITUTION, debug=debug)
        return stdout.getvalue(), stderr.getvalue()

    def test_garbage_lines_then_ping_still_answers(self):
        rng = random.Random(FUZZ_SEED)
        garbage = [
            "".join(rng.choices(string.printable.replace("\n", ""), k=rng.randint(1, 80))) for _ in range(200)
        ]
        ping = json.dumps({"jsonrpc": "2.0", "id": 77, "method": "ping"})
        out, _ = self._serve("\n".join([*garbage, ping]) + "\n")
        lines = [json.loads(line) for line in out.splitlines()]
        self.assertTrue(lines, "transport went mute")
        for line in lines:
            self.assertEqual(line["jsonrpc"], "2.0")
        final = lines[-1]
        self.assertEqual(final["id"], 77)
        self.assertEqual(final["result"], {})

    def test_stdout_carries_protocol_frames_only(self):
        """Every stdout line parses as JSON even under garbage input - the
        transport purity rule that keeps MCP clients from desyncing."""
        rng = random.Random(FUZZ_SEED + 1)
        lines = []
        for _ in range(120):
            frame = _random_frame(rng)
            try:
                lines.append(json.dumps(frame))
            except (TypeError, ValueError):
                continue
        out, _ = self._serve("\n".join(lines) + "\n", debug=True)
        for line in out.splitlines():
            json.loads(line)

    def test_debug_lines_carry_sizes_never_payloads(self):
        secret = "MY_EXTREMELY_SECRET_FUNCTION_BODY"
        call = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "scan_code_for_violations",
                    "arguments": {"code": f"def f():\n    return '{secret}'\n"},
                },
            }
        )
        out, err = self._serve(call + "\n", debug=True)
        self.assertIn("tool=scan_code_for_violations", err)
        self.assertIn("frame_chars=", err)
        self.assertIn("elapsed_ms=", err)
        self.assertNotIn(secret, err, "debug diagnostics leaked scanned payload content")
        # And debug never contaminates the protocol stream.
        for line in out.splitlines():
            json.loads(line)

    def test_debug_off_writes_no_stderr(self):
        ping = json.dumps({"jsonrpc": "2.0", "id": 6, "method": "ping"})
        _, err = self._serve(ping + "\n", debug=False)
        self.assertEqual(err, "")


class TestDebugOptIn(unittest.TestCase):
    """The flag and the env var both enable diagnostics; default is off."""

    def test_flag_enables(self):
        self.assertTrue(server._debug_enabled(["--debug"], {}))

    def test_env_var_enables(self):
        for value in ("1", "true", "YES", " on "):
            with self.subTest(value=value):
                self.assertTrue(server._debug_enabled([], {"PERSONA_CONSTITUTION_DEBUG": value}))

    def test_default_is_off(self):
        self.assertFalse(server._debug_enabled([], {}))
        self.assertFalse(server._debug_enabled([], {"PERSONA_CONSTITUTION_DEBUG": "0"}))


if __name__ == "__main__":
    unittest.main()
