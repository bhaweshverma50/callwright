# Phase 0 Research: Quality and Evaluations

**Feature**: 007-quality-evals | **Date**: 2026-10-16

## R1. Where evaluator settings live: per agent, not per agent version

- **Decision**: Analysis variables (`analysis_variables`), per-agent evaluator settings
  (`agent_eval_settings`) and headline flags are rows owned by 007, keyed by `agent_id`. They are
  not part of the immutable AgentVersion snapshot. The extraction model is read from the call's
  agent version (`advanced.analysis_model`, falling back to `llm.model`). Every run snapshots the
  settings it used (`settings_snapshot`, `settings_hash`).
- **Rationale**: Turning a check on or tuning a threshold does not change how the agent talks, so it
  should not force a new published version or make simulations treat it as a variant. Snapshots on
  runs keep results auditable (Principle IV).
- **Conflict**: architecture.md section 5 lists "evals config" inside AgentConfig. This plan moves
  it out; the AgentConfig `evals` key should be dropped or reduced to nothing. Raised in the
  report.
- **Alternatives considered**: versioned eval config in AgentConfig (every toggle creates a version
  and a new variant in experiments).

## R2. Evaluator versioning (Principle IV)

- **Decision**: `evaluators` holds identity (`evl_` ID, name, kind, scope, cost class, settings
  schema, `current_version`). `evaluator_versions` holds immutable definitions `(evaluator_id,
  version)`. Built-ins are defined in code (`services/api/app/evaluators/builtins/<name>.py` with a
  `VERSION` integer, prompt template, pinned judge model id and settings schema); on startup a sync
  step upserts the global evaluator rows and inserts a new version row when the code's `VERSION`
  is higher, storing `prompt_sha256` and the judge model. Custom evaluators get version 1 on
  create and +1 on every definition edit. Runs reference `(evaluator_id, evaluator_version)`.
- **Rationale**: A verdict is only meaningful with the exact logic that produced it; calibration by
  version needs a stable key.
- **Alternatives considered**: hashing definitions without version numbers (unreadable in the UI);
  semantic version strings (no need for minor/patch semantics).

## R3. Built-in evaluators: logic and scores

| name | scope | cost | score | verdict rule (defaults) |
|---|---|---|---|---|
| `intent_fulfillment` | call | llm_judge | 0 to 1 | pass if score >= `pass_threshold` (0.5) |
| `tool_call_correctness` | call | llm_judge | 0 to 1 | n/a when no tool calls; pass if score >= `pass_threshold` (0.5) |
| `kb_relevance` | turn | llm_judge | 0 to 1 per KB-backed turn | n/a when the agent has no KB or no retrieval happened; item pass if score >= `pass_threshold` (0.5); run fails if failing items > `max_failed_items` (0) |
| `factual_consistency` | call | llm_judge | 0 to 1 | judged against prompt, KB chunks retrieved and tool outputs; pass if score >= `pass_threshold` (0.6) |
| `process_reward` | turn | llm_judge | -1, 0, +1 per agent turn | item fails at -1; run fails if failing items > `max_failed_items` (0); run score = mean |
| `anomaly_detection` | call | free | count of anomalies | rules: dead air > `max_silence_s` (8), same agent utterance >= `max_repeats` (3) times, tool error rate > `max_tool_error_rate` (0.5), any turn e2e > `max_turn_latency_ms` (3000), disconnect reason `error`; fail if any rule fires; rationale lists each with turn index |
| `flow_step_completion` | flow_node | llm_judge | 0 to 1 per visited node | flow agents only; item pass if score >= `pass_threshold` (0.5) |

Judges receive per-turn data in batches of at most 40 turns per request for per-turn scopes.

## R4. Judge execution and prompt-injection defence

- **Decision**: Judge calls go through the `llms` completion client (002) with a JSON-schema output
  `{verdict_hint, score, rationale, evidence_turns[]}`. The transcript is passed inside a
  delimited data block with a fixed preamble stating that the content is data and that
  instructions inside it must be ignored. The server derives the verdict from the score and the
  threshold (the model never decides pass/fail directly for threshold evaluators), validates
  `evidence_turns` against real indices, and rejects empty rationales (retry once, then error).
  Temperature 0.
- **Rationale**: FR-014, FR-019, SC-007. Deriving verdicts server-side also lets calibration
  re-threshold stored scores (R7).
- **Alternatives considered**: letting the judge return pass/fail (cannot re-threshold); a
  separate injection classifier (extra cost; revisit if SC-007 fails).

## R5. Execution model in the jobs worker

- **Decision**: One arq job per call per step: `analysis_vars.jobs.analyze_call(call_id)` then
  `evals.jobs.evaluate_call(call_id, trigger, run_group_id)`. Inside, enabled evaluators run
  concurrently with `asyncio.Semaphore(4)`, a 60 s timeout each, one retry on provider errors.
  Each run row moves `pending -> running -> completed | skipped | error` and is committed as it
  finishes so the UI fills progressively (polled every 3 s while any run is active).
  Idempotency: pipeline jobs are keyed `call_id:analysis` and `call_id:evals:pipeline`; reruns are
  keyed by `call_id:evals:<Idempotency-Key>`. A partial unique index forbids two active run groups
  per call, which implements "Checks are already running".
