# Quickstart: Tools and Knowledge (005)

Validation walkthrough for a developer once tasks are implemented. Assumes 001 to 003 are
running locally (see the [003 quickstart](../003-voice-runtime/quickstart.md): Postgres 16 with
pgvector and Redis from `make up`, API on `:8100`, jobs worker, voice worker connected to a local
LiveKit dev server) and a signed-in user's JWT in `$TOKEN`, a test agent id in `$AGENT`.
Without an `OPENAI_API_KEY` knowledge ingestion and search use the offline fake embedder.

The upload fixtures are built in code (`tests/fixtures/knowledge`); write them out first:

```bash
mkdir -p /tmp/cw-kb && cd services/api && uv run python -c "
import tests.fixtures.knowledge as fx
from pathlib import Path
d = Path('/tmp/cw-kb')
(d / 'refund_policy.pdf').write_bytes(fx.refund_policy_pdf())
(d / 'oversize_21mb.pdf').write_bytes(fx.oversize())
(d / 'notes.pdf').write_bytes(b'Opening hours are 9 to 5.\\n')" && cd ../..
```

## 1. Call-control tools (US1)

```bash
# Create an end-call tool and a static cold transfer tool
curl -s -X POST localhost:8100/v1/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
  "type":"end_call","name":"end_call","description":"Use when the caller says they are done.",
  "config":{"message":"Thanks for calling, goodbye."}}'

curl -s -X POST localhost:8100/v1/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
  "type":"transfer_call","name":"transfer_to_human","description":"Use when the caller asks for a person.",
  "config":{"routing_type":"static","number":"+14155550100","transfer_type":"cold"}}'

# Reserved name is rejected (422)
curl -s -X POST localhost:8100/v1/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"type":"end_call","name":"kb_search","description":"x","config":{}}'

# Attach both to the agent draft
curl -s -X PUT localhost:8100/v1/agents/$AGENT/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"tool_ids":["tool_...","tool_..."]}'
```

Run the harness scenarios (scripted caller, SIP channel simulated):

```bash
cd services/voice-worker
uv run pytest tests/harness -k "tools_end_call or tools_transfer_cold or tools_press_digit"
```

Expected: end-call scenario ends with `agent_hangup` and the goodbye line in the transcript;
transfer scenario ends with `call_transfer`; a `tool_call` event exists for each.

## 2. HTTP tool with a secret and mapping (US2)

```bash
curl -s -X POST localhost:8100/v1/tools -H "Authorization: Bearer $TOKEN" \
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
curl -s -X POST localhost:8100/v1/tools/test-run -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"tool_id":"tool_...","arguments":{"date":"2026-10-20"}}'
```

Check: `http_status` 200, `mapped_variables.echo_date` = "2026-10-20", request headers show
`****1234`. Repeat with URL `http://169.254.169.254/latest` and expect `blocked_address`.

## 3. Upload documents (US3)

```bash
curl -s -X POST localhost:8100/v1/knowledge-bases -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Clinic policies","description":"Refunds, hours, insurance"}'

curl -s -X POST localhost:8100/v1/knowledge-bases/$KB/documents -H "Authorization: Bearer $TOKEN" \
  -F file=@/tmp/cw-kb/refund_policy.pdf
```

Poll `GET /v1/knowledge-bases/$KB/documents/$DOC` until `status` is `ready` (under 30 s for the
fixture). Upload the same file again: expect 409 `duplicate_document`. Upload
`/tmp/cw-kb/oversize_21mb.pdf`: expect 413. Upload `/tmp/cw-kb/notes.pdf` (plain text named
`.pdf`): expect 415 (a Word file named `.pdf` is accepted as Word: types are sniffed from the content).
`GET .../url` returns a URL that opens the PDF and fails after 10 minutes.

## 4. Retrieval during calls (US4)

```bash
curl -s -X POST localhost:8100/v1/knowledge-bases/$KB/search -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"query":"how long do refunds take"}'
curl -s -X PUT localhost:8100/v1/agents/$AGENT/knowledge-bases -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "{\"kb_ids\":[\"$KB\"]}"
cd services/voice-worker && uv run pytest tests/harness -k kb_refund_question
```

Expected: the preview's top result is the refund paragraph with page number; the harness call
shows a `kb_search` tool event and the agent's answer contains "14 days" (fixture value).

## 5. Simulation mocks (US5)

Attach the HTTP tool from section 2 too (`PUT /v1/agents/$AGENT/tools` with all three ids);
coverage only lists attached tools.

```bash
curl -s localhost:8100/v1/agents/$AGENT/tools/mock-coverage -H "Authorization: Bearer $TOKEN"
# ready: false, missing lists check_availability; then set a mock
curl -s -X PATCH localhost:8100/v1/tools/$TOOL -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"mock_response":"{\"json\":{\"date\":\"2026-10-20\"}}"}'
cd services/voice-worker && uv run pytest tests/harness -k tools_http_simulated
```

Expected: coverage `ready: true`; the simulated scenario makes no outbound request (asserted by
the harness HTTP stub) and its event has `mocked: true`.

## 6. Latency gates (Principle II)

```bash
cd services/voice-worker
uv run python -m tests.harness.bench.bench_tool_dispatch --iterations 500  # p95 <= 50 ms
uv run python -m tests.harness.bench.bench_call_set_tools                  # no p50/p95 regression > 5%
# kb_search runs against Postgres in the API suite: p95 <= 300 ms, max <= 800 ms
cd ../api && KB_BENCH_CHUNKS=10000 uv run pytest tests/integration/test_kb_search_latency.py -q
```

The two worker scripts print JSON and exit non-zero when a gate fails.

## 7. Live walkthrough deltas (FR-043 to FR-048)

```bash
curl -s localhost:8100/v1/tools/presets -H "Authorization: Bearer $TOKEN" | jq '[.items[].preset_id]'
# expect end_call_polite, transfer_to_person, press_digit_ivr, http_check_availability

# Outdated extra field is rejected (422 naming transfer_option)
curl -s -X POST localhost:8100/v1/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
  "type":"transfer_call","name":"transfer_legacy","description":"x",
  "config":{"routing_type":"static","number":"+14155550100","transfer_type":"warm","transfer_option":{"type":"warm_transfer"}}}'

# Canned response on a non-http tool is rejected (422)
curl -s -X POST localhost:8100/v1/tools -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"type":"end_call","name":"bye","description":"x","config":{},"mock_response":"ok"}'

# Upload with a display name (into a new knowledge base: the same file in $KB is a 409 duplicate)
curl -s -X POST localhost:8100/v1/knowledge-bases/$KB2/documents -H "Authorization: Bearer $TOKEN" \
  -F file=@/tmp/cw-kb/refund_policy.pdf -F display_name="Refund policy 2026" | jq .display_name
```

Browser: the HTTP tool form refuses "notaurl" inline and offers the same methods as a flow webhook
node; the attach dialog with no knowledge base offers create and upload, and Confirm stays
disabled until the selection changes.
