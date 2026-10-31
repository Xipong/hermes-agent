---
name: systematic-debugging
description: "Use when diagnosing a failure and repairing its cause."
version: 1.2.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, troubleshooting, problem-solving, root-cause, investigation]
    related_skills: [test-driven-development, subagent-driven-development]
---

# Systematic Debugging

Diagnose the reported failure with evidence and make the smallest coherent repair. Use enough investigation to distinguish plausible causes; the method should shorten the path to the fix rather than become a four-phase ceremony.

## When to Use

Use for unexpected behavior, failing tests, crashes, performance regressions, build failures and integration defects. An obvious error may need one direct check; an intermittent or cross-component failure may need a deeper investigation.

## Procedure

1. **Establish the symptom.** Read the relevant error, failing assertion, log or state. Identify the expected behavior and the actual execution path. Reuse existing failure evidence instead of rebuilding a reproduction from scratch.
2. **Choose an informative observation.** A focused test, debugger inspection, CLI command, trace replay or request can distinguish the likely causes. Prefer a fast repeatable repro where practical. If reproducing is expensive, unsafe or unreliable, use the available evidence and state the remaining uncertainty rather than building an unrelated harness.
3. **Trace the relevant owner and boundaries.** Inspect the data, callers, configuration and recent changes that can explain this symptom. Compare with a working path or pinned baseline when that helps. Instrument only the unresolved boundary; reading every reference or logging every component is not a prerequisite.
4. **Test the best explanation.** Make a prediction and choose a cheap observation that could disprove it. Use additional hypotheses when the evidence is ambiguous, not to fill a quota. Keep experimental changes distinguishable so their effect can be attributed.
5. **Repair and verify the affected behavior.** Apply the cause-level correction and inspect sibling callers when they share that cause. Add a regression test when it is useful and practical; an existing check or direct execution may already cover the change. Run broader checks when the affected contracts, risk or project requirements justify them.

These activities can overlap. A user-authorized containment step may precede a complete diagnosis; distinguish mitigation from a demonstrated root-cause fix. Preserve scope, permissions, production data and unrelated work.

## When Progress Stalls

Use new failures to revise the hypothesis. Repeatedly applying the same unsuccessful fix is not progress, but an arbitrary third attempt does not prove the architecture is wrong. Reconsider coupling, assumptions or architecture when the evidence points there. Ask the user when the next decision genuinely changes scope, authority or cost, or required information is unavailable.

For intermittent bugs, increase observation or reproduction only enough to distinguish the suspected race or state transition. Choose stress, timing controls or repetitions for that hypothesis rather than automatically running a hundred attempts.

## Tools

- `read_file` and `search_files`: relevant source, error producers and callers.
- `terminal`: the project's runner, debugger, captured replay and Git history. In Hermes, use `scripts/run_tests.sh` for tests.
- `web_search`/`web_extract`: current documentation when an external contract is in question.
- Native delegation: independent components or reasoning-heavy questions when isolation helps. Provide the symptom, relevant evidence, allowed actions and expected finding; keep direct fixes direct.

## Pitfalls

- A setup error or incomplete fixture can mimic a product failure.
- A green build does not establish that the user's failing path was exercised.
- A speculative fix should not be presented as a confirmed cause.
- A failing test may encode an obsolete expectation; resolve it against the real contract.
- Temporary instrumentation can expose secrets or swamp logs. Keep it scoped and remove disposable diagnostics when they are no longer useful.

## Verification

Observe the original boundary after the repair, reuse unchanged passing evidence, and report what is fixed versus what remains uncertain. Separate inherited failures from new regressions. Finish when the requested behavior has adequate support; further investigation needs a concrete unresolved question.
