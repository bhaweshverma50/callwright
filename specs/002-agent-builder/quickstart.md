# Quickstart: Agent Builder

How to verify feature 002 end to end. Requires feature 001 running as in
`specs/001-platform-foundation/quickstart.md` sections 0 to 2 (stack up, a verified user, `$TOKEN`).

```bash
uv run --directory services/api alembic upgrade head                 # adds 0005 to 0007
uv run --directory services/api python -m app.templates.jobs sync    # loads templates/seed/*.yaml
export PROMPT_AI_MODEL=fake                                          # deterministic assistant in dev (llms/adapters fake)
H=(-H "authorization: Bearer $TOKEN" -H 'content-type: application/json')
```

## 1. Automated checks

```bash
uv run --directory services/api pytest tests/unit/agents tests/unit/agent_versions tests/unit/llms tests/unit/voices tests/unit/prompt_ai -q
uv run --directory services/api pytest tests/contract -q -k "agents or agent_versions or templates or llms or voices or prompt_ai"
uv run --directory services/api pytest tests/integration/agents tests/integration/agent_versions tests/integration/templates tests/integration/prompt_ai -q
cd apps/web && pnpm test -- agents && pnpm exec playwright test agents
```

## 2. Catalog (FR-006, FR-007)

```bash
curl -s localhost:8000/v1/llms/catalog "${H[@]}" | jq '.default, [.providers[].models[] | {id, temperature, price_per_min_usd}]'
curl -s localhost:8000/v1/voices/catalog "${H[@]}" | jq '.languages[0], [.tts[].provider], .ambient_sounds[0]'
curl -s "localhost:8000/v1/voices/elevenlabs/voices?search=calm&limit=5" "${H[@]}" | jq '.items[] | {voice_id, name, preview_url}'
```

Expect at least one model with `temperature.fixed`, every entry with a price or `null`, and a
`next_cursor` for paged providers.

## 3. Create and save a single-prompt agent (US1)

UI: `/agents/new` shows two cards and the "cannot be changed later" warning; pick single-prompt,
then "Start from scratch". In the editor:
1. Clear the name, clear the prompt, set webhook to `ftp://x`, click Save: one dialog lists the
   problems for name, prompt and webhook (and voice if cleared), each linking to its field (SC-004).
2. Type a prompt containing `Hello {{customer_name}}, about order {{order_id}}`: both variables
   appear in the variables list with "no default" warnings.
3. Pick a fixed-temperature model: the temperature slider locks with an explanation.
4. Save: toast confirms, URL becomes `/agents/agt_.../edit`, header shows version 1.

API equivalent:

```bash
curl -s "localhost:8000/v1/agents/defaults?type=single_prompt&language=en-US" "${H[@]}" | jq '.call_behavior'
# the blank form; nothing is stored until the first save
AGENT=$(curl -s localhost:8000/v1/agents "${H[@]}" \
  -d '{"name":"Clinic desk","type":"single_prompt","config":{"prompt":"You answer calls for a dental clinic."}}')
ID=$(echo "$AGENT" | jq -r .id); REV=$(echo "$AGENT" | jq -r .draft_revision)   # version 1
CONFIG=$(echo "$AGENT" | jq '.draft_config | .prompt="Hello {{customer_name}}." | .dynamic_variables=[{"name":"customer_name","default":"there"}]')
curl -s -X PUT localhost:8000/v1/agents/$ID/draft "${H[@]}" -H "If-Match: \"$REV\"" \
  -d "{\"config\": $CONFIG, \"note\": \"first prompt\"}" | jq '{created, version: .version.version_number, warnings}'
# created=true, version 2
```

Repeat the same PUT with the new ETag: `created=false`, no version 3 (FR-023). Repeat with the
old ETag: `412` with `code: draft_changed` (FR-015).

Validation without saving:

```bash
curl -s localhost:8000/v1/agents/validate "${H[@]}" -d '{"type":"single_prompt","config":{"schema_version":1}}' | jq '.valid, (.errors | length)'
```

## 4. List, search, duplicate, delete (US2)

