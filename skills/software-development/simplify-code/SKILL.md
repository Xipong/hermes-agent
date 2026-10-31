---
name: simplify-code
description: "Use when simplifying code without changing its intent."
version: 1.2.0
author: Hermes Agent (inspired by Claude Code /simplify)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, cleanup, refactor, delegation, subagent, parallel, simplify]
    related_skills: [requesting-code-review, test-driven-development]
---

# Simplify Code

Improve the requested code's clarity and maintenance cost while preserving its intended behavior. Prefer deletion, existing abstractions and a small coherent change over extra layers or a fixed reviewer workflow.

## When to Use

Use when the user requests simplification, cleanup or a focused refactor. Honor a named file, commit, staged diff or requested focus. A read-only/dry-run request produces findings without applying them; ordinary implementation does not automatically need a separate cleanup pass.

## Establish Scope

Inspect the relevant changes with `terminal`: working/staged diff, the selected commit or the branch's actual base. If there is no diff, use the explicitly named files; if no target is identifiable, ask for it. Preserve unrelated edits and public behavior.

## Useful Review Angles

Select the angles relevant to the code rather than filling a reviewer quota:

- **Reuse:** duplication or hand-rolled behavior already provided by an existing helper. Name the real replacement and its consumers.
- **Clarity:** unnecessary state, layers, parameter sprawl, nested conditionals and comments that repeat obvious code. Introduce an abstraction only if it makes the existing task simpler.
- **Efficiency:** redundant I/O/computation, avoidable serialization, hot-path work, unbounded resources or retained context. Explain a concrete cost rather than guessing from style.
- **Root cause:** a workaround at one call site may belong in a shared owner. Check its purpose and siblings before removing it; compatibility, staged migration and isolation can be deliberate boundaries.

Work directly for a small target. Delegate genuinely independent areas or questions when that reduces time or context cost; give each lane the relevant contract, code and exclusions. Four perspectives are not a requirement for four agents or four complete copies of the diff. Consult history when the current purpose is unclear, not as a ritual for each line.

## Apply Useful Changes

Deduplicate findings and discard weak suggestions. Prioritize correctness, the user's intent, then clarity and actual cost. A useful finding identifies a location, the mechanism, the benefit and the affected contract.

Make the smallest coherent simplification within the requested authority. Public APIs, wire/config keys, concurrency, ownership and error behavior deserve checks at their consumers. If a deeper change exceeds scope, explain that concrete choice rather than expanding the task. If a real correctness bug appears, report or fix it according to the granted scope rather than hiding it as a stylistic cleanup.

Group related safe edits when convenient. Select checks by meaningful effects and risk: inspection may suffice for a trivial cleanup; changed behavior or contracts warrant targeted execution and required project gates. Reuse valid evidence and rerun only checks invalidated by the edits. A fixed test run after every file or a full suite after every cleanup is not the goal.

## Pitfalls

- Dynamic imports, reflection, callbacks and string registries can make code appear unused. Trace the real consumers before removing it.
- A helper, cache or defensive branch can carry a compatibility or ownership contract. Understand its purpose before deleting it.
- Replacing small duplication with a new generic framework may increase reader load.
- Micro-performance claims need a real workload or a clear mechanism; fewer lines are not automatically faster.
- Repeated review rounds can become more expensive than the original complexity. Finish when the useful scoped changes are supported.

## Verification

Report the applied simplifications, relevant checks and important items intentionally left alone. For a dry run, report actionable findings and their scope. Preserve user work, secret handling and repository requirements; commit or publish only when authorized.
