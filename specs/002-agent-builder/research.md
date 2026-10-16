# Research: Agent Builder

**Feature**: 002-agent-builder | **Date**: 2026-10-16
**Inputs**: spec.md, constitution v1.0.0, research/architecture.md (sections 3 to 5),
research/calldash-functional-spec.md (sections 1, 2.1 to 2.4, 10.4, 10.5, 12), research/pages/
(`_agents_new*.txt`, `single_*.txt`, `_agents_templates.txt`, `03-_agents.txt`), and the sibling
plans that consume this feature (003 R18 and data model section 9, 004 R9 and plan, 005 data model
section 6, 008 R3).

Each entry: Decision, Rationale, Alternatives considered.

---

## R1. One versioned AgentConfig instead of separate model and agent records (deliberate simplification)

**Decision**: An agent's whole runtime configuration (model, prompt, greeting, variables, speech,
voice, call behaviour, advanced settings, attachment references) is one JSON document,
`AgentConfig`, stored as the agent's draft and snapshotted into immutable `AgentVersion` rows.
There is no separate "LLM record".

**Rationale**: The reference product stores the prompt and model in an LLM record and everything
else in an agent record, saved by two parallel requests and joined through `llm_id`. That split
causes partial saves (one request succeeds, the other fails), forces tools to hang off the LLM
record rather than the agent, makes duplication a three-record copy, and means a version has to
reassemble both records to be complete. Nothing in the product shares one LLM record between
agents. A single document gives atomic saves, one hash per version, one diff, and a direct fit for
architecture section 5 and Principle I ("agent configuration is plain, versioned data").

**Alternatives considered**: Mirror the two-record design (rejected for the reasons above);
normalised columns per setting (every new setting becomes a migration; diffs and snapshots get
harder).

## R2. Draft, snapshot on save, explicit publish

**Decision**:
- `agents.draft_config` is what the editor loads and saves (architecture: "current draft config").
- Every save that changes the draft (and passes blocking validation) records a new immutable
  `AgentVersion` (`source = save`) and points `agents.draft_version_id` at it.
- Publishing sets `agents.pinned_version_id` (architecture: "pinned published version"); live
  channels use only the published version, and refuse calls when there is none (003 FR-004).
- Test calls use the draft's version; `snapshot_for_test(agent_id)` returns an existing version
  whose hash matches the draft (including resolved tools and flow, see R5) or records a
  `source = test` version, never publishing it (003 R18).
- Restore copies a version's config into the draft and records a `source = restore` version;
  "restore and publish" also moves the published pointer.

**Rationale**: Gives the reference product's "snapshot on save" history (every saved state can be
compared and restored) while keeping production stable until the operator publishes, which the
reference product lacks (its saves go live immediately). It matches what 003, 004, 005 and 008
already assume (draft, published version, test snapshots).

**Alternatives considered**: Latest save goes live automatically (one mis-click reaches
production); versions only on publish (loses history of saved drafts that the task asks for).

## R3. Content hash and no-op saves

**Decision**: `content_hash = sha256(canonical_json(config))`, canonical JSON with sorted keys,
no insignificant whitespace, UTF-8, and the snapshot-only `tools` block included. A save whose hash
equals the current draft version's hash returns `200` with `created: false` and no new version.
`snapshot_for_test` and 004's `create_version` look up any version of the agent with the same hash
before inserting.

**Rationale**: Prevents version spam from repeated saves and lets callers dedupe cheaply. The same
canonicalisation is what 008 uses for simulation targets (008 R3), so hashes are comparable.

## R4. Config format versioning

**Decision**: `AgentConfig.schema_version` (integer, starts at 1). Stored versions are never
rewritten. When the format changes, an upcaster `upgrade_v{n}_to_v{n+1}(dict) -> dict` in
`agents/schemas.py` runs on read; the runtime and the editor always see the newest shape. Diff and
hash use the stored form.

**Rationale**: Versions must stay immutable (Principle I, SC-003) while the format evolves.

## R5. Extension blocks owned by other features

**Decision**: AgentConfig reserves blocks other modules own: `tool_ids[]` and `kb_ids[]` (005),
`flow` (004: `{flow_id, graph, graph_hash, compiled}`), `evals` (007). 002 stores, hashes, diffs
and versions them, and calls registered hooks:
- `register_validator(block, fn)`: called by `validate_config`, adds errors and publish blockers;
- `register_snapshot_resolver(block, fn)`: called when a version is recorded, writes snapshot-only
  data (005 adds `tools: [ToolSpec]` resolved from `tool_ids`, so later tool edits do not change
  old versions, FR-028).

Before 004, 005 and 007 ship, the blocks default to empty and no hooks are registered.

**Rationale**: Each feature keeps ownership of its content while every version stays
self-contained.

## R6. Catalog source: capability YAML joined with the pricing catalog

