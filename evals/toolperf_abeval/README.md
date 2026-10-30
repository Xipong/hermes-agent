# Tool performance and prompt-guidance ablations

This extends the existing core-toolset harness (#77056), retaining the isolated
YAML arms and correlated Relay trace checks from KoNit-K's #138490. The guidance
experiment addresses #134640 and supplies local acceptance probes for #146236.
**Task quality and unnecessary work are separate measurements. Shorter prompts
or fewer skill calls are not success criteria.** Runtime model defaults are not
changed here; no live model result follows from the offline tests.

## Status: not ready for model campaigns

Only offline mechanics have been exercised; no live model campaign was run.
The audit found an incompatible Relay observability config, false-positive
correctness/workflow scoring, incomplete-span usage accounting, and gaps in
environment/effective-effort pairing. These remain unresolved. Do not use this
harness to claim quality, savings, or calibrated defaults, or spend model tokens
on it before repairing those defects. The commands below document the intended
interface, not a validated live experiment.

## Arms and pairing

`all_on` explicitly enables `agent.tool_use_enforcement`, `execution_guidance`,
`task_completion_guidance`, and `parallel_tool_call_guidance`. Each of
`tool_use_off`, `completion_off`, and `parallel_off` changes exactly one switch.
All supported arms keep `execution_guidance` enabled, preserving mandatory
tool-backed arithmetic. `execution_off` and `all_off` are not supported: disabling
their whole block would remove that accuracy safeguard. Calculations belong in
an execution tool for every model tier; apparent savings from mental arithmetic
are not an acceptable outcome. Runtime defaults are unchanged.
The optional final-gate-only experiment is not implemented: it needs a separate
policy candidate and evidence, not a new implicit runtime default.

Each run copies the same dedicated Hermes home, then uses the normal atomic,
comment-preserving config writer. Source credentials, config and skills are not
modified. Keep the source home **small, dedicated, immutable, and free of old
sessions**, with the same skill library and required workflows for every arm.
Do not point this at a personal running profile. Copied credentials and traces
are private experiment data; do not commit or publish the result directory.

`pairing.json` records hashes of the source home (including skills), source
commit/diff/untracked files, selected task prompts and relevant environment
settings, plus the requested model and explicitly configured reasoning effort.
Inputs are checked before each launch and on resume. Reusing an arm label with
different switches is refused. Legacy results without receipts cannot resume
into a paired campaign. `report.json` marks mismatched/incomplete comparisons
`paired: false`; never use those as one-block guidance evidence. Different code
trees remain useful code A/B arms, but are **not** controlled guidance pairs.
Provider-side model aliases and undocumented server settings cannot be frozen
by this harness: pin a model release and audit actual requests in the traces.

## Offline mechanics (no provider calls)

From the repository root, using an existing interpreter with the test/Relay
dependencies and an owned temporary directory:

```bash
python -m evals.toolperf_abeval.offline_smoke --root "$OWNED_TEMP/smoke"
scripts/run_tests.sh tests/evals/test_toolperf_abeval.py tests/evals/test_guidance_acceptance.py
python scripts/check
```

The smoke runner performs real local reads/writes/check subprocesses, records
actual NeMo Relay tool spans, and feeds them to the same scorer as model runs.
It reports `offline-mechanics-not-model-evaluation`. Unit controls also omit
required gates and add redundant work. These test the measurement apparatus,
**not** a model's decisions, provider transport, billing or savings.

## Authorized live runs

Live execution can incur charges; it is separate from offline acceptance.
Prepare a dedicated `$ABEVAL_HOME/config.yaml` with provider/tool configuration
and an explicit, supported `agent.reasoning_effort` (for example `high`). Keep
transport/cache settings and credentials fixed; use a separate result root per
model/effort experiment. Configure required skills normally; do not suppress
skill discovery/loading to manufacture a saving.

A guidance-only pair uses the **same checkout** and selection in both arms:

```bash
export ABEVAL_ROOT=/owned/experiment
export ABEVAL_HOME=/owned/eval-home
TREE=/path/to/committed/hermes-agent
MODEL=provider/pinned-model-release
TASKS=guidance_tool_action,guidance_write_readback,guidance_trivial_edit,guidance_arithmetic,accept_bug_fix,accept_shared_schema,accept_changed_after_pass,accept_required_workflow,accept_committed_write,accept_async_write,accept_learning_noop,accept_learning_update
for ARM in all_on tool_use_off completion_off parallel_off; do
  python -m evals.toolperf_abeval.ab_eval run --arm "$ARM" \
    --guidance-arm "$ARM" --model "$MODEL" --reps 3 --pythonpath "$TREE" --only "$TASKS"
done
python -m evals.toolperf_abeval.ab_eval report --models "$MODEL" \
  --arms all_on,tool_use_off,completion_off,parallel_off
```

The legacy `run_all.sh BASE_TREE FIXES_TREE REPS MODEL...` also runs the guidance
matrix for each code tree. `ABEVAL_GUIDANCE_ARMS=all_on,completion_off` narrows it.
Report each tree's guidance arms separately for a same-code comparison.
All completed attempts, including nonzero exits, empty-output crashes and
timeouts, stay in the denominator. Resume does not silently retry away failures.

## What the probes establish

| Probe | Correctness evidence | Unnecessary work measured |
|---|---|---|
| Tool action / arithmetic | Successful correlated tool result, requested answer | Tool and LLM call counts |
| Explicit local write/read-back | Same path, successful write, later read with expected content | Counts, not a claim that system guidance requires local read-back |
| Trivial local edit | Successful write span and final file | Subsequent reads of the exact target |
| Narrow bug fix | Failing baseline check, changed implementation, passing current-revision check | Repeated passing checks of the same action/revision |
| Shared schema | Both producer and consumer checks on current revision | Same-revision repeats, not justified broader coverage |
| Change after passing check | Prior passing revision and a passing check for the new revision | Repeats only within a revision |
| Required workflow | Sandbox skill read and affected check | Skill reads are never classified as waste |
| Committed / asynchronous write | Committed object/revision/value vs acknowledgement followed by status | Status fetch after an authoritative synchronous commit |
| Learning no-op / correction | Read skill and lesson; unchanged skill vs fresh-read guarded append | Writes with no new lesson in the no-op fixture |

These are intentionally small, mechanically scored instruction-following
fixtures. External writes are a **local simulated service**, not real API
acceptance. Skill review uses a sandbox skill and an exact supplied correction;
it does not evaluate open-ended novelty or run the background curator. The
fixture script must remain unchanged. Terminal fixture actions use the simple
three-argument command shown in the task (not a shell pipeline). A paraphrased
correction or an alternative tool path may require manual adjudication rather
than relaxing the scorer after seeing which arm wins.

Trace scoring consumes completed UUID-correlated calls, not narration or merely
a final file. Missing/failed/overlapping read-back spans cannot pass. Required
checks are tied to the implementation hash, so stale passing evidence cannot
justify a later revision. Scored repetition is a lower bound: arbitrary shell
checks, invented test files, nested delegated work and semantic reviewer roles
need trace review. `delegation_calls` counts calls; `reviewer_calls` is null
because not every delegation is a review. Do not call every extra tool or skill
load wasted work. The original nine tool-error traps are retained, but their
older marker-based success checks are not promoted to guidance evidence.

## Metrics and interpretation

The table retains LLM-call, tool-call, error/retry, result-size and wall-time
columns. `llm` counts completed LLM spans, not user turns. Detailed per-task rows
and arm totals are written to `<results>/<model>/report.json`:

- Correctness (`ok`) is independent of redundant-check/read-back/skill-edit
  counters. Compare paired task outcomes first; inspect omissions/regressions.
- Raw provider usage supplies input, cached input, uncached input, output,
  reasoning and total tokens when exposed. OpenAI input includes cache reads;
  Anthropic input/cache-read/cache-creation categories are reconciled separately.
  Reasoning is already included in output and is **not added twice**.
- A missing field or missing usage for any LLM call is **null**, not zero.
  Partial billing is not a complete cost. Cost comes only from raw provider
  `usage.cost` in USD, never guessed prices or Relay's estimated annotations.
- Cost per success is **all attempts' reported cost / accepted attempts**,
  including failed attempts' costs. It is null for no successes or incomplete
  billing. An unavailable provider field remains unmeasured.

Accept a policy change only after controlled live evidence shows less
unnecessary work without worse outcomes or premature stopping. Sample size,
run order/cache warmup, supported effort, task representativeness, provider
usage coverage and manual trace adjudication belong in that campaign's report.
No model release, effort level or default policy has been calibrated by the
local deterministic tests. Provenance comments and runtime policy changes are
owned separately from this eval infrastructure.
