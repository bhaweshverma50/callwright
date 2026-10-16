# Research: Testing and Simulation

**Feature**: 008-testing-simulation | **Date**: 2026-10-16

Each entry: Decision, Rationale, Alternatives considered.

## R1. Where simulated conversations execute

- **Decision**: A text-mode session runner lives in the voice-worker codebase
  (`services/voice-worker/worker/textsim/`) and runs as a second process of the voice-worker
  image (`python -m worker.textsim.entry`), consuming an arq queue named `textsim` on the
  existing Redis. It builds the same session as a live call (`pipeline.py`, `flow/`, `tools/`)
  with text input and output instead of STT/TTS, so the agent logic under test is the code that
  serves real callers. The API owns all state: the runner fetches a run spec from
  `GET /v1/internal/simulation-runs/{id}/spec`, posts turns and tool events to the existing
  `POST /v1/internal/calls/{id}/events`, and finishes with
  `POST /v1/internal/simulation-runs/{id}/result`. Test-case runs use the same runner with one
  caller turn (`/v1/internal/test-runs/{trn_id}/cases/{tc_id}/spec` and `.../result`).
- **Rationale**: Principle IV only holds if simulated behaviour matches live behaviour; a second
  implementation of prompt assembly, flow transitions and tool calling inside the API would
  drift. The constitution already requires an offline scripted-caller harness (Principle VII);
  replay mode is that harness with a recorded script, so both share one driver.
- **Alternatives considered**: (a) Run the LLM loop inside the API jobs worker: duplicates the
  flow executor and tool layer. (b) Dispatch text-only LiveKit rooms: adds room cost and
  latency for no audio benefit. (c) A new simulation service: violates Principle VI when a
  process role in an existing image is enough.

## R2. Representing the simulated conversation

- **Decision**: Each finished simulation creates a row in `calls` with a new column
  `origin = 'simulation'` (default `'live'`) and `simulation_run_id`. Channel copies the base
  call's channel (`web` for standalone persona runs). Lifecycle skips `ringing`. The post-call
  pipeline runs finalize transcript, summary/sentiment/analysis variables and evaluators, and
  skips pricing, the ledger call charge and the customer webhook when `origin = 'simulation'`.
  Call History, dashboards and analytics filter `origin = 'live'` unless asked otherwise.
- **Rationale**: Evaluators (007) and issue detection (009) already operate on calls; storing
  simulated conversations as calls lets them work unchanged and lets 009 include simulated
  calls on request.
- **Alternatives considered**: A separate `simulated_transcripts` table: every evaluator and the
  issue clustering would need a second input path. Adding `simulation` to the `channel` enum:
  conflates how a call arrived with whether it was real, and breaks channel analytics.
- **Conflict note**: architecture.md section 5 lists no `origin` field on Call and section 6
  does not describe skipped steps. Recorded in plan.md Complexity Tracking and reported.

## R3. Target configuration and reproducibility

- **Decision**: On start, the API resolves the target to a full snapshot (agent config, tool
  definitions including mock responses, flow graph, knowledge-base ids) and stores it as JSONB
  with a SHA-256 content hash over canonical JSON (sorted keys, no whitespace). `published`,
  `draft` and `version` targets are resolved through `agent_versions` (002); `variant` targets
  carry a full snapshot in the request, validated with 002's config validator and 004's flow
  validator, and store `base_agent_version_id` plus a diff for display. A batch stores one
  snapshot; its runs reference it.
- **Rationale**: A comparison is only meaningful if the exact configuration is known later, even
  after the agent changes. Full-snapshot variants avoid inventing a patch language over nested
  arrays (flow nodes, tools).
- **Alternatives considered**: JSON Patch overrides on a base version: fragile against array
  indices; JSON Merge Patch: cannot address list items by id.

## R4. Tool answers during simulation

