# Quickstart: Quality and Evaluations

Validates 007 end to end on a local stack with 001, 002, 003 and 006 in place. Without vendor
keys every model call goes to the deterministic fake adapter, so results are repeatable.

## 1. Prepare

```bash
make up && make migrate      # migrate also syncs the built-in evaluator catalog (or: uv run python -m app.evaluators.registry sync)
make api                     # :8100; without vendor keys every model call uses the deterministic fake adapter
make worker                  # runs the post-call pipeline, evaluate_call and rerun_analysis
# Sign up in the web app (or POST /v1/auth/register), then seed the workspace:
cd services/api && uv run python -m scripts.seed_007 \
  --dsn postgresql://callwright:callwright@localhost:55432/callwright --workspace ws_...
# Prints the agent ids. Creates "Booking desk" (single prompt; variables appointment_booked and
# preferred_day; intent fulfillment on as a headline check), "Clinic flow" (flow agent), and:
# 10 labelled calls for intent_fulfillment (4 both pass, 2 both fail, 2 over-eager, 2 missed),
# 12 unlabelled calls for the review queue (4 mixed, 3 all failed, 5 all passed).
export AGT=agt_...           # the booking_desk id printed above
H="Authorization: Bearer $TOKEN"   # the access token from sign-in
```

## 2. Analysis variables (US1)

```bash
curl -s -X POST -H "$H" -H "Content-Type: application/json" localhost:8100/v1/agents/$AGT/analysis-variables \
  -d '{"name":"party_size","type":"number","description":"People attending"}' | jq .id
curl -s -X POST -H "$H" -H "Content-Type: application/json" localhost:8100/v1/agents/$AGT/analysis-variables \
  -d '{"name":"Preferred Day","type":"string","description":"x"}' | jq .status   # expect 422
# Place a call with "Test agent" on the agent (or drive POST /v1/sessions/web-call, the internal
# claim and events endpoints as tests/integration/test_web_call_flow.py does), then:
CALL=call_...
curl -s -H "$H" localhost:8100/v1/calls/$CALL/analysis | jq '.summary, .sentiment, .values'
```

## 3. Evaluators and runs (US2)

```bash
curl -s -H "$H" localhost:8100/v1/agents/$AGT/eval-settings | jq '[.items[] | {name, enabled, cost_class}]'
# single-prompt agent: 8 checks; audio_silence and latency_slo on by default (the seed also turns
# on intent_fulfillment); anomaly_detection and the other judges off
curl -s -H "$H" "localhost:8100/v1/evaluators?agent_type=flow&kind=builtin" | jq '.items | length'   # 12
curl -s -H "$H" "localhost:8100/v1/evaluators?agent_type=flow&kind=builtin" \
  | jq '[.items[] | select(.enabled_by_default) | .name] | sort'
# ["audio_silence","flow_completion","latency_slo","node_dead_end","stuck_loop_detector"]
curl -s -H "$H" localhost:8100/v1/evaluators/judge-models | jq '[.items[] | select(.is_default) | .model_id]'
EVL=$(curl -s -H "$H" "localhost:8100/v1/evaluators?kind=builtin" | jq -r '.items[] | select(.name=="intent_fulfillment") | .id')
curl -s -X PUT -H "$H" -H "Content-Type: application/json" localhost:8100/v1/agents/$AGT/eval-settings/$EVL \
  -d '{"enabled":true,"overrides":{"sample_rate_pct":150},"is_headline":true}' | jq '.status, .errors'
# expect 422 with field overrides.sample_rate_pct
curl -s -X PUT -H "$H" -H "Content-Type: application/json" localhost:8100/v1/agents/$AGT/eval-settings/$EVL \
  -d '{"enabled":true,"overrides":{"sample_rate_pct":100},"is_headline":true}' | jq .effective_settings
curl -s -X POST -H "$H" -H "Idempotency-Key: qs-007-rerun-000001" localhost:8100/v1/calls/$CALL/evaluations/rerun | jq .run_group_id
curl -s -X POST -H "$H" -H "Idempotency-Key: qs-007-rerun-000002" -o /dev/null -w "%{http_code}\n" localhost:8100/v1/calls/$CALL/evaluations/rerun
# expect 409 while the first group is active
curl -s -H "$H" "localhost:8100/v1/calls/$CALL/evaluations?include_history=true" | jq '.eval_status, [.runs[] | {evaluator_name, evaluator_version, verdict, rationale}]'
```

## 4. Labels (US3)

```bash
curl -s -X PUT -H "$H" -H "Content-Type: application/json" localhost:8100/v1/calls/$CALL/annotations/me -d '{"label":"good","note":"clean booking"}' | jq .label
curl -s -H "$H" "localhost:8100/v1/calls?label=good" | jq '[.items[].call_id] | index("'$CALL'") != null'   # expect true
curl -s -X DELETE -H "$H" -o /dev/null -w "%{http_code}\n" localhost:8100/v1/calls/$CALL/annotations/me   # expect 204
```

## 5. Calibration (US4)

```bash
curl -s -H "$H" localhost:8100/v1/calibration/evaluators | jq '.items[] | select(.evaluator_name=="intent_fulfillment") | {both_pass, both_fail, over_eager, missed, agreement_rate, reading, best_threshold}'
# expect 4, 2, 2, 2, 0.6, "partial"
curl -s -H "$H" localhost:8100/v1/calibration/summary | jq
```

## 6. Custom evaluators (US5)

```bash
curl -s -X POST -H "$H" -H "Idempotency-Key: qs-007-trial-000001" -H "Content-Type: application/json" localhost:8100/v1/evaluators/trial \
  -d '{"evaluator_type":"phrase_check","call_id":"'$CALL'","config":{"pattern":"guarantee(d)?","mode":"forbidden","target":"agent","is_regex":true}}' | jq
curl -s -X POST -H "$H" -H "Content-Type: application/json" localhost:8100/v1/evaluators \
  -d '{"display_name":"No guarantees","description":null,"evaluator_type":"phrase_check","config":{"pattern":"guaranteed","mode":"forbidden","target":"agent"}}' | jq '.name, .current_version'
# "no_guarantees", 1 (name derived from display_name)
# same POST again: expect 409
```

## 7. Review queue (US6)

```bash
curl -s -H "$H" localhost:8100/v1/review/queue/summary | jq   # expect {"random":12,"failed":7,"disagreement":4}
# (test calls from "Test agent" have origin test and never enter the queue)
curl -s -H "$H" "localhost:8100/v1/review/queue?strategy=disagreement" | jq '[.items[] | [.pass_count, .fail_count]]'
```

In the browser, agent quality tab: flip "Turn latency" off and on (saves at once); expand
"Long silences" and confirm the helper default reads 3,000 ms; type 150 into the intent
fulfillment sample rate and confirm Save stays disabled; "Add custom check" shows two template
cards and the form has "Back".

In the browser: `/review`, open the first mixed card, thumbs up, press "Next call", confirm counts
drop to 11 / 6 / 3. `/calibration` shows the matrix card and greys out evaluators under 5 pairs.

## 8. Test suites

```bash
cd services/api
uv run pytest tests/unit/calibration tests/unit/evals tests/unit/evaluators tests/unit/analysis_vars tests/unit/review -q
uv run pytest tests/contract -k "analysis_vars or evaluators or evals or annotations or review or calibration or builtin" -q
uv run pytest tests/integration/test_post_call_quality.py tests/integration/test_judge_injection.py tests/integration/test_seed_quality.py -q
cd ../../apps/web && pnpm exec vitest run src/routes/agents/quality src/routes/calls/quality src/routes/review src/routes/calibration src/routes/evaluators
```
