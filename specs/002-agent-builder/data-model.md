# Data Model: Agent Builder

**Feature**: 002-agent-builder | **Date**: 2026-10-16

Conventions as in 001's data model: Postgres 16, `timestamptz` UTC, prefixed ULIDs, RLS policy
`workspace_id = current_setting('app.workspace_id', true)` on every tenant table.

---

## 1. agents (Agent)

| Column | Type | Rules |
|---|---|---|
| id | text PK | `agt_` ULID |
| workspace_id | text FK workspaces, not null | RLS |
| name | text, not null | 1 to 80 chars, not unique |
| type | text, not null | `single_prompt` or `flow`; trigger rejects any UPDATE of this column (FR-002) |
| language | text, not null | mirror of `draft_config.language` for list display |
| draft_config | jsonb, not null | AgentConfig (section 4) |
| draft_revision | int, not null, default 1 | +1 on every draft write; exposed as ETag (research R11) |
| draft_version_id | text FK agent_versions.id, not null | version matching the saved draft |
| pinned_version_id | text FK agent_versions.id, null | the published version; null = not published |
| template_id | text null | slug of the template used at creation |
| created_by | text FK users.id | |
| created_at, updated_at | timestamptz | `updated_at` changes on name or draft writes |
| deleted_at | timestamptz null | soft delete |

Indexes: `(workspace_id, updated_at desc) where deleted_at is null`; GIN `name gin_trgm_ops`;
GIN `draft_config jsonb_path_ops` (005 usage lookups).

Note: `draft_version_id` and `agent_versions.agent_id` reference each other; the agent row is
inserted with a deferred constraint and version 1 in the same transaction.

## 2. agent_versions (Agent Version)

Immutable. Trigger rejects `UPDATE` and `DELETE`. RLS.

| Column | Type | Rules |
|---|---|---|
| id | text PK | `agv_` ULID |
| workspace_id | text, not null | |
| agent_id | text FK agents.id, not null | |
| version_number | int, not null | 1, 2, 3... per agent; `unique (agent_id, version_number)` |
| schema_version | int, not null | AgentConfig format version at write time |
| config | jsonb, not null | full AgentConfig plus snapshot-only blocks (`tools`) |
| content_hash | char(64), not null | sha256 of canonical JSON (research R3) |
| source | text, not null | `create`, `save`, `restore`, `template`, `duplicate`, `flow_publish`, `test` |
| restored_from_version_id | text null FK agent_versions.id | set when `source = restore` |
| note | text null | max 500 chars (release notes) |
| publish_blockers | jsonb, not null, default `[]` | `[{pointer, code, message}]` computed at write time |
| created_by | text null FK users.id | null for system-created test snapshots |
| created_at | timestamptz | |

Indexes: `(agent_id, version_number desc)`; `(agent_id, content_hash)`; GIN
`config jsonb_path_ops`.

Version numbers are assigned under `SELECT ... FOR UPDATE` on the agent row.

## 3. Agent state rules

```text
create (first save of a blank form | template | duplicate | 004 flow create)
   blocking errors -> 422, nothing written (the blank form lives only in the browser until saved)
   -> agents row + version 1 (source create | template | duplicate)
      draft_version_id = v1, pinned_version_id = null

save draft (If-Match revision)
   blocking errors           -> 422, nothing written
   hash == draft version hash -> 200 created=false (name-only changes update the row, no version)
   otherwise                 -> new version (source save), draft_version_id = new, revision + 1

publish(version)              -> requires version.publish_blockers re-evaluated now == []
                                 pinned_version_id = version
unpublish                     -> pinned_version_id = null (live channels refuse calls)
restore(version, publish?)    -> draft_config = upcast(version.config minus snapshot-only blocks)
                                 new version (source restore, restored_from = version)
                                 if publish: pinned_version_id = new version
snapshot_for_test             -> version with hash of resolved draft, else new (source test)
delete                        -> refused if usage checkers report attachments; else deleted_at = now
```

The published version always belongs to the same agent (CHECK via trigger).

## 4. AgentConfig (JSON, schema_version 1)