- **Decision**: In simulation sessions the worker's tool executor is wrapped by
  `textsim/mock_tools.py`. Order: (1) `mock_response` from the tool or webhook node; (2) replay
  mode only: the output of the k-th call to the same tool name in the base call's tool events;
  (3) `missing_mock_policy = synthesize` (default): a short LLM-generated JSON stand-in using the
  tool's description and parameter schema, metered as `simulation.tool_synth`;
  `missing_mock_policy = error`: `{"error":"no_mock_configured"}`. Every tool event records
  `answer_source` in `mock | recorded | synthesized | error`. `kb_search` runs for real (read
  only). `end_call` and `transfer` end the session with the matching disconnect reason; keypad
  digits are logged. The textsim process has no route to customer endpoints: HTTP tool and
  webhook node executors are never constructed in simulation mode, and the harness tests fail
  on any outbound socket outside the LLM adapter allow-list.
- **Rationale**: Simulations must not book appointments or charge cards. Recorded outputs make
  replay closer to reality when mocks are missing; labelling the source keeps results honest.
- **Alternatives considered**: Refuse to run without mocks: too strict for exploration. Always
  synthesize: hides that the result depends on invented data.

## R5. Replay turn alignment and divergence

- **Decision**: Caller turns are the base transcript's user messages in order (interrupted
  fragments merged with the next fragment of the same speaker). If the original start speaker
  was the agent, the runner waits for the agent's first message, then sends caller turn 1, and
  so on, sending the next caller turn after each agent turn completes (including tool calls).
  The run stops when caller turns run out (the runner then sends end of conversation), the agent
  ends the call, or 50 agent turns pass. Divergence is the first index where (a) the agent ends
  or transfers before caller turns run out, or (b) for flow agents, the visited node sequence
  differs from the original's. Stored as `diverged_at_turn` (null when none).
- **Rationale**: Simple, deterministic and explainable; the divergence marker tells users when
  replay results stop being meaningful and persona mode is the better choice.
- **Alternatives considered**: Semantic similarity between original and simulated agent text:
  costly and noisy for little gain.

## R6. Persona mode

- **Decision**: Persona extraction is one LLM call over the base transcript producing
  `{goal, known_facts[], temperament, speaking_style, constraints[], opening_line?}` with a JSON
  schema (metered `simulation.persona_extraction`). The simulated caller is an LLM prompted with
  the brief, the conversation so far and one tool `hang_up(reason)`; it speaks only as the
  caller. Persona model default comes from workspace settings (`simulator_model`), temperature
  0.7. Stop on `hang_up`, agent end/transfer, or `max_caller_turns` (default 20, max 50). Caller
  turns are metered as `simulation.dialogue`.
- **Rationale**: Mirrors how a real caller reacts to a changed agent; a structured brief is
  reviewable and reusable for standalone runs.
- **Alternatives considered**: Free-text brief only: harder to show and to edit consistently.

## R7. Evaluator version parity

- **Decision**: The comparison and scorecard use, for each evaluator, the results produced by
  the evaluator version that scored the simulated call. When the base call lacks a result for
  that version, the run's final step calls 007's evaluation service for the base call
  (billed as evaluations by 007). The scorecard flags any pair where versions still differ and
  leaves it out of pair counts.
- **Rationale**: Principle IV requires verdicts to keep their evaluator version; comparing
  verdicts from different rubric versions would show changes the agent did not cause.
- **Alternatives considered**: Compare whatever results exist: misleading after evaluator edits.

## R8. Scorecard math (test-first, Principle VII)

- **Decision**: Implemented as a pure module `services/api/app/simulator/scorecard.py`.
  - Per call c and evaluator e, verdict `v(c,e)`: call scope uses the single verdict; turn scope
    collapses to `fail` if any turn fails, else `pass`; results in `error` or `not_applicable`
    are excluded. Flow-node scope groups by `(node_id, e)` and collapses the same way per call.
  - Pass rate `P(S,e) = passes / n` over calls in S with a verdict; `null` when n = 0.
  - `delta_pp = 100 * (P_sim - P_base)`, computed with exact fractions and rounded half away
    from zero to one decimal only for display; comparisons in 009 use the unrounded fraction.
  - Pairs: calls with a verdict on both sides (same evaluator version) give `improved`
    (fail to pass), `regressed` (pass to fail), `unchanged_pass`, `unchanged_fail`.
  - `mean_score` = arithmetic mean of numeric scores where present, else `null`.
  - Baseline is `original` (the base calls) or `experiment` (another batch's simulated calls
    matched by base call id). Failed or cancelled runs are excluded from the simulated side and
    reported in `excluded_runs`.
