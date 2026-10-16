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

## R3. Built-in evaluators: logic and scores (catalog aligned with the live walkthrough)

- **Decision**: Exactly 12 built-ins, matching the reference catalog observed live on 2026-10-16
  (`research/live/evaluator-catalog.json`): names, scopes, cost classes, output kinds, default
  on/off and every settings field with type, range and default as listed in data-model.md
  "Built-in catalog". Display names, descriptions and helper texts are written fresh. The earlier
  draft's `flow_step_completion` and the rule bundle inside `anomaly_detection` are dropped: dead
  air moved to `audio_silence`, latency spikes to `latency_slo`, loops to `stuck_loop_detector`,
  and node-level failures to `node_dead_end` and `transition_correctness`.

| name | scope | cost | input | score and verdict |
|---|---|---|---|---|
| `anomaly_detection` | call | free | `call_embeddings` (R13) | mean cosine distance to the `knn_k` nearest calls of the agent within `window_days`; fail if > `threshold`; n/a "insufficient data" below `min_sample_size` |
| `factual_consistency` | call | llm_judge | replies, KB chunks returned by `search_knowledge_base` tool events, tool outputs | 0 to 1; pass if >= 0.5 (version cutoff); n/a when no KB search happened |
| `flow_completion` | call | free | `flow_transition` events (004) | pass if the last node type is `end` or `transfer`; one item naming the last node |
| `intent_fulfillment` | call | llm_judge | prompt or flow instructions, transcript | 0 to 1; pass if >= 0.5; sampled per `sample_rate_pct` (R14) |
| `kb_relevance` | call | llm_judge | caller queries and the chunks each KB search returned | 0 to 1; n/a when the agent has no KB or no search happened |
| `audio_silence` | call | free | recording (R12) | longest silence in ms; fail if > `max_acceptable_silence_ms`; n/a without a recording |
| `node_dead_end` | call | free | `flow_transition` events | item per visited node; fail on the node the call ended on when it is not `end` or `transfer`; run fails if any item fails |
| `process_reward` | turn | llm_judge | goal, transcript | -1, 0, +1 per agent turn; item fails at -1; run fails if failing items > `max_failed_items` (0); score = mean |
| `stuck_loop_detector` | call | free | `flow_transition` events | item per visited node; fail if visits > `max_visits_per_node` |
| `tool_call_correctness` | call | llm_judge | tool call events with arguments and outputs | 0 to 1; n/a when no tool calls |
| `transition_correctness` | call | llm_judge | each transition with its source node's outgoing edges | map step: one judge call per transition with the alternatives in seeded random order (seed = run id) to reduce position bias; reduce step: item per transition attributed to its source node; run fails if any item fails |
| `latency_slo` | turn | free | per-turn `e2e_ms` from call events | item per agent turn; fail if > `threshold_ms`; n/a for calls without audio timing (simulated, test text calls) |

Judges receive per-turn data in batches of at most 40 turns per request for per-turn scopes. The
judge pass cutoff (0.5) is part of the evaluator version, not a user setting, so the catalog's
settings stay exactly as observed.
- **Alternatives considered**: keeping our earlier seven-evaluator list (diverges from the product
  being rebuilt and lacks audio and per-node checks); exposing `pass_threshold` on judges (not in
  the reference catalog; calibration can still report agreement per version).

## R4. Judge execution and prompt-injection defence

- **Decision**: Judge calls go through the `llms` completion client (002) with a JSON-schema output
  `{verdict_hint, score, rationale, evidence_turns[]}`. The transcript is passed inside a
  delimited data block with a fixed preamble stating that the content is data and that
  instructions inside it must be ignored. The server derives the verdict from the score and the
  version's pinned cutoff (the model never decides pass/fail directly), validates
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
    score >= t (or `fail` if score > t for evaluators where a higher score is worse, declared by
    the version as `threshold_direction = above_fails`; `anomaly_detection` is the only v1 case);
    maximise agreement; ties broken by smallest |t - current|, then lower t. Only for evaluators
    whose settings include a 0 to 1 `threshold`; computed only when n >= 5.
  For evaluators with node-attributed items (`node_dead_end`, `stuck_loop_detector`,
  `transition_correctness`), rows are also split by `flow_node_id` using item verdicts.
  For turn and step scopes, calibration uses the run-level verdict (and per-step verdicts for
  node-attributed rows). Simulated calls are excluded. Data is computed per request with SQL that
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