Providers and models are strings validated against the catalog (no enums, Principle I).
"Range" is enforced on save; "Default" is what a blank agent gets (research R23).

| Path | Type | Range or values | Default |
|---|---|---|---|
| schema_version | int | 1 | 1 |
| type | string | `single_prompt`, `flow` (mirrors the agent) | from agent |
| language | string | catalog language code, e.g. `en-US`, `hi`, `multi` | `en-US` |
| llm.provider | string | catalog | catalog default (e.g. `azure_openai`) |
| llm.model | string | catalog model of provider | catalog default (e.g. `gpt-5.1`) |
| llm.temperature | number | model's `[min, max]` step, or fixed | model default |
| prompt | string | 1 to 50,000 chars (single_prompt); may be empty for flow | "" |
| begin_message | string or null | max 1,000 chars | "Hi, thanks for calling. How can I help you today?" |
| start_speaker | string | `agent`, `user` | `agent` |
| dynamic_variables[] | object | max 50; `{name, default: string or null (max 2,000), description?: max 200}` | [] |
| stt.provider | string | catalog | per-language default (e.g. `deepgram`) |
| stt.model | string or null | catalog model or null = Auto | null |
| tts.provider | string | catalog | per-language default (e.g. `elevenlabs`) |
| tts.model | string | catalog model of provider | provider default |
| tts.voice_id | string | voice of provider | per-language default voice |
| tts.speed | number | 0.5 to 2.0, step 0.1 | 1.0 |
| tts.expressiveness | number | 0 to 2, step 0.1 (ignored if provider lacks it) | 0.9 |
| tts.volume | number | 0 to 2, step 0.05 | 1.0 |
| noise_cancellation | object or null | `{provider, model}` from catalog; null = off | catalog default NC |
| call_behavior.end_on_silence_s | int | 10 to 300, step 10 | 30 |
| call_behavior.max_duration_s | int | 30 to 3,600 | 600 |
| call_behavior.ring_duration_ms | int | 0 to 30,000, step 500 | 5,000 |
| call_behavior.interruption_sensitivity | number | 0 to 1, step 0.05 | 0.9 |
| call_behavior.responsiveness | number | 0 to 1, step 0.05 | 0.8 |
| advanced.webhook_url | string or null | https, max 2,048, public host (research R20) | null |
| advanced.webhook_timeout_ms | int | 1,000 to 30,000 | 3,000 |
| advanced.voicemail_detection.enabled | bool | | false |
| advanced.voicemail_detection.action | string | `hang_up`, `leave_message` | `hang_up` |
| advanced.voicemail_detection.message | string or null | 1 to 500 chars, required for `leave_message` | null |
| advanced.dtmf.enabled | bool | | false |
| advanced.dtmf.timeout_ms | int | 1,000 to 10,000, step 500 | 2,500 |
| advanced.dtmf.termination_key | string or null | `0`-`9`, `#`, `*`, null | `#` |
| advanced.dtmf.digits | int | 1 to 99 | 10 |
| advanced.background_audio.enabled | bool | | false |
| advanced.background_audio.source | object or null | `{kind: builtin, id}` or `{kind: upload, key}`; required when enabled | null |
| advanced.background_audio.volume | number | 0 to 3, step 0.05 | 0.8 |
| advanced.analysis_model | object or null | `{provider, model}` from LLM catalog; null = use `llm` | null |
| advanced.pronunciation[] | object | max 200; `{word: 1 to 100 chars, replacement: 1 to 200 chars}`; words unique ignoring case; empty rows dropped | [] |
| tool_ids[] | string[] | owned by 005 (max 25) | [] |
| kb_ids[] | string[] | owned by 005 (max 10) | [] |
| flow | object or null | owned by 004 `{flow_id, graph, graph_hash, compiled}` | null |
| evals | object or null | owned by 007 | null |
| tools[] | object[] | **snapshot-only**, written by 005's resolver into versions, never in the draft | absent |

Built-in variable names that may not be declared: `call_id`, `channel`, `direction`,
`user_number`, `agent_number`, `timezone`, `current_time`, `current_date`, `current_datetime`.

