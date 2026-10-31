---
name: test-driven-development
description: "Use when tests clarify a change or prevent a regression."
version: 1.2.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [testing, tdd, development, quality, red-green-refactor]
    related_skills: [systematic-debugging, subagent-driven-development]
---

# Test-Driven Development

Use tests to make the intended behavior concrete and catch regressions. Test-first is a useful design technique, not a reason to discard working code or turn every edit into a testing project.

## When to Use

- A bug needs a durable regression check.
- New behavior or a shared contract benefits from an executable example.
- Refactoring needs evidence that observable behavior stays intact.
- The user or project explicitly requires a test-first workflow.

Choose the effort by the behavioral impact and risk. Inspection can suffice for a trivial edit with no meaningful effect on behavior or contracts. Follow actual project gates; choosing an ordinary implementation/test order does not itself need a separate approval.

## Procedure

1. **Define the observable contract.** Identify the affected caller, relevant existing coverage and a representative failure or desired outcome. Reuse the project's test fixtures and runner.
2. **Establish a useful failure signal.** When test-first helps, add the smallest check that fails for the intended reason, not a typo, missing dependency or broken mock. A current test, replay, command or captured failing case may already provide that evidence.
3. **Implement the coherent change.** Keep useful existing implementation. If code already exists, add coverage around it; a previous revision or isolated control can establish that the test detects the original defect. Work in small understandable slices, or group closely related cases when that is clearer and cheaper than serial micro-cycles.
4. **Check the result.** Run the affected checks through `terminal`, inspect failures and correct the implementation or an incorrect test according to the actual contract. Expand to callers, integration or the full suite when dependencies, risk or project requirements justify it. Reuse passing evidence whose relevant inputs are unchanged.
5. **Simplify where useful and finish.** Keep the solution general over valid inputs, not hardcoded to the observed examples. Further tests or review should address a concrete remaining uncertainty, not merely repeat success.

## Designing Useful Tests

- Exercise input → real production action → observable result. Use mocks to control external boundaries, time or failures without replacing the behavior being tested.
- For a regression, show how the old behavior fails and the repaired behavior succeeds when practical. A test that passes immediately can still be valid existing-behavior coverage; label what it proves.
- Select representative normal, boundary and failure cases for the changed contract. Avoid asserting private names, statement order or implementation-shaped snapshots unless they are themselves a real compatibility contract.
- Test the actual rule across useful inputs. A function that returns the expected answer for one example may still violate the general contract.
- Keep new fixtures and helpers proportional. Prefer an existing runner or a small direct check over a new framework for a one-off change.

## Hermes Tools

Use `read_file` and `search_files` for the relevant implementation, callers and tests. Use `patch`/`write_file` for edits and `terminal` for the repository's declared test command. For Hermes itself, use `scripts/run_tests.sh` with the affected paths and an isolated home.

Delegate independent work only when it helps. Give a child the behavior, scope, existing evidence and required project gates; a fixed reviewer count or a fresh full-suite run per child is not part of TDD.

## Pitfalls

- A red result caused by setup failure is not evidence of the product defect.
- A green test against a mock or a single hardcoded answer may not exercise the contract.
- An existing test can be wrong or obsolete; resolve that against the requested behavior rather than blindly changing production code to satisfy it.
- Destructive resets, deleting implementation to recreate chronology and repeated unrelated suites add no regression evidence.

## Verification

Report the behavior covered, the actual command and result, and any meaningful limitation or inherited failure. Distinguish automated coverage, a manual observation and an unexecuted check. Done means the requested change has adequate support, not that a ritual was completed.
