# Research: Issues and Auto-Fix

**Feature**: 009-issues-autofix | **Date**: 2026-10-16

Each entry: Decision, Rationale, Alternatives considered.

## R1. Clustering evaluator failures

- **Decision**: Detection job (`issues/detection.py`):
  1. Load failed verdicts in the window for enabled evaluators of the agent (live calls, plus
     simulated calls when asked); collapse turn-scope failures to one row per call and
     evaluator, joining the turn reasons.
  2. Group by `(evaluator_id, flow_node_id or none)`; cap each group at the 2,000 most recent.
  3. Embed each failure's reasoning with the workspace's embeddings adapter from 005 and cache
     the vector in `issue_failure_embeddings` keyed by evaluator result id.
  4. Cluster each group with agglomerative clustering (scikit-learn `AgglomerativeClustering`,
     `metric="cosine"`, `linkage="average"`, `distance_threshold=0.25`).
  5. Keep clusters covering at least 3 distinct calls; order by distinct calls; cap 20 new.
  6. Match each kept cluster to existing issues of the same evaluator and node by centroid
     cosine similarity at least 0.85: open/validating/validated issues are updated; dismissed
     issues get counts only; applied issues produce a new issue with `recurrence_of` when the
     cluster's calls ran on a version created at or after the apply; otherwise update.
  7. For new issues, one LLM call per cluster names it (title up to 80 chars, description,
     suspected cause) from up to 8 representative reasons (closest to the centroid).
- **Rationale**: Deterministic given the same vectors, so re-runs on unchanged data create no
  issues (SC-004). Grouping by evaluator and node first keeps clusters interpretable and maps
  directly onto which fix kinds apply.
- **Alternatives considered**: LLM-only theming over all reasons: costly, non-deterministic,
  hard to deduplicate. k-means: needs k up front. A hand-written average-linkage loop: possible,
  but a maintained library is simpler to trust.

## R2. Baseline for validation: control arm instead of originals

- **Decision**: Validation runs two batches over the same calls through 008: control (published
  version, `target.type = version`) and treatment (`target.type = variant`). The keep rule
  compares treatment with control.
- **Rationale**: Affected calls were chosen because they failed, so their original pass rate is
  near 0% by construction; any re-simulation would look like an improvement. Simulation also
  differs from live audio (text mode, mocks), and the control arm cancels that difference.
- **Alternatives considered**: Compare treatment with the originals (the reference product's
  approach): biased, as above. Several repetitions per arm: better statistics but triples
  cost; noted as a later option.

## R3. Keep rule math (test-first, Principle VII)

- **Decision**: Pure module `issues/validation_rule.py` over pair counts from 008's
  `pair_verdicts()`:
  - Affected set A, guard set G. For evaluator e and set S, the paired calls are those with a
    verdict for e in both arms at the same evaluator version.
  - `rate(arm) = passes / n` over paired calls; `delta = rate(T) - rate(C)` as `Fraction`.
  - Inconclusive if `n(headline, A) < min_sample` or failed treatment runs exceed 20% of
    treatment runs.
  - Failed if `delta(headline, A) < min_improvement / 100`.
  - Failed if any check `delta(e, A union G) < -max_regression / 100` for e not headline, or
    `delta(headline, G) < -max_regression / 100`, where the check only counts when
    `n >= min_sample`; checks below the sample are reported as `insufficient_data`.
  - Otherwise passed. Boundaries are inclusive for passing (exactly +10 passes, exactly -5 does
    not block).
  - Reasons are a list of `{code, evaluator_id?, set?, delta_pp?, n?}` with codes
    `insufficient_sample`, `too_many_failed_runs`, `improvement_below_threshold`,
    `regression`, and `insufficient_data` (informational).
- **Rationale**: Exact fractions avoid float drift at the 10-point boundary; inclusive bounds
  match the wording "at least 10 points" and "beyond a threshold".
- **Alternatives considered**: Statistical tests (McNemar): more principled but opaque to users
  and unstable at n = 5-20; can be added as an extra informational column later.

## R4. Building the variant from a fix

