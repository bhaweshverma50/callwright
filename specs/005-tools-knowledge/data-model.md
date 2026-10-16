# Data Model: Tools and Knowledge (005)

All tables live in Postgres 16, carry `workspace_id`, and have RLS enabled with the standard
policy `workspace_id = current_setting('app.workspace_id')`. IDs are prefixed ULIDs from
`core/ids.py`. Timestamps are `timestamptz`. Migration:
`services/api/app/migrations/versions/005_tools_knowledge.py` (forward-only).

## 1. Tool (`tools`)

| Column | Type | Rules |
|---|---|---|
| id | text PK | `tool_` prefix |
| workspace_id | text FK workspaces | RLS |
| type | text | `end_call`, `transfer_call`, `press_digit`, `http`; immutable after insert |
| name | text | `^[a-z][a-z0-9_]{0,63}$`; not `kb_search`; not prefixed `route_to_` |
| description | text | 1 to 1,000 chars; becomes the LLM function description |
| config | jsonb | Type-specific, validated by `ToolConfig` discriminated union (below) |
| mock_response | text null | Up to 16 KB; used in simulations |
| created_by | text FK users | |
| created_at, updated_at | timestamptz | |

Indexes: `(workspace_id, type)`, `(workspace_id, lower(name))` (not unique: uniqueness is per
attached set). Delete is hard delete after detaching from drafts.

### Type-specific config (Pydantic models in `tools/schemas.py`)

**EndCallConfig**: `message` (string, optional, max 500).

**TransferSpec** (shared with 004 transfer nodes):

| Field | Type | Default | Rules |
|---|---|---|---|
| routing_type | `static` \| `dynamic` | `static` | |
| number | string | | Required for static; E.164 `^\+[1-9]\d{6,14}$` |
| routing_instructions | string | | Required for dynamic; max 2,000; appended to the function description |
| allowed_numbers | string[] | [] | Optional E.164 allow-list for dynamic routing, max 50 |
| transfer_type | `cold` \| `warm` | `cold` | |
| warm_transfer | object | null | Required when warm: `handoff_type` `private` \| `public`, `briefing_message_type` `static` \| `prompt`, `briefing_message` (max 1,000) |
| hold_message | string | "Please hold while I connect you." | max 500 |
| ring_timeout_s | int | 30 | 5 to 120 |

LLM function shape: static has no parameters; dynamic has `{destination: string (E.164)}`.

**PressDigitConfig**: `delay_ms` (int, default 1000, 0 to 10000), `cooldown_ms` (int, default
5000, 0 to 60000). LLM function parameters `{digits: string, pattern ^[0-9*#]{1,20}$}`.

**HttpToolConfig** = `parameters` + `HttpRequestSpec`:

| Field | Type | Default | Rules |
|---|---|---|---|
| parameters | JSON Schema object | `{type: object, properties: {}, required: []}` | Must be `type: object`; validated as Draft 2020-12; max depth 5, max 30 properties |
| method | `GET` \| `POST` \| `PUT` \| `PATCH` \| `DELETE` | `POST` | |
| url | string | | Required; `https://` (http allowed only when `ENV=development`); `{{var}}` placeholders allowed in path and query |
| headers | HeaderSpec[] | `[{name: "Content-Type", value: "application/json", secret: false}]` | Max 20; names per RFC 9110 token |
| body_template | JSON value \| null | null | null means "send arguments" (FR-016); placeholders in string values |
| timeout_ms | int | 8000 | 1000 to 30000 |
| response_mappings | {variable_name, json_path}[] | [] | `variable_name` snake_case, max 20; `json_path` dot path with `[n]` |
| speak_during_execution | bool | true | |
| execution_message | string | "One moment while I check that." | max 300; spoken only after 400 ms |

**HeaderSpec**: `name`, `value` (write-only for secrets; null on read when secret), `secret`
(bool), `secret_ref` (read-only, `secrets.id`), `masked_value` (read-only, `****` + last 4).
Update rule: secret header with `value` absent or null keeps the existing `secret_ref`; a new
`value` replaces the secret (old secret row deleted); switching `secret` to false deletes the
secret row and stores the plain value.

### ToolSpec (snapshot form)

What `resolve_for_snapshot` returns and what AgentVersion stores: `{tool_id, type, name,
description, config, mock_response}` where every secret header is `{name, secret: true,
secret_ref}` with no value or mask. The worker resolves `secret_ref` values with the per-call
tool-secrets fetch.

## 2. Secret (`secrets`, owned by 001 core)

Used, not created, by 005: `id`, `workspace_id`, `kind` (`tool_header`), `ciphertext`,
`key_id`, `last4`, `created_at`, `rotated_at`. Owner reference: `owner_type = "tool"`,
`owner_id = tool_id`. Deleting a tool deletes its secret rows; published snapshots keep the
`secret_ref`, which then resolves to nothing and the worker returns `secret_unavailable` for that
tool (logged, call continues).

## 3. Knowledge Base (`knowledge_bases`)

| Column | Type | Rules |
|---|---|---|
| id | text PK | `kb_` |
| workspace_id | text | RLS |
| name | text | 1 to 120 chars, unique per workspace (case-insensitive) |
| description | text | max 500; used to build the kb_search function description |
| created_by, created_at, updated_at | | |

