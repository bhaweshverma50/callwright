# Quickstart: Quality and Evaluations

Validates 007 end to end on a local stack with 001, 002, 003 and 006 in place. Model calls use
the fake LLM client (`LLM_CLIENT=fake`) with recorded fixtures so results are deterministic.

## 1. Prepare

```bash
make up && make migrate
LLM_CLIENT=fake make api worker
python -m services.api.scripts.seed_007 --workspace ws_A
# Creates agent agt_DEMO (single prompt, has tools, no KB), a flow agent, and calibration fixtures:
# 10 labelled calls for intent_fulfillment (4 both pass, 2 both fail, 2 over-eager, 2 missed),
# 12 unlabelled calls for the review queue (4 mixed, 3 all failed, 5 all passed).
export TOKEN=$(python -m services.api.scripts.dev_token --workspace ws_A)
H="Authorization: Bearer $TOKEN"
```

## 2. Analysis variables (US1)

```bash
curl -s -X POST -H "$H" -H "Content-Type: application/json" localhost:8000/v1/agents/agt_DEMO/analysis-variables \
  -d '{"name":"appointment_booked","type":"boolean","description":"True if a slot was confirmed"}' | jq .id
curl -s -X POST -H "$H" -H "Content-Type: application/json" localhost:8000/v1/agents/agt_DEMO/analysis-variables \
  -d '{"name":"Preferred Day","type":"string","description":"x"}' | jq .status   # expect 422
python -m services.voice_worker.tests.harness.run --agent agt_DEMO --script booking_tuesday   # offline scripted call
CALL=$(python -m services.api.scripts.last_call --agent agt_DEMO)
curl -s -H "$H" localhost:8000/v1/calls/$CALL/analysis | jq '.summary, .sentiment, .values'
```

## 3. Evaluators and runs (US2)

```bash
curl -s -H "$H" localhost:8000/v1/agents/agt_DEMO/eval-settings | jq '[.items[] | {name, enabled, cost_class}]'
# expect anomaly_detection enabled, judge evaluators disabled
EVL=$(curl -s -H "$H" "localhost:8000/v1/evaluators?kind=builtin" | jq -r '.items[] | select(.name=="intent_fulfillment") | .id')
curl -s -X PUT -H "$H" -H "Content-Type: application/json" localhost:8000/v1/agents/agt_DEMO/eval-settings/$EVL \
  -d '{"enabled":true,"overrides":{"pass_threshold":0.6},"is_headline":true}' | jq .effective_settings
curl -s -X POST -H "$H" -H "Idempotency-Key: qs-007-rerun-000001" localhost:8000/v1/calls/$CALL/evaluations/rerun | jq .run_group_id
curl -s -X POST -H "$H" -H "Idempotency-Key: qs-007-rerun-000002" -o /dev/null -w "%{http_code}\n" localhost:8000/v1/calls/$CALL/evaluations/rerun
# expect 409 while the first group is active
curl -s -H "$H" "localhost:8000/v1/calls/$CALL/evaluations?include_history=true" | jq '.eval_status, [.runs[] | {evaluator_name, evaluator_version, verdict, rationale}]'
```

## 4. Labels (US3)

```bash
curl -s -X PUT -H "$H" -H "Content-Type: application/json" localhost:8000/v1/calls/$CALL/annotations/me -d '{"label":"good","note":"clean booking"}' | jq .label
curl -s -H "$H" "localhost:8000/v1/calls?label=good" | jq '[.items[].call_id] | index("'$CALL'") != null'   # expect true
curl -s -X DELETE -H "$H" -o /dev/null -w "%{http_code}\n" localhost:8000/v1/calls/$CALL/annotations/me   # expect 204
```

## 5. Calibration (US4)

```bash
curl -s -H "$H" localhost:8000/v1/calibration/evaluators | jq '.items[] | select(.evaluator_name=="intent_fulfillment") | {both_pass, both_fail, over_eager, missed, agreement_rate, reading, best_threshold}'
# expect 4, 2, 2, 2, 0.6, "partial"
curl -s -H "$H" localhost:8000/v1/calibration/summary | jq
```

## 6. Custom evaluators (US5)

```bash
curl -s -X POST -H "$H" -H "Idempotency-Key: qs-007-trial-000001" -H "Content-Type: application/json" localhost:8000/v1/evaluators/trial \
  -d '{"evaluator_type":"phrase_check","call_id":"'$CALL'","config":{"pattern":"guarantee(d)?","mode":"forbidden","target":"agent","is_regex":true}}' | jq
curl -s -X POST -H "$H" -H "Content-Type: application/json" localhost:8000/v1/evaluators \
  -d '{"name":"no_guarantees","display_name":"No guarantees","evaluator_type":"phrase_check","config":{"pattern":"guaranteed","mode":"forbidden","target":"agent"}}' | jq .current_version   # 1
# same POST again: expect 409
```

## 7. Review queue (US6)

```bash
curl -s -H "$H" localhost:8000/v1/review/queue/summary | jq   # expect {"random":12,"failed":7,"disagreement":4}
curl -s -H "$H" "localhost:8000/v1/review/queue?strategy=disagreement" | jq '[.items[] | [.pass_count, .fail_count]]'
```

In the browser: `/review`, open the first mixed card, thumbs up, press "Next call", confirm counts
drop to 11 / 6 / 3. `/calibration` shows the matrix card and greys out evaluators under 5 pairs.

## 8. Test suites

```bash
pytest services/api/tests/unit/calibration services/api/tests/unit/evals services/api/tests/unit/evaluators services/api/tests/unit/analysis_vars services/api/tests/unit/review -q
pytest services/api/tests/contract -k "analysis_vars or evaluators or evals or annotations or review or calibration" -q
pytest services/api/tests/integration/test_post_call_quality.py services/api/tests/integration/test_judge_injection.py -q
pnpm --filter web test -- routes/agents/quality routes/calls/quality routes/review routes/calibration
```