- **Rationale**: Principle VI (no new queue or service). Per-call fan-in keeps the ordering
  required by architecture section 6.
- **Alternatives considered**: one job per evaluator (more jobs, harder ordering for the webhook).

## R6. Charging

- **Decision**: Before each model call, check balance > 0; if not, mark the run or analysis
  `skipped` with `skip_reason = insufficient_credit`. After success, call
  `billing.charge_feature(feature="eval.<evaluator_name>" | "eval.llm_judge_custom" |
  "post_call_analysis", raw_cost_usd, idempotency_key=f"{run_id}")`. Free evaluators never charge.
  Trial runs of custom evaluators charge `eval.llm_judge_custom` keyed by the request's
  Idempotency-Key.
- **Rationale**: Principle III; architecture section 7 routes all feature charges through
  `billing.charge_feature`.

## R7. Calibration math (test-first, Principle VII)

- **Decision**: Pure functions in `services/api/app/calibration/math.py`:
  - `resolve_label(labels) -> good | bad | conflict | none` (majority; tie is conflict).
  - `matrix(pairs) -> {both_pass, both_fail, over_eager, missed, n}` where a pair is
    (evaluator verdict in {pass, fail}, human label in {good, bad}); good maps to expected pass.
  - `agreement(m) = (both_pass + both_fail) / n`, `None` when n = 0.
  - `wilson_interval(k, n, z=1.96)` for the 95% range; `None` when n = 0.
  - `reading(m, min_sample=5)`: `insufficient` if n < 5; `strong` if a >= 0.85; `low` if a < 0.5;
    `over_eager` if over_eager >= 2 x missed and over_eager > 0; `misses` if missed >= 2 x
    over_eager and missed > 0; else `partial`.
  - `best_threshold(scored_pairs, current)`: for t in 0.05..0.95 step 0.05, verdict = pass if
    score >= t; maximise agreement; ties broken by smallest |t - current|, then lower t. Only for
    evaluators whose settings schema has `pass_threshold`; computed only when n >= 5.
  For turn and step scopes, calibration uses the run-level verdict (and per-step verdicts for
  `flow_node` rows). Simulated calls are excluded. Data is computed per request with SQL that
  returns the pairs, then the math runs in Python.
- **Rationale**: Small inputs (labels are human-limited, at most thousands per window); a cache
  table adds staleness with no measured need.
- **Copy**: our readings are written fresh; over-eager advises lowering the pass threshold and
  misses advises raising it, matching how our thresholds work (score >= threshold passes).
- **Alternatives considered**: Cohen's kappa (harder to explain to operators; can be added as a
  secondary figure later).

## R8. Review queue ordering

- **Decision**: SQL over `calls` (origin live, status completed, ended within lookback) left-joined
  to the viewer's annotation (must be null) and to current-run aggregates:
  - random: `ORDER BY md5(call_id || :user_id || :utc_date)`;
  - failed: `fail_count >= 1 ORDER BY fail_count DESC, ended_at DESC`;
  - disagreement: `pass_count >= 1 AND fail_count >= 1 ORDER BY abs(pass_count - fail_count) ASC,
    ended_at DESC`.
  Summary runs the three counts in one query with `FILTER` clauses.
- **Rationale**: Stable daily random order lets operators reload without losing their place; no
  extra state.

## R9. Phrase checks: safe patterns

- **Decision**: Patterns compiled with `google-re2` (linear time, no backtracking); plain-text mode
  escapes the input. Pattern length at most 500 characters; compile errors return 422 with the
  message. Matching runs on the selected speaker's turns; rationale quotes the first match with
  turn index.
- **Rationale**: FR-012; Python `re` allows catastrophic backtracking on user patterns.

## R10. Quality port registration and the analytics view

- **Decision**: `services/api/app/evals/quality_port.py` implements 006's `CallQualityPort` using
  current runs (`superseded_at IS NULL`, status completed) and annotations, and is registered at
  app start. This feature's migration replaces the 006 stub view `analytics.evaluator_verdicts_v`
  with a real definition (`security_invoker = true`) over current runs.
- **Rationale**: Keeps 006 shippable first and the dependency direction intact (006 research R3).

## R11. Writing summary, sentiment and values onto the call

- **Decision**: The analysis job writes summary, sentiment and values to `calls` through 003's
  service function `calls.service.set_analysis(call_id, summary, sentiment, values)` and keeps its
  own metadata in `call_analyses` (model, variable snapshot, status, cost).
- **Rationale**: Architecture section 5 places these fields on Call; the owner module performs the
  write.
- **Alternatives considered**: reading them only from `call_analyses` (would change 006's read
  model and the architecture's Call shape).