- **Rationale**: Exact arithmetic makes the 10-point threshold in 009 unambiguous at the
  boundary; per-call collapse stops long calls from outweighing short ones.
- **Alternatives considered**: Pooling turn-level results: overweights long calls. Floats:
  boundary cases such as 0.7 - 0.6 fail an equality check.

## R9. LLM judge for test cases

- **Decision**: The judge prompt receives the caller utterance, the expected behaviour, the
  agent reply and tool calls; it returns `{verdict: passed|failed, reasoning}` through
  structured output at temperature 0. One retry on malformed output, then the result is `error`.
  The call goes through the LLM judge adapter that 007 provides (provider chosen by config,
  Principle I); `test_runs/judge.py` only builds the prompt and parses the answer. Default judge
  model comes from workspace settings.
- **Rationale**: Reuses the provider-agnostic path; deterministic temperature keeps reruns
  stable.
- **Alternatives considered**: Ask the judge for a score: users asked for pass/fail plus a reason.

## R10. Billing and idempotency

- **Decision**: Feature keys passed to `billing.charge_feature()` (001): `testing.run`
  (agent and judge tokens for the whole run), `testing.generate`, `simulation.replay`,
  `simulation.persona`, `simulation.persona_extraction`, `simulation.tool_synth`. One charge per
  test run and per simulation run, keyed `feature:<run id>` so retries cannot double charge;
  evaluations of simulated and base calls are charged by 007 under its own keys. POSTs that
  start paid work require `Idempotency-Key` (001 middleware stores the first response for 24 h).
  Pre-flight estimates multiply the median metered usage of the agent's last 50 runs of the same
  mode (fallback constants per mode) by catalog prices from `pricing`.
- **Rationale**: Principle III; one charge per run keeps the transaction list readable.
- **Alternatives considered**: Charge per LLM call: noisy history, more ledger rows.

## R11. Fan-out, concurrency and progress

- **Decision**: `POST /v1/experiments` inserts the batch and all runs as `pending` in one
  transaction, then enqueues one arq job per run on `textsim`. A Redis semaphore per workspace
  (default 10, setting `sim_max_concurrency`) gates execution; jobs that cannot acquire it
  re-enqueue with a 5 s delay. Batch counters update on each run result. The web app polls every
  3 s while anything is pending or running (TanStack Query `refetchInterval`).
- **Rationale**: Principle VI: no websocket channel, no new queue technology.
- **Alternatives considered**: Server-sent events: more moving parts for a page that tolerates
  3 s staleness.

## R12. Test case import format

- **Decision**: Accept `{"format":"callwright.test_cases.v1","test_cases":[...]}` or a bare
  array. Fields: `user_prompt` (required), `expected_behaviour` (required), `name`, `category`
  (slug), `dynamic_variables`. Unknown categories are rejected per row. Duplicates are detected
  on normalised `user_prompt` plus `expected_behaviour` (trimmed, whitespace collapsed,
  case-folded). Export writes the wrapped form.
- **Rationale**: A versioned wrapper lets the format evolve; bare arrays keep hand-written files
  easy.
- **Alternatives considered**: CSV: multi-line prompts and nested variables make it awkward.

## R13. Privacy of simulation data

- **Decision**: Persona briefs and simulated transcripts are derived from caller data, so they
  are stored like transcripts (encrypted storage, workspace RLS) and purged with the base call's
  retention; standalone persona runs follow workspace transcript retention. Dataset membership
  never extends retention; purged calls show as unavailable.
- **Rationale**: Principle V.
- **Alternatives considered**: Keep briefs forever for reuse: retains personal data past policy.