Built-in ambient sound ids: `office_ambience`, `city_ambience`, `forest_ambience`,
`crowded_room`, `hold_music`, `keyboard_typing`, `keyboard_typing2` (shared with 003 R12).

## 5. Validation result

```text
ValidationResult {
  valid: bool                      # no errors
  errors[]:            {pointer, code, message}   # block save
  publish_blockers[]:  {pointer, code, message}   # block publish
  warnings[]:          {pointer, code, message}
  normalized_config:   AgentConfig                # defaults filled, fixed temperature applied, empty rows dropped
}
```

Codes: `required`, `out_of_range`, `invalid_format`, `not_in_catalog`, `withdrawn`, `unpriced`,
`voice_not_in_provider`, `stt_language_unsupported`, `invalid_variable`, `reserved_variable`,
`duplicate_entry`, `private_address`, `missing_reference` (005), plus warnings
`variable_without_default`, `unused_default`, `generated_greeting`, `temperature_fixed`,
`component_replaced`.

## 6. templates (Template)

Global (no RLS), app role read-only, written by the sync job (research R16).

| Column | Type | Rules |
|---|---|---|
| id | text PK | slug, `^[a-z0-9-]{3,64}$` |
| category | text, not null | `healthcare`, `banking`, `insurance`, `retail`, `telecom`, `automotive`, `real_estate`, `hospitality`, `support` |
| name | text, not null | max 80 |
| description | text, not null | max 300 |
| icon | text, not null | icon token from the design system, e.g. `stethoscope` |
| config | jsonb, not null | partial AgentConfig; must validate when overlaid on defaults |
| sort_order | int | |
| is_active | bool | false when removed from seed files |
| content_hash | char(64) | change detection for the sync |
| updated_at | timestamptz | |

## 7. ambient_audio_files (Background Audio Upload)

| Column | Type | Rules |
|---|---|---|
| id | bigint identity PK | internal only |
| workspace_id | text, not null | RLS |
| storage_key | text unique, not null | `workspaces/{ws}/ambient/{ulid}.{ext}`; the public handle |
| filename | text, not null | original name, max 200 |
| content_type | text, not null | audio/mpeg, audio/wav, audio/ogg, audio/flac, audio/aac, audio/opus |
| size_bytes | int, not null | max 10,485,760 |
| created_by | text FK users.id | |
| created_at | timestamptz | |
| deleted_at | timestamptz null | |

Limit: 20 non-deleted files per workspace.

## 8. Catalog (not tables; YAML plus 001 pricing)

```text
LlmCatalog   { default: {provider, model},
               providers[]: {id, label, models[]: {id, label, temperature: {min,max,step,default} | {fixed},
                                                    supports_tools, context_window, withdrawn?, price_per_min_usd | null}}}
VoiceCatalog { languages[]: {code, label, stt_default: {provider, model|null}, tts_default: {provider, model, voice_id}},
               stt[]: {provider, label, supports_auto, models[]: {id, label, description, languages[], withdrawn?, price_per_min_usd|null}},
               tts[]: {provider, label, capabilities: {speed, expressiveness, volume}, default_model,
                       models[]: {id, label, description, withdrawn?, price_per_min_usd|null}},
               noise_cancellation[]: {provider, model, label, description, default, price_per_min_usd|null},
               ambient_sounds[]: {id, label} }
Voice        { voice_id, name, description, gender|null, languages[], preview_url|null, model_ids[] }
```

## 9. Redis keys

| Key | TTL | Purpose |
|---|---|---|
| `voices:{provider}:{sha1(filters,cursor)}` | 1 h | voice browser cache |
| `rl:prompt_ai:{workspace_id}:{minute}` | 60 s | 20 requests per minute |

## 10. Relationships

```text
workspaces 1--* agents 1--* agent_versions
agents *--1 agent_versions (draft_version_id), agents *--0..1 agent_versions (pinned_version_id)
agent_versions 0..1--* agent_versions (restored_from)
templates 1--* agents (template_id, informational)
workspaces 1--* ambient_audio_files  (referenced by storage_key inside configs)
calls (003) *--1 agent_versions
```
