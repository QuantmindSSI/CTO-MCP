---
description: >-
  Two-factor review of the currently staged changes before committing:
  factor 1 runs the deterministic staged gate (persona-pr-review --staged),
  factor 2 applies agent judgement with business-logic test research.
agent: pr-review
---

Review the changes currently staged in this repository (the pre-commit view).
Extra focus requested by the user (may be empty): $ARGUMENTS

Execute both factors:

1. Factor 1 - deterministic staged gate. Run:
   `persona-pr-review --staged --json`
   (fall back to `python -m persona_constitution.review.cli --staged --json`
   if the console script is not on PATH). Parse the JSON verdict. Its FAIL is
   final: report the findings file:line and stop with a "do not commit"
   conclusion; do not attempt to argue the engine down.

2. Factor 0/2 - policy and business-logic test research, per your agent
   protocol: read `.persona-review.json` (business_logic hints), inventory
   the project's test layers (unit / integration / e2e / smoke / regression),
   and map every staged production symbol to its covering tests with
   `git grep <symbol> -- <test paths>`. Note that the staged diff comes from
   `git diff --cached` and staged file contents from `git show :0:<path>` -
   judge the index, not the worktree.

3. Adjudicate every warning from factor 1 (Po10 metrics, empty loops,
   identical branches, constant conditions, C-03 test presence) with one
   sentence each: dismissed-with-reason or upheld-as-required-change.

4. Apply gates G1-G5 to the staged logic and name any missing test layer
   with the concrete cases it must cover (happy path, boundaries, error
   paths, business rule).

Conclude with exactly one of:
- "COMMIT: gate PASS, judgement clean" (optionally with advisory notes), or
- "DO NOT COMMIT" followed by the ordered list of required fixes, each with
  file:line and the gate/dimension/finding it violates.
