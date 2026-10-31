---
title: "Hermes Agent Skill Authoring — Use when authoring focused, portable Hermes skills"
sidebar_label: "Hermes Agent Skill Authoring"
description: "Use when authoring focused, portable Hermes skills"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Hermes Agent Skill Authoring

Use when authoring focused, portable Hermes skills.

## Skill metadata

| | |
|---|---|
| Source | Optional — install with `hermes skills install official/software-development/hermes-agent-skill-authoring` |
| Path | `optional-skills/software-development/hermes-agent-skill-authoring` |
| Version | `2.1.0` |
| Author | Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `skills`, `authoring`, `hermes-agent`, `conventions`, `skill-md` |
| Related skills | [`requesting-code-review`](../../bundled/software-development/software-development-requesting-code-review.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Authoring Hermes Skills

Write a focused procedure that gives a capable agent the goal, relevant context, working tools and real constraints. Explain dependencies and fragile contracts; leave ordinary implementation choices open. Improve completed-task quality, not compliance with a rigid itinerary.

## When to Use

Use for an existing or new skill in the Hermes repository. For personal skills, use `skill_manage` in the active profile. Read the target area's current `AGENTS.md` and applicable authoring standards; they own repository-specific requirements.

## Choose the Owner and Tier

- User-local skills live under the active Hermes home's `skills/`; `skill_manage` owns normal edits there.
- Bundled source lives in `skills/<category>/<name>/SKILL.md`.
- Optional source lives in `optional-skills/<category>/<name>/SKILL.md`; heavier or niche capabilities normally belong here.
- `skill_manage(action='create')` targets user storage, not a repository branch. Use `write_file`/`patch` for in-repo source and include it in the authorized commit.

Extend an existing coherent skill when it owns the capability. A small router is useful for several genuinely distinct workflows or optional references; an empty index duplicating sibling descriptions is not. Preserve package ownership, attribution and licenses, and keep local lessons separate from upstream-owned packages unless the user authorized those edits.

## Frontmatter and Tool Contracts

For Hermes repository skills, retain the fields required by current authoring checks:

```yaml
---
name: example-skill
description: "Use when performing the specific recurring workflow."
version: 0.1.0
author: Human Contributor (github-handle), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Relevant, Searchable, Terms]
    related_skills: []
---
```

- Start at byte zero with `---`, close the YAML mapping, then provide a non-empty body.
- Use a lowercase/hyphen name, at most 64 characters, matching the directory. Keep a repository description within **60 characters**, ending with a period and stating when the capability applies. The validator's broader **1024-character** ceiling is not the repository's description standard. Quote YAML scalars containing a colon.
- Preserve author credit; for new contributions, credit the real human contributor rather than inventing an identity. Related skill names resolve in the same submitted repository tree.
- Declare platforms from the actual commands and scripts. Cross-platform Python/CLI code can support all three OSes; POSIX-specific APIs, shell behavior or system commands need appropriate gating or a working portable implementation.
- Name the available Hermes tools, expected MCP server or actual third-party CLI. Tool schemas and current documentation own exact parameters. Keep commands executable, secrets out of examples and paths portable; public source should not depend on the author's home directory.

## Write the Useful Depth

A concise introduction and clear trigger are usually enough before the procedure. Include setup, commands, pitfalls and evidence only where they help this workflow. Order steps when a real dependency requires it, not to impose a universal sequence on every task.

Put branch-specific depth in topical `references/`, reusable starter files in `templates/`, and worthwhile deterministic helpers in `scripts/`. Link the useful entry point from the main skill. Keep the root small enough to read comfortably; the enforced full-content ceiling is **100,000 characters**, not a target size.

Prefer knowledge the model cannot infer: environment contracts, API shapes, valid examples, supported commands and failure mechanisms. Remove duplicated or obsolete advice at its owner. A correction may justify a smaller rule or no new rule. Preserve exact applicability conditions, decision values and user permissions when simplifying.

## Proportionate Verification

For prose-only edits, inspect the before/after meaning, frontmatter and changed links. A new phrase-presence test or an agent/model trial is not needed merely because words changed. If scripts, interfaces or runtime behavior change, exercise the affected safe entry point and relevant repository checks. Follow real project gates rather than blindly running a full suite or adding a test for every paragraph.

For Hermes, structural checks include `tests/skills/test_authoring_standards.py`, run through `scripts/run_tests.sh` with the relevant selection. When new executable behavior needs coverage, place focused tests under `tests/skills/` or the owning source area. A generic skill-manager pass alone does not prove a new helper works.

Regenerate affected documentation/catalog entries when discovery metadata changes, using `website/scripts/generate-skill-docs.py` and its current options. Inspect the resulting diff and retain only intended pages/rows; an unrelated generator rewrite is not part of the skill change. Add `.env.example` entries only if the capability actually introduces a credential requirement.

Bundled descriptions also feed the stock skills index in `tests/fixtures/prompt_surface/`. Carry the intended index changes and token-estimate metadata into those fixtures; keep unrelated host-specific render drift separate.

## Delivery

Commit only the authorized source and generated documentation. Verify links, metadata and important preserved behavior; then report what changed and any untested executable or model-behavior claim. For a local edit, verify the active-profile copy through the loader when relevant. Already loaded skill text or a cached conversation may require a fresh load/session; do not restart working chats solely to demonstrate a prose edit.

## Pitfalls

- A broad trigger can load irrelevant guidance on every nearby task.
- A top-level warning does not neutralize a contradictory example or reference loaded later.
- A copied tool command or platform declaration can be stale even when its prose reads well.
- A longer checklist can make the agent obey the process while missing the user's actual result.