- **Decision**: `issues/fixes.py` applies a fix payload to the published version's full snapshot
  (from 002) and returns a new snapshot; it fails with `redraft_needed` when the payload's
  `current_*` value does not equal the snapshot value (for example the node was edited or
  removed). Kind handling:
  - `prompt_edit`: `config.prompt` replaced.
  - `node_prompt_edit`: flow node `instructions` replaced by node id.
  - `add_guardrail`: rule appended under a "Rules" heading in the prompt, one node, or every
    `agent` node (idempotent: identical rule text is not added twice).
  - `tool_description_edit`: `tools[tool_id].description` replaced in the snapshot.
  - `transition_condition_edit`: edge `handoff_condition` replaced by edge id.
  - `add_transition`: edge appended; label must be unique per source node (004 rule).
  - `node_tool_attachment`: node `tool_ids` updated; tools must be attached to the agent.
  - `kb_attach`: `config.kb_ids` extended; advisory when `kb_ids_to_attach` is empty.
  The resulting snapshot is validated with 002/004 validators and hashed with 008's canonical
  hash, then passed to 008 as the variant target.
- **Rationale**: One function produces both the validation variant and the applied version, so
  the hash check in apply (FR-021) is a real guarantee.
- **Alternatives considered**: Re-derive the change at apply time from the live entities: the
  applied configuration could differ from what was validated.

## R5. Apply mechanics

- **Decision**: In one database transaction: lock the agent row; check FR-020 preconditions
  (latest attempt for the current revision passed; published version id equals
  `base_agent_version_id`; draft content hash equals the base version hash); for a shared tool,
  create an agent-specific copy through 005's tools service and rewrite the snapshot's tool id;
  call 002's `create_version(agent_id, snapshot, release_notes, publish)`; also write the change
  into the agent's draft so the editor shows it; mark the revision `applied` and the issue
  `applied`. Verify the new version's content hash equals the validated hash (the tool copy
  changes only the tool id, which is excluded from the hash comparison via a normalisation that
  maps the copied tool id back to the original).
- **Rationale**: Locking prevents a concurrent publish from slipping between check and write.
- **Alternatives considered**: Edit the shared tool in place: silently changes other agents
  that were never validated.

## R6. Fix drafting prompt

- **Decision**: One LLM call through the provider-agnostic LLM adapter used by 002's prompt AI,
  with a JSON schema per kind. Context: issue title and description, up to 8 sample transcripts
  trimmed to the failing turns plus 2 turns of context, evaluator reasoning, the relevant part
  of the snapshot (prompt, node, tool or edges), allowed kinds and user guidance. When kind is
  omitted, the schema is a tagged union over allowed kinds and the model must pick one. Model:
  workspace `fix_model` setting, defaulting to the analysis model. Billed `issues.draft_fix`.
- **Rationale**: Structured output makes before/after diffs exact and the payload applicable.
- **Alternatives considered**: Free-text suggestions: not applicable without a second parse.

## R7. Guard calls

- **Decision**: Up to 10 most recent completed live calls of the agent in the detection window,
  not in the issue's samples, with a passing headline verdict; if fewer exist, use what exists
  (zero is allowed; regression checks then rely on affected calls only and the evidence says so).
- **Rationale**: Detects fixes that help the target case but break normal calls, at bounded
  cost.
- **Alternatives considered**: Use a dataset chosen by the user: useful later; adds a required
  input to a one-click flow.

## R8. Post-apply tracking

- **Decision**: Computed on read for applied issues: headline pass rate over live calls of the
  base version in the `window_days` before `applied_at`, and over live calls of the applied
  version after `applied_at`; shown when the after side has at least 10 calls. Not stored.
- **Rationale**: Cheap query; no scheduler needed (Principle VI).
- **Alternatives considered**: Nightly job writing snapshots: extra moving part for one panel.

## R9. Billing and idempotency

- **Decision**: `issues.detect` charged once per detection run (embeddings and naming tokens),
  `issues.draft_fix` once per AI draft, via `billing.charge_feature()` keyed by detection run id
  or `(issue_id, revision)`. Validation creates two 008 batches with `source = issue_validation`
  and `issue_id`, so their simulation and evaluation charges appear under 008 and 007 keys.
  `Idempotency-Key` required on detect, AI drafting, validate and draft-and-validate.
- **Rationale**: Principle III; validation cost stays visible per batch.
- **Alternatives considered**: A single "auto-fix" charge: hides what was spent where.

## R10. No new public ID prefixes

- **Decision**: Fix revisions and validation attempts are addressed by issue id plus an integer
  (`revision`, `attempt`); detection runs are addressed by agent ("latest detection").
- **Rationale**: architecture.md defines the prefix list; nested numbering is enough for
  objects that never exist outside their issue.
- **Alternatives considered**: New prefixes (`fix_`, `val_`): would change the shared
  convention.
