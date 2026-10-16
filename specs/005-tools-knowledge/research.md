# Research: Tools and Knowledge (005)

Phase 0 output for [plan.md](./plan.md). Each entry: Decision, Rationale, Alternatives considered.
Reference behaviour comes from `research/calldash-functional-spec.md` sections 3 and 4; Callwright
does not copy its code or copy text.

## R1. Tools are a workspace library, referenced by id from the agent config

- **Decision**: `tools` rows belong to a workspace (`tool_` ids). An agent draft references
  them through `AgentConfig.tool_ids[]` (002). Attach and detach is `PUT
  /v1/agents/{agent_id}/tools` in the tools router, which validates the set and then calls
  `agents.service.update_draft(...)`.
- **Rationale**: The reference product ties tools to an LLM record, so a shared "transfer to
  billing" tool must be recreated per agent and duplicating an agent copies tools. A library
  avoids that and gives a natural "used by N agents" view.
- **Alternatives**: Tools embedded inside AgentConfig (no table): no reuse, no usage view,
  secrets would live inside config JSON. Join table `agent_tools`: duplicates what the draft
  config already stores and can drift from it.

## R2. Published versions embed resolved tool definitions

- **Decision**: On publish (002) and flow compile (004), `tools.service.resolve_for_snapshot(
  workspace_id, tool_ids) -> list[ToolSpec]` returns full definitions with secret header values
  replaced by `secret_ref` ids. The snapshot stores these; the worker never reads the `tools`
  table.
- **Rationale**: Principle I says runtime config is plain versioned data. Editing a tool must not
  silently change a live, published agent; simulations (008) must be able to replay a version.
- **Alternatives**: Resolve tools at call start by id: version drift, an extra query on the hot
  path, broken replays after deletion.

## R3. Secrets: encrypted store, masked API, fetched once per call

- **Decision**: Header values with `secret: true` are written to the cross-cutting `secrets`
  table via `services/api/app/core/secrets.py` (KMS envelope encryption, 001). Tool config keeps
  only `secret_ref` plus `masked_value` (`****` + last 4). On PATCH, a secret header with no
  `value` keeps its existing ref. The worker calls `GET /v1/internal/calls/{call_id}/tool-secrets`
  once at session start (service token) and keeps the map in memory for the call only.
- **Rationale**: Principle V. One fetch per call keeps secret resolution off the per-turn path;
  secrets never enter the snapshot, so version diffs and exports are safe.
- **Alternatives**: Put encrypted blobs in the snapshot and give the worker the KMS key: widens
  key exposure to every worker. Fetch per tool invocation: adds a network hop to each tool call.

## R4. HTTP execution core and SSRF guard

- **Decision**: `httpx.AsyncClient` with a custom transport that resolves DNS itself, rejects
  private (RFC 1918, RFC 4193), loopback, link-local (including 169.254.169.254 and fd00:ec2::254),
  CGNAT, multicast and unspecified addresses, then connects to the vetted IP with the original
  Host/SNI (prevents DNS rebinding). Redirects are followed manually (max 3), each hop
  re-checked. Body read is capped at 64 KB. HTTPS required unless `ENV=development`. No
  automatic retries.
- **Rationale**: Customers enter arbitrary URLs and the agent fills arguments from caller speech,
  so both the editor test run and live calls are SSRF vectors.
- **Alternatives**: Egress proxy (smokescreen-style): sound, but a new service (Principle VI);
  revisit if more outbound features appear. URL string checks only: bypassed by DNS tricks.

## R5. One HTTP core, two copies (API test run and worker)

