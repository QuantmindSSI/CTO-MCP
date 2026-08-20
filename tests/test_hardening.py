#!/usr/bin/env python3
"""Trust-boundary hardening tests.

Covers the bounds and validation added for the enterprise-hardening pass:

  - initialize echoes only protocol versions this server implements,
    and offers its latest for unknown or malformed requests;
  - the stdio transport rejects frames over MAX_MESSAGE_CHARS instead of
    parsing them;
  - review_patch rejects oversized diffs and files maps with instructions
    rather than degrading;
  - GitHubClient refuses a missing token with an exception that survives
    `python -O` (a plain assert would be stripped).

Run: python3 -m unittest discover -s tests -v
Dependencies: Python 3.9+ standard library only.
"""

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from persona_constitution import server  # noqa: E402 - path must be set before import.
from persona_constitution.review.github_client import GitHubClient  # noqa: E402


def _initialize_response(protocol_version_value, include_field=True):
    """Dispatch one initialize request; return the result object."""
    params = {"capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}
    if include_field:
        params["protocolVersion"] = protocol_version_value
    response = server.dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params},
        "unused constitution text",
    )
    return response["result"]


class TestProtocolVersionNegotiation(unittest.TestCase):
    """The handshake must never parrot a version this server does not speak."""

    def test_each_supported_version_is_echoed(self):
        for version in sorted(server.SUPPORTED_PROTOCOL_VERSIONS):
            result = _initialize_response(version)
            self.assertEqual(result["protocolVersion"], version)

    def test_unknown_version_gets_latest_supported(self):
        result = _initialize_response("1999-01-01")
        self.assertEqual(result["protocolVersion"], server.PROTOCOL_VERSION)

    def test_non_string_version_gets_latest_supported(self):
        result = _initialize_response(42)
        self.assertEqual(result["protocolVersion"], server.PROTOCOL_VERSION)

    def test_missing_version_gets_latest_supported(self):
        result = _initialize_response(None, include_field=False)
        self.assertEqual(result["protocolVersion"], server.PROTOCOL_VERSION)

    def test_latest_is_itself_supported(self):
        """PROTOCOL_VERSION must be a member of the supported set, or the
        server would offer a version it then refuses to recognise."""
        self.assertIn(server.PROTOCOL_VERSION, server.SUPPORTED_PROTOCOL_VERSIONS)


class TestTransportFrameLimit(unittest.TestCase):
    """serve() must reject an oversized frame, respond with a JSON-RPC error,
    and keep serving subsequent well-formed frames."""

    def _serve(self, stdin_text, frame_limit):
        stdout = io.StringIO()
        with mock.patch.object(server, "MAX_MESSAGE_CHARS", frame_limit):
            server.serve(io.StringIO(stdin_text), stdout, "unused constitution text")
        return [json.loads(line) for line in stdout.getvalue().splitlines()]

    def test_oversized_frame_is_rejected_not_parsed(self):
        oversized = '{"jsonrpc":"2.0","id":1,"method":"ping","padding":"' + "x" * 200 + '"}\n'
        ping = '{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
        responses = self._serve(oversized + ping, frame_limit=100)

        self.assertEqual(len(responses), 2)
        self.assertIn("error", responses[0])
        self.assertEqual(responses[0]["error"]["code"], server.INVALID_REQUEST)
        self.assertIn("frame limit", responses[0]["error"]["message"])
        self.assertIsNone(responses[0]["id"])
        # The transport survived and answered the next frame normally.
        self.assertEqual(responses[1]["id"], 2)
        self.assertIn("result", responses[1])

    def test_frame_at_the_limit_is_served(self):
        ping = '{"jsonrpc":"2.0","id":3,"method":"ping"}\n'
        responses = self._serve(ping, frame_limit=len(ping))
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 3)
        self.assertIn("result", responses[0])

    def test_shipped_limit_covers_maximum_review_payload(self):
        """The frame ceiling must exceed the largest legitimate tool payload
        (diff cap plus files cap) with headroom for JSON escaping."""
        largest_payload = server.MAX_REVIEW_DIFF_CHARS + server.MAX_REVIEW_FILES_TOTAL_CHARS
        self.assertGreater(server.MAX_MESSAGE_CHARS, largest_payload)


class TestReviewPayloadBounds(unittest.TestCase):
    """review_patch inputs are bounded and fail loudly with instructions."""

    def test_oversized_diff_is_rejected(self):
        with mock.patch.object(server, "MAX_REVIEW_DIFF_CHARS", 50), self.assertRaises(ValueError) as ctx:
            server.tool_review_patch(None, {"diff": "+" + "x" * 100})
        self.assertIn("limit", str(ctx.exception))

    def test_oversized_files_map_is_rejected(self):
        diff = "diff --git a/f.py b/f.py\n+pass\n"
        files = {"f.py": "y" * 100}
        with (
            mock.patch.object(server, "MAX_REVIEW_FILES_TOTAL_CHARS", 50),
            self.assertRaises(ValueError) as ctx,
        ):
            server.tool_review_patch(None, {"diff": diff, "files": files})
        self.assertIn("fragment scanning", str(ctx.exception))

    def test_files_total_is_summed_across_entries(self):
        diff = "diff --git a/f.py b/f.py\n+pass\n"
        files = {"a.py": "y" * 30, "b.py": "y" * 30}
        with mock.patch.object(server, "MAX_REVIEW_FILES_TOTAL_CHARS", 50), self.assertRaises(ValueError):
            server.tool_review_patch(None, {"diff": diff, "files": files})

    def test_bounded_payload_still_reviewed(self):
        diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+x = 1\n"
        result = json.loads(server.tool_review_patch(None, {"diff": diff}))
        self.assertIn("verdict", result)


class TestGitHubClientTokenValidation(unittest.TestCase):
    """Auth-input validation must be a real exception, not an assert."""

    def test_empty_token_raises_value_error(self):
        with self.assertRaises(ValueError):
            GitHubClient("")

    def test_none_token_raises_value_error(self):
        with self.assertRaises(ValueError):
            GitHubClient(None)

    def test_valid_token_constructs(self):
        client = GitHubClient("ghs_dummy_token_for_construction_only")
        self.assertIsInstance(client, GitHubClient)


if __name__ == "__main__":
    unittest.main()
