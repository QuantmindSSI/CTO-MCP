"""Shared review policy: .persona-review.json at the repository root.

One config file drives both factors of the review gate - the pre-commit
staged scan and the PR review - plus the agent layer, so a rule can never be
enforced at one gate and forgotten at the other.

Schema (all keys optional, unknown keys rejected loudly):

    {
      "exclude": ["tests/*", "vendor/*"],
      "fail_on_review": false,
      "require_tests": "warn",            // "off" | "warn" | "fail"
      "min_test_trigger_lines": 5,        // added prod lines before C-03 applies
      "test_globs": ["qa/*", "*.feature"],// project-specific test locations
      "business_logic": {                  // consumed by the AGENT layer, not
        "description": "...",              // the deterministic engine: hints
        "critical_paths": ["billing/*"],   // for business-logic test research
        "test_commands": ["make test-billing"]
      }
    }

Config loading is strict: a malformed file raises ValueError instead of
silently degrading the gate - a typo in "require_tests" must not disable
test enforcement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

CONFIG_FILENAME = ".persona-review.json"

REQUIRE_TESTS_MODES = ("off", "warn", "fail")

_DEFAULTS: dict[str, Any] = {
    "exclude": [],
    "fail_on_review": False,
    "require_tests": "warn",
    "min_test_trigger_lines": 5,
    "test_globs": [],
    "business_logic": {},
}


def default_config() -> dict[str, Any]:
    """A fresh copy of the default policy."""
    return {key: (list(value) if isinstance(value, list) else value) for key, value in _DEFAULTS.items()}


def _check_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _check_require_tests(value: Any) -> bool:
    return value in REQUIRE_TESTS_MODES


def _check_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# key -> (predicate, requirement text used in the error message).
_VALIDATORS: dict[str, tuple[Callable[[Any], bool], str]] = {
    "exclude": (_check_string_list, "an array of strings"),
    "test_globs": (_check_string_list, "an array of strings"),
    "fail_on_review": (lambda value: isinstance(value, bool), "a boolean"),
    "require_tests": (_check_require_tests, f"one of {REQUIRE_TESTS_MODES}"),
    "min_test_trigger_lines": (_check_non_negative_int, "an integer >= 0"),
    "business_logic": (lambda value: isinstance(value, dict), "an object"),
}


def _validate(raw: Any) -> dict[str, Any]:
    """Validate raw JSON against the schema; returns a complete config dict."""
    if not isinstance(raw, dict):
        raise ValueError(f"{CONFIG_FILENAME}: top level must be a JSON object")
    unknown = set(raw) - set(_DEFAULTS)
    if unknown:
        raise ValueError(
            f"{CONFIG_FILENAME}: unknown key(s) {sorted(unknown)}; valid keys: {sorted(_DEFAULTS)}"
        )
    config = default_config()
    for key, value in raw.items():
        predicate, requirement = _VALIDATORS[key]
        if not predicate(value):
            raise ValueError(f"{CONFIG_FILENAME}: '{key}' must be {requirement}")
        config[key] = value
    return config


def load_config(root: str | Path) -> dict[str, Any]:
    """Load the policy for a repository root.

    Args:
        root: Directory containing (or not) a .persona-review.json.

    Returns:
        A complete config dict - defaults when the file is absent.

    Raises:
        ValueError: The file exists but is not valid JSON or violates the
            schema. Loud by design: a broken policy must stop the gate, not
            silently weaken it.
    """
    path = Path(root) / CONFIG_FILENAME
    if not path.is_file():
        return default_config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{CONFIG_FILENAME}: invalid JSON: {error}") from error
    return _validate(raw)