- **Decision**: The logic for templating, argument placement, response mapping, truncation and
  the address guard exists in `services/api/app/tools/http_exec.py` (editor test runs) and
  `services/voice-worker/worker/tools/http.py` (calls). Both run the same parametrised test
  vectors (`tests/unit/test_http_exec_vectors.py` in each service, generated from one JSON file
  checked into each service's tests).
- **Rationale**: The two deployables share no package today (Principle VI: no new shared
  library until a second need appears). The code is about 200 lines and fully unit-tested.
- **Alternatives**: Route test runs through a worker: needs a job channel to the worker and a
  room-less execution mode. Shared Python package: adds packaging and versioning work now.

## R6. Templating and response mapping

- **Decision**: Placeholders `{{name}}` with names `[a-zA-Z_][a-zA-Z0-9_.]*`. Lookup order:
  LLM arguments, call dynamic variables, previously mapped variables. The body template is
  parsed as JSON first and placeholders are substituted inside string values (a value that is
  exactly one placeholder takes the variable's JSON type), so caller speech can never break the
  JSON structure. URL placeholders are percent-encoded. Response mapping uses a small dot-path
  parser (`a.b[0].c`), not full JSONPath.
- **Rationale**: Prevents injection; covers the reference product's documented paths
  (`data.slots[0].time`) without a dependency.
- **Alternatives**: Jinja2: too powerful for user-supplied templates. `jsonpath-ng`: larger
  surface than needed.

## R7. Speak during execution

- **Decision**: The worker starts the request, waits up to 400 ms, and if it has not finished and
  `speak_during_execution` is true, calls the session's say method with `execution_message`
  (default "One moment while I check that.") without adding it to the LLM context. Spoken at
  most once per invocation.
- **Rationale**: Fast APIs should not produce filler; slow ones should not leave dead air. The
  reference product speaks unconditionally.
- **Alternatives**: Always speak: adds 1 to 2 s of audio to fast lookups. LLM-generated filler:
  an extra LLM call on the hot path.

## R8. Transfers on LiveKit SIP

- **Decision**: Cold: LiveKit SIP `TransferSIPParticipant` (SIP REFER) on the caller's SIP
  participant, then the agent leaves; disconnect reason `call_transfer`. Warm, `private`: create
  a consult room, dial the destination with `CreateSIPParticipant` (ring timeout from config),
  the agent speaks the briefing there (static text or one LLM-written line from the briefing
  instructions), then the destination is moved into the caller's room (`MoveParticipant`) and
  the agent leaves. Warm, `public`: dial the destination straight into the caller's room and
  brief with both listening. The caller hears `hold_message` and, if configured, hold audio.
  Non-SIP channels return `channel_unsupported` to the LLM.
- **Rationale**: Uses LiveKit primitives only (no media server of our own). Matches the
  reference product's cold/warm and private/public options.
- **Alternatives**: Bridge via the carrier (Twilio conference): carrier lock-in, violates
  Principle I. Keep the agent in the call after warm transfer: doubles metered minutes for no
  value.
- **Metering**: Billed call duration ends when the agent leaves the room (cold: after REFER is
  accepted; warm: after the move). The consult leg time before the move is part of the call
  duration. Carrier charges on the customer's trunk are outside Callwright billing.

## R9. Press digit (DTMF)

- **Decision**: `rtc.LocalParticipant.publish_dtmf(code, digit)` per digit (RFC 4733 events on
  the SIP leg), after `delay_ms` (default 1000) and with `cooldown_ms` (default 5000) enforced by
  delaying, not dropping, a press that arrives early. Digits `[0-9*#]{1,20}`, 100 ms between
  digits.
- **Rationale**: LiveKit-native; no carrier API.
- **Alternatives**: In-band tone audio: unreliable through codecs.

## R10. Dynamic transfer allow-list

- **Decision**: `TransferSpec.allowed_numbers[]` (optional, E.164). If present for dynamic
  routing, the chosen number must be in it; otherwise any valid E.164 number is accepted. The UI
  recommends filling it.
- **Rationale**: A caller can talk an agent into "transferring" to a premium-rate number; an
  allow-list closes that. The reference product has no such guard.
- **Alternatives**: Mandatory list: blocks legitimate "route by region" setups with many numbers.

## R11. Document intake and duplicate detection

- **Decision**: Multipart upload through the API (`POST
  /v1/knowledge-bases/{kb_id}/documents`), streamed to a spooled temp file with a hard 20 MiB
  cap, content sniffed (`%PDF-` header; DOCX = ZIP with `word/document.xml`), SHA-256 computed
  while streaming, then written to S3. The browser computes SHA-256 with Web Crypto first and
  calls `POST .../documents/check-duplicate` so a duplicate 20 MB file is never sent. Same hash
  in the same KB: 409 `duplicate_document`. Same hash in another KB, or same file name with a
  different hash: warning; the latter offers `replace_doc_id`.
- **Rationale**: Reference product checks duplicates by file name only, which misses renamed
  copies and blocks real new versions.
- **Alternatives**: Presigned direct-to-S3 upload: one more round trip and a finalize step, no
  benefit at 20 MB (Principle VI).

## R12. Text extraction and chunking

- **Decision**: `pypdf` for PDF text (per page), `python-docx` for DOCX (paragraphs, headings,
  tables flattened row by row). Chunker: heading-aware recursive splitter, target 400 tokens,
  60-token overlap, never splitting inside a table row, counted with `tiktoken` (`cl100k_base`).
  Each chunk keeps `page_from`, `page_to` and the nearest heading. A document with under 50
  characters of text per page on average fails with `no_extractable_text` (scanned PDF).
- **Rationale**: 300 to 500 token passages answer FAQ-style questions well and keep 4 passages
  under the 4,000-character budget sent to the LLM.
- **Alternatives**: `unstructured`: heavy dependency tree. Fixed-size character windows: split
  mid-sentence and lose headings.

## R13. Embeddings behind an adapter

- **Decision**: `services/api/app/knowledge/embeddings/base.py` defines `EmbeddingAdapter`
  (`embed(texts) -> list[vector]`, `model`, `dimensions`). Default `openai.py` with
  `text-embedding-3-small` (1536 dimensions); `azure_openai.py` as second vendor. Selected by
  environment config. Chunks store `embedding_model`; queries only match chunks of the same
  model. Ingestion cost = tokens x catalog rate, posted through
  `billing.charge_feature("knowledge_ingestion", ...)`.
- **Rationale**: Principle I (vendor behind an adapter) and III (metered).
- **Alternatives**: Local embedding model in the API image: larger image, CPU load in the API
  process, no quality gain at this scale.

## R14. Vector store and query

- **Decision**: pgvector `vector(1536)` column, HNSW index with `vector_cosine_ops` (m 16,
  ef_construction 64), `hnsw.ef_search = 40`, and `hnsw.iterative_scan = relaxed_order`
  (pgvector 0.8) so `WHERE kb_id = ANY(...)` filtering under RLS still returns top_k rows.
  Similarity threshold 0.30 (cosine similarity), tuned against the SC-007 question set.
- **Rationale**: Constitution names pgvector; no separate vector database (Principle VI).
- **Alternatives**: IVFFlat: needs training and re-indexing as data grows. Per-KB partial indexes:
  index count grows with tenants.

## R15. Retrieval path and latency budget

- **Decision**: The worker's `kb_search` tool calls `POST /v1/internal/knowledge/search`
  (service token, includes `call_id`; the API derives the workspace from the call and sets
  `app.workspace_id`, so RLS applies). Budget for p95 300 ms: query embedding about 150 ms,
  vector query under 30 ms, network and serialisation under 40 ms, with headroom. Measures:
  persistent keep-alive HTTP client opened at session start, a Redis cache of query embeddings
  (normalised text hash, 24 h TTL), and the connection opened at session start so the first search does not pay TLS setup.
  KB names and descriptions for the tool description come from the version snapshot (captured
  at publish), not from a call-time request.
  Hard timeout 800 ms in the worker: on timeout the tool returns `{results: [], timed_out: true}`
  and the LLM is told nothing was found.
- **Rationale**: Keeps database access and RLS in one place; the worker stays stateless and has
  no database credentials (architecture section 1).
- **Alternatives**: Worker queries Postgres directly: saves one hop (about 10 ms) but spreads DB
  credentials and RLS session handling to every worker. Pre-turn automatic retrieval injected
  into every prompt: adds retrieval latency to every turn, including turns that do not need it.

## R16. kb_search as a system tool

- **Decision**: No tool row. When the version's `kb_ids` is non-empty, the worker registry adds a
  `kb_search(query: string)` function whose description is generated from the KB names and
  descriptions ("Search the clinic policies and price list for facts ..."). The name `kb_search`
  is reserved in the tool library. Results are formatted as numbered passages with source file
  and page; total under 4,000 characters.
- **Rationale**: Nothing to configure for the operator; the LLM decides when to search.
- **Alternatives**: A user-created tool type: extra setup for no gain.

## R17. Signed document URLs

- **Decision**: S3 presigned GET, 10-minute expiry, `response-content-disposition=inline;
  filename=...`, key `ws/{workspace_id}/kb/{kb_id}/{doc_id}/{sha256}.{ext}`, server-side
  encryption on.
- **Rationale**: Matches the recordings convention (architecture section 7) and Principle V.

## R18. Ingestion job

- **Decision**: arq job `knowledge.jobs.ingest_document(doc_id)`, idempotent: inside one
  transaction it deletes existing chunks for the doc, inserts new ones, and sets status `ready`.
  Transient vendor errors retry 3 times (10 s, 60 s, 300 s backoff); permanent errors set
  `failed` with `error_code`. A Redis semaphore limits each workspace to 2 concurrent ingestions.
  Replace: the new doc ingests fully, then the old doc and its chunks are deleted in the same
  transaction that marks the new one ready.
- **Rationale**: Architecture says jobs run in the API image on arq; idempotency mirrors the
  post-call pipeline convention.

## R19. Tool call events

- **Decision**: Every invocation emits a CallEvent of kind `tool_call` through 003's
  `worker/metrics.py` event batcher (non-blocking) to `POST /v1/internal/calls/{call_id}/events`
  with `{tool_id?, tool_name, tool_type, arguments, output, is_error, error_code, duration_ms,
  dispatch_overhead_ms, turn_index, mocked}`. `kb_search` events add `kb_ids`, `result_count`,
  `top_score`, `chunk_ids`, `timed_out`. Arguments and outputs are scrubbed of secret values
  before emission.
- **Rationale**: Feeds the call detail "tools used" view (006), evaluators such as tool-call
  correctness and KB relevance (007), and the latency gate (Principle II).

## R20. Simulation mocks

- **Decision**: The session config carries `simulation: true` (set by 008 at dispatch). The
  registry then wraps `http` to return `mock_response` (or, if empty, a structured
  `{"error": "no_mock_response"}` so 008 can decide), and `transfer_call` and `press_digit` to
  succeed without telephony. `kb_search` runs for real (read-only). `GET
  /v1/agents/{agent_id}/tools/mock-coverage` returns attached tools whose `mock_response` is
  empty, including flow webhook nodes reported by 004 via a hook function.
- **Rationale**: Simulations must not create bookings in customer systems.

## R21. Latency benchmarks (Principle II)

- **Decision**: `services/voice-worker/tests/harness/bench/` holds three benchmarks run in CI
  with 500 iterations each and compared to a stored baseline JSON: (1) tool dispatch overhead
  against an in-process HTTP stub returning in 0 ms (gate p95 <= 50 ms); (2) kb_search end to
  end against a seeded 10,000-chunk workspace with a recorded-latency embedding stub
  (gate p95 <= 300 ms, max <= 800 ms); (3) the benchmark call set with and without tools
  attached (gate: no p50/p95 turn-latency regression beyond 5%). A nightly job reruns (2) with
  the real embedding vendor.
- **Rationale**: The constitution requires showing no p50/p95 regression for hot-path changes.

## R22. Limits

- **Decision**: 25 tools per agent, 10 KBs per agent, 200 documents per KB, 1 GiB documents per
  workspace, 30 editor test runs per minute per workspace (Redis token bucket from 001), top_k
  default 4, max 8.
- **Rationale**: LLM tool-selection accuracy drops with long tool lists; quotas cap storage and
  embedding spend in v1. All are environment-configurable.
