# Quickstart: Issues and Auto-Fix

Validates the loop detect, draft, validate, apply on a local stack with 001-008 running
(API, jobs worker, voice-worker textsim process), a JWT in `$TOKEN` and an LLM provider key on
the workspace. IDs are examples.

## 0. Seed a recurring failure

```bash
cd services/api && uv run alembic upgrade head
# A published single-prompt agent (create it in the app or through POST /agents), then 30 live
# calls on its published version: 8 fail "intent_fulfillment" because the agent quotes a price
# that is not in its price list, 2 fail it for an unrelated reason, 20 pass. The seed switches
# intent fulfillment on for the agent.
uv run python -m app.dev.seed_issues --dsn postgresql://callwright:callwright@localhost:55432/callwright \
  --workspace ws_01J... --agent agt_01J... --calls 30 --failing 8 --other 2
export API=http://localhost:8100/v1 AGENT=agt_01J...
```

Offline (no vendor keys) the fake judge and the text runner's fake agent answer the same way in
both batches, so validation completes with "failed" (+0.0 pp): that proves the plumbing. A real
improvement, and with it section 4 on a live stack, needs real model keys.

## 1. Detect (US1)

```bash
curl -s -X POST $API/issues/detect -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: det-$(date +%s)" -d '{"agent_id":"'$AGENT'"}' | jq '{status, window_days}'
# second request while running -> 409
watch -n 3 "curl -s '$API/issues/detection?agent_id=$AGENT' -H 'Authorization: Bearer $TOKEN' | jq '{status,calls_scanned,issues_created,issues_updated}'"
curl -s "$API/issues?agent_id=$AGENT" -H "Authorization: Bearer $TOKEN" | jq '.items[] | {issue_id, title, affected_call_count, status}'
```

Expected: one issue with 8 affected calls, no issue for the 2-call group. Run detection again:
`issues_created` is 0 and `issues_updated` is 1.

```bash
curl -s "$API/issues?agent_id=$AGENT&window_days=7&scope=real" -H "Authorization: Bearer $TOKEN" | jq '.total'
```

In the browser, changing Window or Source on `/issues` issues a new list request and the address
bar keeps the filters; with no agent chosen, "Detect issues" is disabled with its hint.

## 2. Draft a fix (US2)

```bash
ISS=iss_01J...
curl -s -X POST $API/issues/$ISS/fixes -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: fix-$(date +%s)" -d '{"mode":"ai"}' | jq '{revision, kind, status, rationale}'
# kind defaults to prompt_edit for single-prompt agents
curl -s -X POST $API/issues/$ISS/fixes -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"mode":"manual","kind":"add_guardrail","payload":{"placement":"agent_prompt","rule_text":"Only quote prices listed in the price list. If a price is not listed, say you will confirm it by text."}}' | jq '{revision, is_current}'
```

Try applying now: `curl -s -X POST $API/issues/$ISS/apply ...` returns 409 with
`no_passing_validation`.

## 3. Validate (US3)

```bash
curl -s -X POST $API/issues/$ISS/validate -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: est-$(date +%s)" -d '{"dry_run":true}' | jq .
# expect affected_calls 8, guard_calls up to 10, simulations = 2 x (8 + guard), an estimate
curl -s -X POST $API/issues/$ISS/validate -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: val-$(date +%s)" -d '{}' | jq '{attempt, control_experiment_id, treatment_experiment_id}'
watch -n 5 "curl -s $API/issues/$ISS -H 'Authorization: Bearer $TOKEN' | jq '{status, d: .latest_validation.decision, h: .latest_validation.headline}'"
```

Expected: status `validating`, then `validated` (or `open` with reasons). Open
`http://localhost:5180/issues/$ISS` to see thresholds, the headline row, the per-evaluator table
and links to both batches. Compare one evaluator row with
`GET /experiments/{treatment}/scorecard?baseline=experiment&baseline_experiment_id={control}`.

## 4. Apply (US4)

```bash
curl -s -X POST $API/issues/$ISS/apply -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{}' | jq '{agent_version_id, published, release_notes}'
curl -s "$API/agents/$AGENT/versions?page_size=1" -H "Authorization: Bearer $TOKEN" | jq '.items[0] | {agent_version_id, release_notes, content_hash}'
```

Expected: release notes start with `Fix for iss_...`; the version's content hash equals the
attempt's `variant_config_hash`; a second apply returns 409 `wrong_status`.

Negative check: validate another issue, then publish an unrelated agent edit, then apply:
409 `base_version_changed`.

## 5. Dismiss and follow-up (US5)

```bash
curl -s -X POST $API/issues/iss_01K.../dismiss -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason":"other"}' -o /dev/null -w '%{http_code}\n'   # 422, note required
curl -s -X POST $API/issues/iss_01K.../dismiss -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason":"evaluator_wrong","note":"Rubric flags polite refusals"}' | jq .status
uv run python -m app.dev.seed_issues --dsn ... --workspace ws_01J... --agent $AGENT --calls 12 --failing 0 --other 0   # post-apply calls
curl -s $API/issues/$ISS -H "Authorization: Bearer $TOKEN" | jq .post_apply
```

## 6. Automated checks

```bash
cd services/api
uv run pytest tests/unit/test_validation_rule.py tests/unit/test_issue_clustering.py tests/unit/test_fix_application.py
uv run pytest tests/contract/test_issues_contract.py tests/integration -k issue
```