**Decision**: Selectable options come from two data sources:
1. Capability files in the repo: `services/api/app/llms/catalog.yaml` (providers, models, labels,
   temperature rules, tool support, context window) and `services/api/app/voices/catalog.yaml`
   (languages with defaults, STT providers and models with language coverage and single-model
   flags, TTS providers, models, capability flags and default voices, NC options, built-in
   ambient sounds).
2. The 001 pricing catalog for prices.

`GET /v1/llms/catalog` and `GET /v1/voices/catalog` return the capability entries with each
entry's current per-minute rate attached, or `price: null` when no pricing row matches (the editor
then shows "price unavailable" and the version gets a publish blocker). Entries marked
`withdrawn: true` are hidden from pickers but still resolve for existing configs, which get a
publish blocker. AgentConfig stores providers and models as plain strings, validated against the
catalog at save time; the contract has no vendor enums.

**Rationale**: Principle I: a new vendor is one runtime adapter, one capability entry, one pricing
row; no schema or migration. YAML in git is reviewed like code and needs no admin UI.

**Alternatives considered**: Catalog tables with an admin UI (more surface, no current need);
hard-coded client lists as in the reference product (drift between client and server).

## R7. Voice browser

**Decision**: One normalised endpoint, `GET /v1/voices/{provider}/voices`, backed by per-vendor
listing adapters in `services/api/app/voices/adapters/<vendor>.py` (ElevenLabs and Cartesia list
remotely; Fish Audio serves a curated allow-list kept in the YAML, because its public library is a
community ranking unsuited to business agents; no Sarvam voices at launch). Output shape:
`{voice_id, name, description, gender, languages[], preview_url, model_ids[]}` with cursor
pagination, `search`, `gender`, `language`, `model` filters applied by the adapter or locally (Cartesia has no
vendor search, so search runs over the cached list).
Results are cached in Redis per `(provider, filters, cursor)` for 1 hour; vendor failure returns
`503` with `code: catalog_unavailable` and the editor keeps the current selection. Preview audio
is the vendor's sample URL when one exists; otherwise no preview button (test calls cover it).

**Rationale**: One client component for every vendor; vendor keys stay server-side (Principle V);
caching keeps the picker fast and spares vendor rate limits.

**Alternatives considered**: One endpoint per vendor as in the reference product (client knows
vendor shapes); synthesising previews via TTS in the API (adds a TTS path outside the worker).

## R8. Temperature rules

**Decision**: Each model entry carries `temperature: {min, max, step, default}` or
`{fixed: 1.0}`. On save, a fixed model's temperature is normalised to the fixed value (warning,
not error). On model change the editor clamps to the new range and shows a notice; the server
rejects out-of-range values for non-fixed models with `out_of_range`.

**Rationale**: Some current models accept only one temperature; others use 0 to 1 or 0 to 2.
Encoding the rule as data avoids per-vendor code in the editor.

## R9. Dynamic variables

**Decision**: Placeholder syntax `{{name}}`, whitespace inside braces tolerated (`{{ name }}`).
Extraction regex `\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,63})\s*\}\}`; any other `{{...}}` is reported as
`invalid_variable`. Config stores `dynamic_variables: [{name, default | null, description?}]`, the
union of extracted and hand-added names, max 50. Reserved built-ins (003 FR-005): `call_id`,
`channel`, `direction`, `user_number`, `agent_number`, `timezone`, `current_time`,
`current_date`, `current_datetime`; they may appear in text but not in the list. Warnings:
`variable_without_default`, `unused_default`.

**Rationale**: Matches 003's runtime resolution and naming rules exactly.

## R10. Validation model

**Decision**: Three layers, one code path (`agents.service.validate_config(type, config)`):
1. Structure and ranges: Pydantic v2 models in `agents/schemas.py` (all field errors collected,
   not first-fail).
2. Catalog checks: provider and model exist and are not withdrawn for new selections, voice
   belongs to provider, STT model covers the language, analysis model exists.
3. Registered hooks (R5).

Results are classified as `errors` (block save), `publish_blockers` (allow save, block publish:
unpriced component, withdrawn component, missing tool or KB), and `warnings`. Each item carries a
JSON Pointer into the config. `POST /v1/agents/validate` exposes the same function so the editor
can show field errors as the operator types (debounced 400 ms) and 008 can validate variants.

**Rationale**: SC-004 needs every violation in one response; one function serves save, publish,
the editor and other features.

## R11. Concurrent edits

**Decision**: `agents.draft_revision` (integer) increments on every draft write and is returned
as an `ETag`. `PUT /v1/agents/{id}/draft` and `POST .../restore` require `If-Match`; a stale
revision returns `412` with `code: draft_changed` and the current revision, so the editor can
offer "reload" or "compare with the newer draft".

