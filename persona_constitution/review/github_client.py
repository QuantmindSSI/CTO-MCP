"""Minimal GitHub REST client for the PR reviewer. Stdlib only.

Speaks exactly the four endpoints the reviewer needs: PR metadata, PR diff,
head-version file contents, and review creation. Every request is bounded
(timeout, bounded retries with backoff on transient statuses) and every
failure path raises GitHubError with the status and the API's message - no
silent degradation.

The token is read by the caller and passed in; this module never touches the
environment and never logs the token.
"""

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API_URL = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 30
# Bounded retry policy (Power of 10 rule 2): transient statuses only.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
_RETRYABLE_STATUSES = frozenset({500, 502, 503, 504})

# The contents API refuses blobs over 1 MiB via the JSON media type.
MAX_CONTENT_BYTES = 1024 * 1024


class GitHubError(RuntimeError):
    """A GitHub API call failed definitively (after bounded retries)."""

    def __init__(self, status, message):
        super().__init__(f"GitHub API error {status}: {message}")
        self.status = status


class GitHubClient:
    """Authenticated client scoped to one API base URL."""

    def __init__(self, token, api_url=DEFAULT_API_URL):
        assert token, "a GitHub token is required (GITHUB_TOKEN)"
        self._token = token
        self._api_url = api_url.rstrip("/")

    def _request(self, method, path, body=None, accept="application/vnd.github+json"):
        """Perform one bounded-retry request; returns (status, raw bytes)."""
        url = self._api_url + path
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        last_error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            request = urllib.request.Request(url, data=payload, method=method)
            request.add_header("Accept", accept)
            request.add_header("Authorization", f"Bearer {self._token}")
            request.add_header("X-GitHub-Api-Version", "2022-11-28")
            request.add_header("User-Agent", "persona-pr-review")
            if payload is not None:
                request.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")[:500]
                if error.code in _RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                    last_error = GitHubError(error.code, detail)
                    time.sleep(BACKOFF_SECONDS * attempt)
                    continue
                raise GitHubError(error.code, detail) from error
            except urllib.error.URLError as error:
                if attempt < MAX_ATTEMPTS:
                    last_error = GitHubError(0, str(error.reason))
                    time.sleep(BACKOFF_SECONDS * attempt)
                    continue
                raise GitHubError(0, str(error.reason)) from error
        raise last_error  # unreachable while MAX_ATTEMPTS >= 1, kept for totality

    def _request_json(self, method, path, body=None):
        _, raw = self._request(method, path, body=body)
        return json.loads(raw.decode("utf-8"))

    def get_pull_request(self, owner, repo, number):
        """PR metadata; head sha lives at ["head"]["sha"]."""
        return self._request_json("GET", f"/repos/{owner}/{repo}/pulls/{number}")

    def get_pull_request_diff(self, owner, repo, number):
        """The PR's unified diff via the diff media type."""
        _, raw = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}",
            accept="application/vnd.github.v3.diff",
        )
        return raw.decode("utf-8", errors="replace")

    def get_file_content(self, owner, repo, path, ref):
        """Full text of a file at a ref, or None when unavailable.

        None (rather than an exception) for the three expected cases a review
        must tolerate per-file: absent path, non-file entry, and blobs over
        the contents-API size limit. Real API failures still raise.
        """
        quoted = urllib.parse.quote(path)
        try:
            data = self._request_json(
                "GET", f"/repos/{owner}/{repo}/contents/{quoted}?ref={urllib.parse.quote(ref)}"
            )
        except GitHubError as error:
            if error.status == 404:
                return None
            raise
        if not isinstance(data, dict) or data.get("type") != "file":
            return None
        if data.get("size", 0) > MAX_CONTENT_BYTES or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")

    def post_review(self, owner, repo, number, payload):
        """Create the PR review; returns the API's review object."""
        return self._request_json("POST", f"/repos/{owner}/{repo}/pulls/{number}/reviews", body=payload)
