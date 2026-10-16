# DELTA resolution: findings tagged 007 to 010

Resolution of the live-walkthrough findings in `DELTA.md` tagged [007], [008], [009] and [010]
(2026-10-16). Multi-part findings are split into one row per decision. Evidence: the walkthrough
notes in this folder, `blocked-requests.json`, `data/`, `research/live/evaluator-catalog.json` and
`research/live/gs-Quality_Checks.txt`. Spec folders are abbreviated: 007 = `specs/007-quality-evals`,
008 = `specs/008-testing-simulation`, 009 = `specs/009-issues-autofix`, 010 = `specs/010-channels`.

| Finding (short) | Spec | Decision | Where applied (file + FR/task ids) or reason |
|---|---|---|---|
| Built-in catalog is 12 evaluators, not our 7 (no `flow_step_completion`; `kb_relevance` is per call) | 007 | ADOPT | 007 spec.md FR-006 rewritten to the exact 12; data-model.md "Built-in catalog" table; research.md R3 rewritten; contracts/evaluators.yaml examples; plan.md source tree; tasks T032 (edited), T027 (edited), T075 golden catalog test |
| `audio_silence` reads the recording, not the transcript | 007 | ADOPT | FR-040, edge case, US2 scenario 15; research R12; result items `start_ms`/`duration_ms` (data-model, evals.yaml); tasks T072, T076, T081 |
| `latency_slo` scored per turn on every call | 007 | ADOPT | FR-041, edge case; data-model item rules; tasks T078 |
| Evaluator types `anomaly`, `class`, `audio_quality`, `process_reward` | 007 | ADOPT | FR-033 (output kind); data-model `evaluators.output_kind`; evaluators.yaml and evals.yaml `output_kind`; task T074 |
| Flow-only checks: flow_completion, node_dead_end, stuck_loop_detector, transition_correctness (shuffled alternatives, per-node attribution) | 007 | ADOPT | FR-006, FR-034, FR-043, US2 scenario 9; FR-026 and calibration.yaml per-node rows; research R3 and R7; tasks T077 |
| Anomaly detection is KNN over embeddings (threshold, window_days, min_sample_size, knn_k, backfill_per_run; "insufficient data") | 007 | ADOPT | FR-035, FR-042, edge case; data-model `call_embeddings`; research R13; plan Complexity Tracking; tasks T074, T078, T082 |
| On by default on a new flow agent: flow completion, long silences, node dead ends, stuck loops, turn latency; judges and anomaly off | 007 | ADOPT | FR-034, FR-008 (edited), US2 scenarios 1 and 9; data-model `enabled_by_default`; quickstart section 3; task T075 |
| Every config field with type, range and default | 007 | ADOPT | FR-035; data-model catalog table; settings field type `int` added (evaluators.yaml) |
| Judge model options: one model only for every judge | 007 | ADOPT | FR-036 (pick list from the platform judge model list, v1 one default model); `GET /v1/evaluators/judge-models` in evaluators.yaml; research R15; tasks T073, T084 |
| Intent fulfillment sample rate (1 to 100, default 100) | 007 | ADOPT | FR-035, FR-037 (deterministic, not charged, reruns and simulations bypass), US2 scenario 12; skip reason `not_sampled` (data-model, evals.yaml); research R14; tasks T079, T083 |
| Long silences helper says default 5000 ms while the field default is 3000 ms | 007 | IMPROVE | FR-038 (helper shows the schema default), US2 scenario 14; `{default}` helper placeholder in data-model; research R15; task T085 |
| Sample rate 150 accepted by the form (schema max 100) | 007 | IMPROVE | FR-038, US2 scenario 10; evals.yaml 422 with `errors[]`; quickstart section 3; tasks T080, T085 |
| Stuck loops whole number 2 to 10 rendered as a plain text box | 007 | IMPROVE | FR-038, US2 scenario 11 (stepper); `int` field type; task T085 |
| Transition correctness judge model is free text | 007 | IMPROVE | FR-036 (never free text), US2 scenario 11; `options_source: judge_models`; task T084 |
| Toggle and Save settings both PUT the full `{enabled, config}` | 007 | ADOPT | FR-039; evals.yaml PUT description; data-model note under `agent_eval_settings`; edge case on concurrent saves |
| Per-card Discard / Save settings while editing | 007 | ADOPT | FR-039, US2 scenario 13; task T085 |
| Custom check is two steps (template cards, then form with Back) | 007 | ADOPT | FR-044, US5 scenario 6; task T088 |
| Phrase check sends `description: null` when empty | 007 | ADOPT | FR-044, US5 scenario 7; quickstart section 6; task T086 |
| Create enabled once name and pattern (or question) are filled | 007 | ADOPT | FR-044, US5 scenario 6; task T088 |
| Custom check has one "Name" field (no separate machine name) | 007 | ADOPT | FR-044 (machine name derived), US5 scenario 7; evaluators.yaml `CustomEvaluatorInput.name` optional; tasks T086, T087 |
| Custom judge fields: question and judge model (single model) | 007 | ADOPT | Already in FR-009 (we keep `pass_when` as a superset); judge model list per FR-036 |
| Analysis variable name: snake_case advised but not enforced ("Customer Mood" sent as is) (tagged [005], handed to 007) | 007 | IMPROVE | FR-045 (form normalises to snake_case and shows the result; API keeps rejecting invalid names per FR-001), US1 scenario 7; data-model `analysis_variables.name`; analysis_vars.yaml `AnalysisVariableInput` description; task T090 |
| Analysis variable "Predefined Choices" stays visible for Boolean and Number (tagged [005], handed to 007) | 007 | IMPROVE | FR-046 (choices only for the fixed-set type, rejected otherwise), US1 scenario 8; data-model `analysis_variables.choices`; analysis_vars.yaml; tasks T089, T090 |
| Analysis variable Save disabled until a name is typed; description optional (tagged [005], handed to 007) | 007 | ADOPT | FR-046 (Save enabled only when name, type and description are valid); description stays required (FR-001) because it steers extraction |
| Calibration `min_sample_for_signal` = 5 | 007 | ADOPT | Already present: FR-028, FR-031, calibration.yaml `const: 5`; no change needed |
| `/tests/categories` returns a colour per category | 008 | ADOPT | FR-032; data-model `test_categories.color`; test_cases.yaml `TestCategory.color` (required) and create `color`; task T090 |
| Categories sorted by name | 008 | ADOPT | FR-032, US1 scenario 9; test_cases.yaml list description; data-model ordering note; quickstart section 1; task T090 |
| Create dialog defaults to Bad Behavior | 008 | ADOPT | Generalised in FR-032: preselect the filtered category, else the first listed (alphabetical gives the same result); task T090 |
| Generate dialog clamps count to 1..20 | 008 | ADOPT | FR-004 already had the range; FR-033 and US1 scenario 7 add the clamping; task T091 |
| Generate button label pluralises | 008 | ADOPT | FR-033, US1 scenario 7; task T091 |
| "All Categories" sends `category_id: null` | 008 | ADOPT | Already in test_cases.yaml (`category` nullable); FR-033 makes it the default choice; task T091 |
| Guidance placeholder text | 008 | SKIP | Reference copy text; we write our own placeholder |
| Testing page works for flow agents too | 008 | ADOPT | FR-034, US1 scenario 8; task T092 |
| Simulations agent filter is client side; GETs use a fixed `limit=50` | 008 | IMPROVE | FR-035 (server-side filter, refetch, paging, totals), US3 scenario 6; contract already has `agent_id`; task T093 |
| No way to start a simulation from the Simulations page | 008 | IMPROVE | FR-035 "New simulation" for standalone persona runs (otherwise unreachable for agents with no calls), US4 scenario 4; plan.md file list; task T094 |
| New dataset dialog has no agent field (API supports `agent_id`) | 008 | IMPROVE | FR-036 (agent required in the form), US5 scenario 6; datasets.yaml already requires `agent_id`; quickstart section 5; task T095 |
| Empty dataset name shows an inline error | 008 | ADOPT | FR-036 (own message text), US5 scenario 6; task T095 |
| Dataset items loaded with a fixed `limit=500` | 008 | IMPROVE | FR-036 paging with total, US5 scenario 7 (datasets hold up to 1,000); task T095 |
| Issues Window and Source filters do not refetch the list | 009 | IMPROVE | FR-026, US1 scenario 6; issues.yaml `window_days` list parameter; data-model index and filter note; tasks T059, T060, T061; quickstart section 1 |
| Source only changes the Detect flag, not the list | 009 | IMPROVE | FR-026 (source filters the list and sets the next detection scope); task T061 |
| Detect disabled until an agent is chosen | 009 | ADOPT | FR-027 (plus a hint explaining why), US1 scenario 7; task T061 |
| Status options shown as lower-case raw values | 009 | IMPROVE | FR-027 readable labels mapped to the raw values, US1 scenario 7; task T061 |
| Page eyebrow "CHANNELS" but sidebar "Phone Numbers" | 010 | IMPROVE | FR-039 (one name, "Channels"), US1 scenario 11; plan.md page comment; task T082 |
| One fixed platform origination URI with copy button | 010 | ADOPT | Already present: FR-005, research R3, `GET /v1/phone-numbers/sip-settings`; no change |
| Import validation: E.164 message; host or IP only, not a full SIP URI | 010 | ADOPT | FR-040, US1 scenario 9 (own wording). We keep FR-002's friendlier rule of stripping a bare `sip:` scheme and reject user parts or paths; task T081 |
| Empty import submit shows no messages | 010 | IMPROVE | FR-040, US1 scenario 8; task T081 |
| Import payload carries a client-supplied `user_id` | 010 | IMPROVE | FR-041, US1 scenario 10; phone_numbers.yaml already `additionalProperties: false`; quickstart section 2; task T080 |
| WhatsApp dialog placeholders | 010 | SKIP | Reference copy text; our placeholders are written in T085 |
| Cloud API version defaults to 23.0 | 010 | ADOPT | Already in data-model (`graph_api_version` default from settings) and `GET /v1/whatsapp/settings`; FR-042 prefills it, US4 scenario 10; task T085 |
| One shared webhook URL for all WhatsApp channels | 010 | ADOPT | Already in research (single callback URL); FR-042 shows it read-only with copy; task T085 |
| Docs icon link to the platform's setup guide | 010 | ADOPT | FR-042, US4 scenario 10; task T085 |
| Phone Number ID not validated as numeric ("abc" accepted) | 010 | IMPROVE | FR-040, US4 scenario 9; whatsapp.yaml already has `^\d{5,32}$`, 422 now returns field `errors` (`ValidationProblem`); tasks T083, T085 |
| Generic "failed, try again" message on WhatsApp create | 010 | IMPROVE | FR-042, US4 scenario 11; whatsapp.yaml 502 `whatsapp-unreachable`; tasks T083, T084, T085 |

## Totals

ADOPT 33, IMPROVE 18, SKIP 2 (53 rows from 17 findings: 16 tagged 007 to 010 plus one tagged
[005] handed over to 007).

## Architecture notes raised (not edited here)

- `audio_silence` reads the finished recording during the post-call `evaluate` step. Architecture
  section 6 does not order `evaluate` after recording egress completes; it should say that
  `evaluate` waits for (or re-queues until) the recording object is finalised, and that a call
  with no recording gives "not applicable".
- `call_embeddings` (pgvector, owned by 007) is a second pgvector use besides knowledge-base
  chunks; embedding usage for it is recorded with raw cost and zero billable amount, which needs
  001's `charge_feature` (or usage recording) to accept a zero billable amount.
- PyAV and numpy join the API image (jobs worker) for recording analysis.
- 010 task T082 edits the shell navigation file owned by 001; add it to the expected shared-file
  edits list in architecture section 3.
