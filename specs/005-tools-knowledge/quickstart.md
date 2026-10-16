# Quickstart: Tools and Knowledge (005)

Validation walkthrough for a developer once tasks are implemented. Assumes 001 to 003 are
running locally (`docker compose up` for Postgres 16 with pgvector, Redis, MinIO; API on
`:8000`; voice worker connected to a local LiveKit dev server) and a signed-in user's JWT in
`$TOKEN`, a test agent id in `$AGENT`.

## 1. Call-control tools (US1)

```bash
# Create an end-call tool and a static cold transfer tool
curl -s -X POST localhost:8000/v1/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
  "type":"end_call","name":"end_call","description":"Use when the caller says they are done.",
  "config":{"message":"Thanks for calling, goodbye."}}'

curl -s -X POST localhost:8000/v1/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
  "type":"transfer_call","name":"transfer_to_human","description":"Use when the caller asks for a person.",
  "config":{"routing_type":"static","number":"+14155550100","transfer_type":"cold"}}'

# Reserved name is rejected (422)
curl -s -X POST localhost:8000/v1/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"type":"end_call","name":"kb_search","description":"x","config":{}}'

# Attach both to the agent draft
curl -s -X PUT localhost:8000/v1/agents/$AGENT/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"tool_ids":["tool_...","tool_..."]}'
```

Run the harness scenarios (scripted caller, SIP channel simulated):

```bash
cd services/voice-worker
pytest tests/harness -k "tools_end_call or tools_transfer_cold or tools_press_digit"
```

Expected: end-call scenario ends with `agent_hangup` and the goodbye line in the transcript;
transfer scenario ends with `call_transfer`; a `tool_call` event exists for each.

## 2. HTTP tool with a secret and mapping (US2)

```bash
curl -s -X POST localhost:8000/v1/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
  "type":"http","name":"check_availability","description":"Look up the next free slot for a date.",
  "config":{
    "method":"POST","url":"https://httpbin.org/anything/slots",
    "headers":[{"name":"Authorization","value":"Bearer sk_test_abcd1234","secret":true}],
    "parameters":{"type":"object","properties":{"date":{"type":"string"}},"required":["date"]},
    "response_mappings":[{"variable_name":"echo_date","json_path":"json.date"}],
    "timeout_ms":3000}}'
```

Check: the response shows the header with `value: null`, `masked_value: "****1234"`.

```bash
curl -s -X POST localhost:8000/v1/tools/test-run -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"tool_id":"tool_...","arguments":{"date":"2026-10-20"}}'
```

Check: `http_status` 200, `mapped_variables.echo_date` = "2026-10-20", request headers show
`****1234`. Repeat with URL `http://169.254.169.254/latest` and expect `blocked_address`.

## 3. Upload documents (US3)

```bash
curl -s -X POST localhost:8000/v1/knowledge-bases -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Clinic policies","description":"Refunds, hours, insurance"}'

curl -s -X POST localhost:8000/v1/knowledge-bases/$KB/documents -H "Authorization: Bearer $TOKEN" \
  -F file=@services/api/tests/fixtures/knowledge/refund_policy.pdf
```

Poll `GET /v1/knowledge-bases/$KB/documents/$DOC` until `status` is `ready` (under 30 s for the
fixture). Upload the same file again: expect 409 `duplicate_document`. Upload
`tests/fixtures/knowledge/oversize_21mb.pdf`: expect 413. Upload `notes.txt` renamed to `.pdf`:
expect 415. `GET .../url` returns a URL that opens the PDF and fails after 10 minutes.

## 4. Retrieval during calls (US4)

```bash
curl -s -X POST localhost:8000/v1/knowledge-bases/$KB/search -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"how long do refunds take"}'
curl -s -X PUT localhost:8000/v1/agents/$AGENT/knowledge-bases -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "{\"kb_ids\":[\"$KB\"]}"
cd services/voice-worker && pytest tests/harness -k kb_refund_question
```

Expected: the preview's top result is the refund paragraph with page number; the harness call
shows a `kb_search` tool event and the agent's answer contains "14 days" (fixture value).

## 5. Simulation mocks (US5)

```bash
curl -s localhost:8000/v1/agents/$AGENT/tools/mock-coverage -H "Authorization: Bearer $TOKEN"
# lists check_availability; then set a mock
curl -s -X PATCH localhost:8000/v1/tools/$TOOL -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"mock_response":"{\"json\":{\"date\":\"2026-10-20\"}}"}'
cd services/voice-worker && pytest tests/harness -k tools_http_simulated
```

Expected: coverage `ready: true`; the simulated scenario makes no outbound request (asserted by
the harness HTTP stub) and its event has `mocked: true`.

## 6. Latency gates (Principle II)

```bash
cd services/voice-worker
python -m tests.harness.bench.bench_tool_dispatch --iterations 500    # p95 <= 50 ms
python -m tests.harness.bench.bench_kb_search --iterations 500        # p95 <= 300 ms, max <= 800 ms
python -m tests.harness.bench.bench_call_set_tools                    # no p50/p95 regression > 5%
```

Each script writes JSON next to `baseline.json` and exits non-zero when a gate fails.