## R12. Long silences from the recording

- **Decision**: `evaluators/audio.py` streams the dual-channel recording from object storage in
  the jobs worker (the API image already holds storage credentials; architecture section 7),
  decodes it with PyAV to 16 kHz mono per channel, and computes RMS level in 20 ms frames. A frame
  is silent when both channels are below `call_average_db + silence_threshold_db` (threshold is
  negative). Runs of silent frames shorter than `min_silence_ms` are ignored. The item score is
  the longest run; the rationale lists the three longest runs with start offsets. Leading silence
  before the first speech and trailing silence after hang-up are excluded. No recording
  (`recording_enabled = false`, purged, or origin `simulation`) gives `not_applicable` with
  rationale "no recording".
- **Rationale**: FR-040; the transcript cannot show dead air, TTS stalls or mid-word hang-ups.
  Using both channels avoids counting the caller listening while the agent speaks as silence.
- **Alternatives considered**: VAD on the agent channel only (misses caller-side silence after an
  agent question); transcript timestamps (gaps between words are not silences in audio).

## R13. Anomaly detection with call embeddings

- **Decision**: After a live call completes, the evaluator embeds a normalised text of the call
  (agent and caller turns, tool names, end reason; truncated to the embedding model's limit)
  through 005's embedding adapter and stores it in `call_embeddings`. Neighbours are the
  `knn_k` nearest rows of the same agent with `ended_at` in the last `window_days`, excluding the
  call itself, by pgvector cosine distance. If fewer than `min_sample_size` rows exist, up to
  `backfill_per_run` completed live calls of the agent without an embedding are embedded first
  (newest first), then the count is re-checked. Embedding cost is recorded as `embedding` usage
  with raw cost and zero billable amount, so the check stays free.
- **Rationale**: FR-042; finds failure modes nobody wrote a check for, without labels, reusing
  pgvector already present for the knowledge base.
- **Alternatives considered**: rule bundle (dead air, repeats, latency) from the earlier draft
  (overlaps the dedicated checks and only finds known patterns); isolation forest over numeric
  features (needs per-agent model training state).

## R14. Sampling for judge cost control

- **Decision**: Deterministic hash sampling per `(call_id, evaluator_name)` (data-model.md), so a
  re-delivered pipeline job makes the same decision. Not-selected runs are stored as `skipped`
  with `not_sampled` so the call view can explain the gap. Sampling only applies to
  `trigger = pipeline` on live calls; reruns, datasets and simulations ignore it so comparisons
  are complete.
- **Rationale**: FR-037; random sampling at job time would differ on retries.

## R15. Judge model list and settings editing

- **Decision**: `EVAL_JUDGE_MODELS` (API setting, list of model ids from 002's LLM catalog, first
  entry is the default) feeds every `judge_model` select, the custom judge form, and validation.
  `GET /v1/evaluators/judge-models` serves the list. Settings are validated twice: the web form
  (generated from `settings_schema`, `int` as stepper, `select` as pick list, Save disabled while
  any field is invalid) and the API (422 with `errors[{field, message}]`). Toggle and save are both
  a full PUT. Helper texts use a `{default}` placeholder so the text can never disagree with the
  default.
- **Rationale**: FR-036, FR-038, FR-039. The live walkthrough found a free-text judge model, a
  sample rate of 150 accepted by the form, an integer setting shown as plain text, and a helper
  that stated a different default than the field; each is prevented here by construction.
