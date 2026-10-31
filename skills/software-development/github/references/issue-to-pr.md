# GitHub Issue to Pull Request

Turn a GitHub issue into a tested, verified PR. This skill owns the end-to-end discipline — premise validation, duplicate sweeps, class-level fixes, and honest CI reporting; the sibling GitHub and development skills own their own mechanics.

## When to Use

- "Fix issue #123 and open a PR."
- "Implement this GitHub feature request."
- "Take this bug from issue to green CI."

Don't use for: reviewing an existing PR, or answering a code question with no requested change.

## Procedure

### 1. Read the live issue — body AND full thread

Use `terminal` to run `gh issue view <N> --comments`. The body is a snapshot from filing time; the newest comments carry the live state: partial fixes already merged, new root-cause analyses, maintainer decisions, or questions directed at you that change the task. Also read repository instructions (`AGENTS.md`, contribution docs) with `read_file`. Done when the currently requested behavior, non-goals, and any unanswered thread questions are known.

### 2. Sweep for existing and duplicate work

Search linked work with `gh pr list --search "#<N>" --state all`; broaden by subsystem/symptom when that search is incomplete. Check relevant recent history, for example `git log --oneline -20 -- <relevant files>`. Reuse or coordinate existing work rather than building a duplicate, and state search limits rather than claiming exhaustive coverage.

### 3. Validate the premise against current code — and against design intent

Establish the reported failure or feature gap in current code with a reproduction, focused test, fixture, or other evidence suited to the change. Trace the relevant path with `search_files` and `read_file`. Check design intent when it is unclear; `git log -p -S "<symbol>"` can explain a deliberate restriction. Challenge stale issue prose rather than implementing it blindly. Done when the premise and intended behavior are supported, or missing evidence is stated.

### 4. Define acceptance and risk

List acceptance criteria, interfaces, migrations/state changes, compatibility, security/privacy, rollout, and rollback. Map every criterion to a test or explicit verification. Done when review has a finite contract.

### 5. Implement the smallest complete change — and fix the class

Work on a branch or worktree that preserves existing work. Use relevant debugging/testing guidance and add regression coverage where behavior changes. Inspect sibling call sites for the same root cause; repair those within scope and identify separate follow-up work rather than silently expanding the PR. Avoid drive-by cleanup. Done when appropriate checks support the fix and known sibling risks are resolved or disclosed.

### 6. Validate regression coverage

Check that new tests distinguish the intended behavior from the defect. Existing failing-before evidence is sufficient. When that distinction remains uncertain, run the test against an isolated pre-fix version or use a focused mutation without disturbing current work. Follow repository requirements for red-on-base evidence; do not restore broken behavior in the active working tree merely to repeat an already established result.

### 7. Run applicable quality gates and open the requested PR

Run the repository's required gates and checks relevant to the changed surface. Reuse passing evidence for unchanged current-revision inputs; add review or broader execution for unresolved risks, not a fixed reviewer quota. Follow `references/pr-workflow.md` for PR mechanics and record the problem, approach, actual checks, risks, and exclusions. Push/open the PR within user authorization. Verify head SHA, base, title, and intended diff from the provider response or a targeted read when needed. Done when the requested PR exists and its CI state is known, including not configured or pending.

### 8. Shepherd CI honestly and close the loop

Inspect live checks and failure logs via `gh pr checks` / `gh run view --log-failed`. Distinguish failures introduced by your diff from pre-existing baseline or infrastructure failures — reproduce on the default branch when unsure, and rerun once only for genuine infra flakes. Never say "green," "merged," or "released" without live evidence of that exact state. When the PR lands, comment on the issue with the PR link and a one-line explanation so the reporter gets a traceable resolution. Done when CI state, remaining blockers, and the issue thread all reflect reality.

## Pitfalls

- Coding before reading issue comments, sweeping for duplicate PRs, or reading current code.
- "Fixing" behavior that the original commit shows is intentional design.
- Fixing a symptom at one call site while sibling sites keep the same bug.
- Shipping a regression test that also passes without the fix.
- Hiding unrun required checks or adding unrelated formatting churn.
- Claiming the issue is delivered because a PR exists.

## Verification

- [ ] Full issue thread read; newest comment state reflected in the plan.
- [ ] Relevant existing work searched; search limits stated.
- [ ] Premise and intended behavior supported by current evidence.
- [ ] Regression coverage distinguishes the defect where applicable; repository-specific gates satisfied.
- [ ] Sibling risks resolved within scope or disclosed.
- [ ] Changes stay within the issue and required supporting work.
- [ ] CI state reported from live evidence only; issue commented with the PR link.