```bash
curl -s "localhost:8000/v1/agents?search=clinic" "${H[@]}" | jq '.items[] | {id, name, published_version}'
curl -s "localhost:8000/v1/agents?search=$ID" "${H[@]}" | jq '.total'              # 1
DUP=$(curl -s -X POST localhost:8000/v1/agents/$ID/duplicate "${H[@]}" | jq -r .id)
curl -s localhost:8000/v1/agents/$DUP/versions "${H[@]}" | jq '.total, .items[0].source'   # 1, "duplicate"
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE localhost:8000/v1/agents/$DUP "${H[@]}"  # 204
```

## 5. Versions: compare, publish, restore (US3)

```bash
V=$(curl -s localhost:8000/v1/agents/$ID/versions "${H[@]}")
V1=$(echo "$V" | jq -r '.items[-1].id'); V2=$(echo "$V" | jq -r '.items[0].id')
curl -s "localhost:8000/v1/agents/$ID/versions/$V2/diff?against=$V1" "${H[@]}" | jq '.changes'
# includes {op:"replace", path:"/prompt", ...} and {op:"add", path:"/dynamic_variables[customer_name]", ...}
curl -s -X PUT localhost:8000/v1/agents/$ID/published-version "${H[@]}" -d "{\"version_id\":\"$V2\"}" | jq .published_version
REV=$(curl -s -D - localhost:8000/v1/agents/$ID "${H[@]}" -o /dev/null | awk -F'"' '/^etag/I{print $2}')
curl -s -X POST localhost:8000/v1/agents/$ID/versions/$V1/restore "${H[@]}" -H "If-Match: \"$REV\"" -d '{"note":"roll back"}' \
  | jq '{v: .version.version_number, published: .agent.published_version.version_number}'
# new version 3 with source restore; published stays version 2
```

UI: the history drawer lists 3 versions newest first with a "Published" badge on version 2;
"Compare with draft" shows "System prompt" and "Dynamic variables" with readable labels and a
line diff for the prompt. Restore takes 3 clicks (history, restore, confirm) (SC-008).

Publish blocker: set `tts.provider` to a provider without a pricing row in a test database, save
(allowed), then publish that version: `422` with `code: publish_blocked` and the TTS pointer.

Test snapshot (used by 003): `uv run --directory services/api pytest tests/integration/agent_versions/test_snapshot_for_test.py -q`
confirms the draft's version is reused when unchanged and nothing gets published.

## 6. Cost card (US4)

In the editor, switch the voice model between two options with different rates: the TTS line
and total change within a second (SC-002). Turn noise cancellation off: its line disappears.
Paste a prompt of about 4,000 words: the surcharge-risk notice appears naming the 20,000-token
input allowance. Parity check:

```bash
uv run --directory services/api pytest tests/integration/agents/test_cost_card_parity.py -q
```

## 7. Templates (US5)

```bash
curl -s localhost:8000/v1/templates/categories "${H[@]}" | jq '[.items[].id]'          # 9 categories
T=$(curl -s "localhost:8000/v1/templates?category=healthcare" "${H[@]}" | jq -r '.items[0].id')
curl -s localhost:8000/v1/agents "${H[@]}" -d "{\"name\":\"From template\",\"type\":\"single_prompt\",\"template_id\":\"$T\"}" \
  | jq '{template_id, prompt: .draft_config.prompt[0:80], v: .draft_version.version_number, warnings}'
```

UI: `/agents/templates` shows "Start from scratch" first, chips "All" plus categories; preview
shows prompt and greeting; "Use template" opens the editor pre-filled.

## 8. AI prompt assistant (US6)

```bash
curl -s localhost:8000/v1/prompt-ai/generate "${H[@]}" -H 'Idempotency-Key: qs-1' \
  -d '{"messages":[{"role":"user","content":"A receptionist for a dental clinic that books appointments"}],"current":null}' \
  | jq '{reply: .reply[0:80], has_proposal: (.proposal != null), billed_usd}'
curl -s "localhost:8000/v1/usage" "${H[@]}" | jq '.rows[] | select(.feature=="prompt_generation")'
```

UI: in the editor's assistant tab, ask for a change, click Apply: the prompt updates and the
Save button becomes active; Undo restores the previous text. With balance at zero (set via an
admin `adjustment`), the request is refused with an add-funds message (`402`).

## 9. Isolation

```bash
uv run --directory services/api pytest tests/integration/test_rls_isolation.py -q -k "agents or agent_versions or ambient"
```