Derived on read (not stored): `document_count`, `ready_count`, `processing_count`,
`failed_count`, `total_bytes`, `status` = `empty` (0 docs) | `processing` (any uploaded or
processing) | `ready` (all ready) | `partial` (some ready, some failed) | `failed` (none ready, some
failed). `attachable` = `ready_count > 0`.

## 4. Document (`kb_documents`)

| Column | Type | Rules |
|---|---|---|
| id | text PK | `doc_` |
| workspace_id | text | RLS |
| kb_id | text FK knowledge_bases ON DELETE CASCADE | |
| file_name | text | Original name, max 255 |
| file_type | text | `pdf` \| `docx` (from content sniffing) |
| file_size | bigint | <= 20,971,520 |
| sha256 | text | hex, 64 chars |
| storage_key | text | `ws/{workspace_id}/kb/{kb_id}/{doc_id}/{sha256}.{ext}` |
| status | text | `uploaded`, `processing`, `ready`, `failed` |
| error_code | text null | `no_extractable_text`, `corrupt_file`, `encrypted_file`, `embedding_unavailable`, `too_many_chunks`, `internal` |
| error_message | text null | Human-readable |
| page_count | int null | |
| chunk_count | int null | |
| token_count | int null | Embedded tokens, basis of the ingestion charge |
| embedding_model | text null | |
| attempts | int | default 0 |
| replaces_doc_id | text null | Set when uploaded with Replace; old doc removed when this one is ready |
| uploaded_by | text | |
| created_at, processing_started_at, processed_at | timestamptz | |

Indexes: `(workspace_id, sha256)`, `(kb_id, status)`, `(kb_id, lower(file_name))`. Unique
`(kb_id, sha256)` enforces "same content in same KB is refused".

### State transitions

```
uploaded --job picked--> processing --success--> ready
                         processing --permanent error or 3 transient failures--> failed
failed --reprocess--> uploaded
any --delete--> (row, chunks and object removed)
ready (old) --replacement becomes ready--> deleted
```

## 5. Chunk (`kb_chunks`)

| Column | Type | Rules |
|---|---|---|
| id | text PK | ULID, no public prefix (exposed as opaque `chunk_id`) |
| workspace_id | text | RLS |
| kb_id | text | denormalised for filtering |
| doc_id | text FK kb_documents ON DELETE CASCADE | |
| ordinal | int | position in document |
| content | text | <= about 400 tokens |
| token_count | int | |
| page_from, page_to | int null | |
| heading | text null | nearest heading |
| embedding | vector(1536) | |
| embedding_model | text | |
| created_at | timestamptz | |

Indexes: HNSW `embedding vector_cosine_ops` (m 16, ef_construction 64); btree `(workspace_id,
kb_id)`; btree `(doc_id, ordinal)`. Max 5,000 chunks per document (`too_many_chunks`).

## 6. Agent references (owned by 002)

- `AgentConfig.tool_ids: list[str]` (max 25) and `AgentConfig.kb_ids: list[str]` (max 10) in
  the agent draft. 005 validates: ids exist in the workspace, names unique in the set, no
  reserved names, KBs attachable.
- AgentVersion snapshot: `tools: list[ToolSpec]` (resolved), `kb_ids`, and `knowledge: [{kb_id,
  name, description}]` captured at publish to build the kb_search description. KB contents are
  live data searched at call time, so new or deleted documents take effect without republishing.
- Usages query (`GET /v1/tools/{id}/usages`) scans agent drafts and pinned or latest published
  versions for the id, using 002's GIN index on the config JSON.

## 7. Tool call event (CallEvent kind `tool_call`, table owned by 003)

```jsonc
{
  "kind": "tool_call",
  "turn_index": 4,
  "payload": {
    "tool_id": "tool_01J...",          // null for kb_search
    "tool_name": "check_availability",
    "tool_type": "http",               // end_call | transfer_call | press_digit | http | kb_search
    "arguments": {"date": "2026-10-20"},
    "output": "{\"next_slot\":\"10:00\"}", // truncated to 4 KB, secrets scrubbed
    "is_error": false,
    "error_code": null,                // timeout | http_status | blocked_address | invalid_arguments | channel_unsupported | transfer_failed | secret_unavailable | response_too_large | missing_variable | no_mock_response
    "duration_ms": 412,
    "dispatch_overhead_ms": 6,
    "mocked": false,
    "http_status": 200,
    "spoke_execution_message": true,
    "mapped_variables": {"next_slot": "10:00"},
    "kb": {"kb_ids": ["kb_01J..."], "result_count": 3, "top_score": 0.71, "chunk_ids": ["01J..."], "timed_out": false, "embedding_cache_hit": true}
  }
}
```

`kb` is present only for `kb_search`; `http_status`, `spoke_execution_message` and
`mapped_variables` only for `http`.

## 8. Internal search request and response

Request `POST /v1/internal/knowledge/search`: `{call_id, query (1 to 1,000 chars), kb_ids
(1 to 10), top_k (1 to 8, default 4)}`. Response: `{results: [{chunk_id, kb_id, doc_id,
file_name, page_from, page_to, heading, content, score}], embedding_ms, query_ms,
embedding_cache_hit}`. Results below the 0.30 similarity threshold are dropped; total `content`
is cut to 4,000 characters across results.
