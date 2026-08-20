"""Test-collection policy for mutation-testing runs.

mutmut executes the suite inside its `mutants/` sandbox with
MUTANT_UNDER_TEST set. Two groups of tests assert properties of the real
repository, not of the code under mutation, so running them there is
noise at best and a false kill at worst:

  - test_release_integrity.py checks the actual checkout's version
    plumbing (pyproject.toml, package metadata, CHANGELOG discipline);
    the sandbox is not a release artefact.
  - test_scan_budget.py measures wall-clock behaviour; under mutation
    trampolines the stopwatch measures the instrumentation, and its
    megabyte corpus multiplied by hundreds of mutants would consume the
    entire nightly budget.
  - The subprocess-spawning end-to-end tests (test_smoke.py and the
    stdio transport class) launch the server as a child process from the
    real checkout; inside the sandbox they exercise packaging plumbing,
    not the mutated logic, and every dispatch path they cover is also
    covered in-process by the conformance and dispatcher suites, which
    do run against mutants.

Everything else - the scanner detection contracts, the protocol
invariants, the review engine - is exactly what mutation testing is for
and runs unfiltered. Plain test runs (no MUTANT_UNDER_TEST) collect
everything; this file changes nothing outside the mutation sandbox.
"""

import os

import pytest

_SKIP_FILES_UNDER_MUTATION = ("test_release_integrity.py", "test_scan_budget.py", "test_smoke.py")
_SKIP_CLASSES_UNDER_MUTATION = ("TestStdioTransport",)


def pytest_collection_modifyitems(config, items):  # noqa: ARG001 - pytest hook signature
    if os.environ.get("MUTANT_UNDER_TEST") is None:
        return
    marker = pytest.mark.skip(reason="asserts real-repository properties; not meaningful under mutation")
    for item in items:
        in_skipped_file = any(name in str(item.fspath) for name in _SKIP_FILES_UNDER_MUTATION)
        in_skipped_class = item.cls is not None and item.cls.__name__ in _SKIP_CLASSES_UNDER_MUTATION
        if in_skipped_file or in_skipped_class:
            item.add_marker(marker)
