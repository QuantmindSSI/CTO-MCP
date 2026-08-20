# Security Policy

This project runs inside other people's CI pipelines and code-review
loops, scanning bytes that pull-request authors control. That makes two
report classes security-relevant here that most projects would file as
ordinary bugs:

1. **Resource-exhaustion inputs.** Any input at or under the documented
   size caps (`MAX_SCAN_BYTES`, `MAX_REVIEW_DIFF_CHARS`,
   `MAX_REVIEW_FILES_TOTAL_CHARS`, `MAX_MESSAGE_CHARS`) that pushes the
   scanner or server into hang-class runtime or a crash. These deny
   service to every consumer's pipeline. Two of this class were found and
   fixed by the adversarial suite in `tests/test_scan_budget.py`; more are
   assumed to exist.
2. **Deliberate detection bypasses.** A construction that smuggles a
   stub, placeholder, or deferral past `scan_code_for_violations` or
   `review_patch` defeats the gate this software exists to be. Bypasses
   are treated as vulnerabilities, not false negatives.

Anything in the classic classes (code execution via crafted input,
token/secret exposure in the PR-review path, privilege escalation through
the composite action) is of course also in scope.

## Reporting

Report privately via GitHub's security advisories:
**Security tab → Report a vulnerability** on
https://github.com/QuantmindSSI/CTO-MCP - or, if that is unavailable to
you, open an issue saying only that you have a security report and a
maintainer will open a private channel. Do not put reproduction details
in a public issue.

Expectations you can hold us to:

| Stage | Target |
|---|---|
| Acknowledgement | 7 days |
| Assessment (in scope / not) | 14 days |
| Fix or public advisory with mitigation | 90 days |

## Supported versions

The latest release line only. There is no backporting; upgrades are the
security mechanism, which is why releases are attested and the version is
single-sourced.
