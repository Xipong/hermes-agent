---
name: requesting-code-review
description: "Use when reviewing changes and their relevant evidence."
version: 2.2.0
author: Hermes Agent (adapted from obra/superpowers + MorAlekss)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, security, verification, quality, pre-commit, auto-fix]
    related_skills: [subagent-driven-development, test-driven-development, github]
---

# Code Review and Verification

Review the intended behavior and affected consumers, then choose evidence proportionate to the remaining risk. A review is a way to find useful problems, not a mandatory multi-agent pre-commit pipeline.

## When to Use

- The user requests a review, verification or pre-merge assessment.
- A substantive change, cross-owner integration or security-sensitive boundary needs another look.
- Existing evidence leaves a concrete question before publication.

A trivial code or prose edit may need only inspection. A configuration change can be consequential: select depth by its effects, not its extension. Respect required project/user gates and any read-only review scope.

## Establish the Candidate

Use `terminal` to inspect the actual task base, branch and diff. `git diff --cached` covers staged work; `git diff` covers unstaged work; a branch review uses its real base rather than only the latest commit. An empty staged diff is not proof there is nothing to review: check the working tree and status. Stage routine owned edits yourself only when publication is authorized.

Read the relevant changed code and consumers. Split a large diff by coherent areas when useful; history or dependencies matter when they explain an otherwise unclear boundary.

## Review for Material Problems

Prioritize correctness, data loss, authorization, secrets, injection, resource ownership and affected contracts. Security scans and patterns are leads, not automatic verdicts: establish whether untrusted input can reach a dangerous operation. Select applicable checks rather than requiring a generic checklist for every file.

Examples of useful questions:
- Does the public/native caller receive the intended result, including relevant failure paths?
- Are secret values exposed or committed, rather than harmless placeholder names?
- Are database queries parameterized and shell arguments separated from untrusted text?
- Do retries, concurrency and cleanup preserve ownership and delivery?
- Do checks observe behavior rather than implementation spelling or a substitute mock?

Give findings a concrete mechanism and source location. Separate confirmed defects, unresolved risks and optional suggestions. A missing defensive wrapper or a scan match alone is not a bug.

## Select Verification

Use the repository's declared runner and affected checks. Reuse fresh passing evidence while its relevant inputs remain unchanged. For a disputed failure, compare that exact case against a pinned baseline with matching dependencies; avoid disturbing active shared work to manufacture a baseline.

Run broader integration, security checks or a full suite when affected contracts, material risk or required gates warrant them. Inspection may suffice for a trivial edit with no meaningful behavioral or contract effect. A new test per function, a fresh full suite per review and tests that mirror the diff are not default requirements.

## Independent Review When Useful

Use native `delegate_task` when the user asks for it or independent reasoning can settle a material unresolved question. Give the reviewer the contract, base/head, affected consumers, exclusions and existing evidence. Keep normal small fixes in the current context; no fixed number of spec, code and fix agents is required.

If structured output was requested, validate that it contains the requested findings; an unparseable or missing review is not approval. Judge reports against the actual code and evidence rather than blindly accepting a pass/fail label.

## Resolve and Deliver

Repair confirmed in-scope issues through the existing owner, then recheck the failed observer and affected callers. Reuse other valid results. Reconsider the cause or approach when repairs stop making progress; seek a user decision only when it is actually needed. A cosmetic follow-up does not automatically restart the review pipeline.

For an authorized commit/push, stage only owned files and use `github` for publication mechanics. A read-only review ends with findings, not edits. Report the candidate, useful findings or repairs, executed checks and remaining limitations. Distinguish local checks, requested independent review and hosted CI; report relevant unavailable checks rather than silently treating them as passed.

## Pitfalls

- Treating grep patterns or a reviewer JSON boolean as evidence of exploitability.
- Requiring explicit permission again for an already authorized commit or fix.
- Automatically stashing/resetting someone else's work to get a clean baseline.
- Re-running the whole pipeline after a small change that leaves accepted evidence valid.
- Enforcing TDD chronology instead of checking the intended behavior and useful regression coverage.