**Rationale**: Same pattern as 004's flow saves (004 R2); avoids lost updates across tabs.

## R12. Version diff

**Decision**: Server computes `GET .../versions/{a}/diff?against={b|draft}` as a list of
`{op: add | remove | replace, path, old, new}` with RFC 6901 pointers. Keyed lists are matched by
key: `dynamic_variables` by `name`, `advanced.pronunciation` by `word` (case-insensitive),
`tool_ids` and `kb_ids` by value, `tools` by `tool_id`. Paths use the key in brackets for keyed
items, e.g. `/dynamic_variables[customer_name]/default`. The web app maps paths to labels
("System prompt", "Voice speed") in `routes/agents/versionLabels.ts` and renders long strings with
a line diff (`diff` npm package). The `flow` block is diffed by 004's node-aware differ when
registered; otherwise as JSON.

**Rationale**: Index-based patches mislabel changes when a list item is inserted; keyed matching
gives the readable output the spec asks for (FR-025).

## R13. Resolving the version for a call

**Decision**: Live channels read `agents.pinned_version_id` at admission (one indexed read in
003's admission transaction), so a publish takes effect for the next call with no cache to
invalidate (SC-006). Version configs are immutable and can be cached by `agv_` id indefinitely
(worker side, 003).

## R14. Delete

**Decision**: Soft delete (`deleted_at`); versions are never deleted (calls reference them,
SC-003). Before deleting, `agents.service.delete_agent` asks registered usage checkers (010
registers one for phone numbers, WhatsApp channels and outbound) and returns `409` with
`code: agent_in_use` and the list. Deleted agents vanish from list and search and return `404`
on direct reads, except through version reads used by call detail pages.

## R15. Duplicate

**Decision**: New `agt_`, name "<name> (copy)" (truncated to 80 chars), same type, same draft
config (attachment references included), `draft_version_id` = a fresh version 1 with
`source = duplicate`, no published version, no history. Flow agents: 004 registers a duplicate
hook to copy the flow draft.

## R16. Templates

**Decision**: Platform templates are YAML files in `services/api/app/templates/seed/*.yaml`
(`id` slug, `name`, `category`, `description`, `icon`, `config` partial AgentConfig, `sort_order`).
On deploy, a sync job upserts them into the global `templates` table by slug and deactivates
removed ones. Categories (fixed list): `automotive`, `banking`, `ecommerce`, `healthcare`,
`telecom`. Launch set: the seven templates in data-model.md section 6, matching the reference
product's live set in intent and structure (captured 2026-10-16, `research/ui-walkthrough/templates/`)
with Callwright-written prompts, plus declared variables with defaults (the reference templates
had none). "Use template" is `POST /v1/agents {template_id}` with an `Idempotency-Key`; the
server overlays the template config on the defaults, replaces unavailable components with
language defaults, and reports replacements as warnings. Clicking a card only opens the preview
(the reference created an agent on any card click, with no preview).

**Rationale**: Templates change with releases, not at runtime; slugs avoid a new ID prefix
(architecture section 4 has none for templates) and read well in version notes.

**Alternatives considered**: Templates as workspace-owned agents (needs sharing rules);
templates served from a CMS (Principle VI).

## R17. Cost estimate

**Decision**: The editor calls 001's `POST /v1/pricing/quote` with the current STT, LLM, TTS and
NC selections (debounced 250 ms; TanStack Query keyed by the selection so toggling back is
instant). Picker prices come from the catalog endpoints (R6). Surcharge-risk notice: estimated
prompt tokens = characters / 4; assumed agent turns per minute = 4 (`SURCHARGE_TURNS_PER_MIN`);
expected input tokens per minute = 4 x (prompt tokens + 600 for history and tool output); notice
when that exceeds the model's `llm_input_tokens` bundle from the quote. With the default bundle of
20,000, a prompt of about 4,400 tokens (roughly 3,300 words) triggers it.

**Rationale**: One pricing implementation (001 R15, Principle VII). The heuristic is display-only
and its constants are config, so it can be tuned from real call data later.

## R18. AI prompt assistant

**Decision**: `POST /v1/prompt-ai/generate` with `{messages[], current: {prompt, begin_message,
dynamic_variables} | null, language}` returns `{reply, proposal | null, usage}`. The API calls the
platform assistant model through `llms/client.py`, which dispatches to
`services/api/app/llms/adapters/<vendor>.py` (Principle I; the same gateway is available to 006,
007 and 008 for API-side model calls). The system prompt for the assistant asks for a JSON
`proposal` object only when the user asks for a prompt or a change. Timeout 60 s. Before the call:
`billing.credit_check` style refusal when balance `<= 0` (`402`, `insufficient_credit`) and a
Redis limit of 20 requests per minute per workspace (`429`). After the call:
`billing.charge_feature(ws, "prompt_generation", quantity=tokens, raw_cost, billable_cost,
ref=("agent", agent_id), idempotency_key)`. Chat history lives only in the browser.

**Rationale**: Stateless and cheap to build (Principle VI); usage reporting (001 US4) sees every
request.

## R19. Background audio uploads

**Decision**: `POST /v1/voices/ambient-audio` (multipart) accepts `.mp3 .wav .ogg .flac .aac .opus`
up to 10 MB, verified by magic bytes; max 20 files per workspace. Stored at
`workspaces/{ws}/ambient/{ulid}.{ext}` in object storage (encrypted at rest), metadata in
`ambient_audio_files`. AgentConfig references it as `{kind: "upload", key}`; built-ins as
`{kind: "builtin", id}`. The UI previews through a 10-minute signed URL. 003 resolves the key to a
signed URL in the claim response (003 R12). Deleting an upload that any draft or published version
references is refused (`409 audio_in_use`).

**Rationale**: 003 already plans for uploaded ambience by object key; object keys avoid a new ID
prefix.

## R20. Webhook address rules

**Decision**: `https://` absolute URL, max 2,048 chars; `http://` only when `ENV=development`.
At save, the host is resolved and rejected if any address is loopback, link-local, private
(RFC 1918, RFC 4193), or metadata ranges; IP literals are checked directly. 003 re-checks at send
time (DNS can change).

**Rationale**: Principle V and SSRF protection; aligned with 003's validation rules.

## R21. Search and list performance

**Decision**: Partial name search with `ILIKE` backed by a `pg_trgm` GIN index on `agents.name`;
exact ID match short-circuits. List index `(workspace_id, updated_at desc) where deleted_at is
null`. 005's usage lookup gets `GIN (draft_config jsonb_path_ops)` on `agents` and on
`agent_versions.config`.

**Rationale**: SC-005 (1,000 agents, under 1 s) with room to spare.

## R22. Editor state in the web app

**Decision**: `react-hook-form` holds the draft form (dirty tracking for the leave guard, field
registration across the four sections), with server validation from `POST /v1/agents/validate`
mapped onto fields by JSON Pointer. Saves use `PUT /v1/agents/{id}/draft` with `If-Match`.
The error summary dialog and leave guard come from 001's components (001 T085).

**Alternatives considered**: Plain controlled state (the reference product's approach; manual
dirty tracking across about 40 fields); duplicating validation rules in a client schema library
(two sources of truth for catalog-dependent rules).

## R23. Defaults

**Decision**: Defaults live in `services/api/app/agents/defaults.py` and per-language overrides in
`voices/catalog.yaml`; the API returns a fully defaulted config from `POST /v1/agents` and from
`GET /v1/agents/defaults?language=`. Values are those listed in spec Assumptions. Unlike the
reference product, templates do not silently change call-behaviour defaults (it used 0.5/0.5
interruption/responsiveness for templates and 0.95/0.79 for blank agents); a template changes a
default only if its YAML sets it. Noise cancellation defaults to voice isolation (`sanas`/`vi`)
and the editor shows it from the first render. Every default lies on its control step (volume
1.0, responsiveness 0.8), so labels never disagree with stored values.

## R24. IDs

**Decision**: `agt_` and `agv_` ULIDs (architecture section 4). Templates use slugs; uploads use
object keys; nothing else in this feature needs an exposed ID.

## R25. Live UI findings applied (2026-10-16)

**Decision**: Items tagged [002] and [003] in `research/ui-walkthrough/DELTA.md` changed these
choices (full table in `research/ui-walkthrough/DELTA-resolution-001-003.md`):
- Catalogs are exact copies of the live offer (data-model.md section 8) with one model id across
  providers; the reference priced `gpt-5.1-chat` but offered `gpt-5.1`, so its cost card showed
  $0.0000. T090 fails the build on any such gap.
- One control-range table (`controls`) feeds the editor and every override UI; the reference
  used other steps and a 0 to 1 "stability" range on flow nodes, and showed labels that did not
  match the stored values.
- Inline validation reuses the server rules; the reference sent `notaurl`, a 50 ms timeout, a
  12 s or 61 minute maximum and a negative ring time to the server.
- Provider switch picks the language default voice instead of leaving the form invalid; every
  STT provider has Auto; selects never render blank (the reference showed an empty noise
  cancellation field while saving voice isolation).
- Fish Audio is offered through a curated allow-list; its public community ranking is not suited
  to business agents. Cartesia gets local search.
- Create and duplicate are idempotent; duplicate needs no confirmation.
- Version list carries `parent_version_id` and a summary; analysis variables stay out of the
  snapshot (architecture section 5 keeps them in 007's per-agent tables).
- Test on a never-saved form saves first; the reference showed a "coming soon" placeholder.

**Rationale**: Each change removes a defect observed live or copies a behaviour that worked, at
small cost.

