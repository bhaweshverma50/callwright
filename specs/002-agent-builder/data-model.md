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
| parent_version_id | text null FK agent_versions.id | the agent's `draft_version_id` when this version was written; null for version 1 (drives "compare with previous") |
| summary | jsonb, not null | computed at write time for the history list: `{llm_model, tts_provider, tts_voice_id, tool_count, kb_count, node_count}` (`node_count` null for single-prompt) |
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
| language | string | catalog language code (section 8.1), e.g. `en-US`, `hi`, `multi` | `en-US` |
| llm.provider | string | catalog (section 8.2) | `azure_openai` |
| llm.model | string | catalog model of provider; one id across providers | `gpt-5.1` |
| llm.temperature | number | model's `[min, max]` step, or fixed (every launch model is fixed at 1.0) | model default (1.0) |
| prompt | string | 1 to 50,000 chars (single_prompt); may be empty for flow | "" |
| begin_message | string or null | max 1,000 chars; kept but unused when `start_speaker = user` (warning `greeting_unused`) | "Hi, thanks for calling. How can I help you today?" |
| start_speaker | string | `agent`, `user` | `agent` |
| dynamic_variables[] | object | max 50; `{name, default: string or null (max 2,000), description?: max 200}` | [] |
| stt.provider | string | catalog | per-language default (e.g. `deepgram`) |
| stt.model | string or null | catalog model, or null = Auto (resolved per language by 003, section 8.3) | null |
| tts.provider | string | catalog | per-language default (e.g. `elevenlabs`) |
| tts.model | string | catalog model of provider | provider default |
| tts.voice_id | string | voice of provider | per-language default voice |
| tts.speed | number | 0.5 to 2.0, step 0.1 | 1.0 |
| tts.expressiveness | number | 0 to 2, step 0.1 (ignored if provider lacks it) | 0.9 |
| tts.volume | number | 0 to 2, step 0.05 | 1.0 |
| noise_cancellation | object or null | `{provider, model}` from catalog (section 8.5); null = off | `{provider: sanas, model: vi}` |
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
ConfigValidationResult {
  valid: bool                      # no errors
  errors[]:            ConfigIssue {pointer, code, message}   # block save
  publish_blockers[]:  {pointer, code, message}   # block publish
  warnings[]:          {pointer, code, message}
  normalized_config:   AgentConfig                # defaults filled, fixed temperature applied, empty rows dropped
}
```

Codes: `required`, `out_of_range`, `invalid_format`, `not_in_catalog`, `withdrawn`, `unpriced`,
`voice_not_in_provider`, `stt_language_unsupported`, `invalid_variable`, `reserved_variable`,
`duplicate_entry`, `private_address`, `missing_reference` (005), plus warnings
`variable_without_default`, `unused_default`, `generated_greeting`, `greeting_unused`,
`temperature_fixed`, `component_replaced` (also used when a provider switch picks the provider's
default voice for the language).

## 6. templates (Template)

Global (no RLS), app role read-only, written by the sync job (research R16).

| Column | Type | Rules |
|---|---|---|
| id | text PK | slug, `^[a-z0-9-]{3,64}$` |
| category | text, not null | `automotive`, `banking`, `ecommerce`, `healthcare`, `telecom` |
| name | text, not null | max 80 |
| description | text, not null | max 300 |
| icon | text, not null | icon token from the design system, e.g. `stethoscope` |
| direction | text, not null | `inbound` or `outbound`; informs the preview, not the config |
| config | jsonb, not null | partial AgentConfig (fields below); must validate when overlaid on defaults |
| sort_order | int | |
| is_active | bool | false when removed from seed files |
| content_hash | char(64) | change detection for the sync |
| updated_at | timestamptz | |

Fields a template config carries (FR-046): `agent_name`, `language`, `llm.provider`,
`llm.model` (never `llm.temperature` for a fixed-temperature model), `prompt`, `begin_message`,
`start_speaker`, `stt.provider` (model left null = Auto), `tts.provider`, `tts.model`, and
`dynamic_variables` with defaults. `tts.voice_id` is omitted so the language's default voice for
that provider applies. Anything else (call behaviour, advanced, tools, knowledge) comes from the
platform defaults. Model ids must be canonical catalog ids (the reference stored a drifted id,
`gpt-5.1-chat`, and mapped it in the client).

Launch set (seven templates; all single-prompt, `en-US`, `azure_openai` / `gpt-5.1`,
`start_speaker: agent`, Deepgram Auto, ElevenLabs `eleven_flash_v2_5`). Every template declares
`company_name` with a neutral fictional default (for example "Acme Bank") so a test call works
before editing. Prompts and greetings are written by Callwright; the reference templates were
read for intent and structure only.

| sort | id | Category | Name | Direction | Intent | Prompt structure | Variables (with defaults) |
|---|---|---|---|---|---|---|---|
| 1 | `banking-collections` | banking | Loan payment reminder | outbound | Remind a borrower of an overdue instalment and leave with a payment or a promise-to-pay date | Role and objective; opening with right-party check (if someone else answers: no account details, ask for a callback time); overdue amount and due date; payment options in order (pay now by link, pay at a branch, schedule a later payment); objection handling that states consequences factually (late fees, credit report) without pressure; capture the promise-to-pay date; recap and close | `company_name`, `customer_name`, `loan_type`, `overdue_amount`, `due_date` |
| 2 | `banking-loan-telesales` | banking | Personal loan offer | outbound | Present a pre-approved personal loan and complete an application with consent | Four phases: opening and permission to talk; offer (amount, tenure, rate, monthly instalment, bundled cover, fees, prepayment terms); verification (identity, employment type, two references, partial ID digits); declarations, explicit consent and next steps | `company_name`, `customer_name`, `offer_amount`, `interest_rate`, `tenure_months` |
| 3 | `telecom-plan-upgrade` | telecom | Mobile plan upgrade | outbound | Move a prepaid customer to a postpaid or family 5G plan | Four phases: opening; plan pitch (benefits, price, data, family lines); verification; confirmation and close | `company_name`, `customer_name`, `current_plan`, `offer_plan` |
| 4 | `ecommerce-credit-offer` | ecommerce | Shopping credit and membership | outbound | Offer a pay-later shopping credit line and a paid membership, then guide app activation | Four phases: opening; offer (credit limit, pay-later terms, membership benefits); verification; app onboarding steps and close | `company_name`, `customer_name`, `credit_limit` |
| 5 | `healthcare-triage-booking` | healthcare | Symptom triage and booking | inbound | Understand why the caller is calling, screen for emergencies, recommend a department and book a visit | Four phases: opening and intent; triage with an emergency check first (urgent symptoms go to emergency services; never diagnose); department recommendation and booking with detail verification; close with prescription pickup information | `company_name` |
| 6 | `automotive-roadside-ev` | automotive | Roadside and EV assistance | inbound | Handle breakdown and EV charging calls safely and dispatch help | Four phases: safety check first; issue assessment (breakdown, battery or charging, accident); location and vehicle verification; dispatch with arrival estimate and close | `company_name` |
| 7 | `healthcare-previsit-checkin` | healthcare | Pre-visit patient check-in | outbound | Prepare a patient for an upcoming appointment | Task list: confirm identity, verify insurance, update medical history, confirm appointment details, give pre-visit instructions, answer common questions; guidelines: warm tone, repeat when the patient is unsure, emergencies to emergency services, confirm before ending | `company_name`, `patient_name`, `appointment_date`, `appointment_time`, `doctor_name` |

Category labels: Automotive, Banking, E-commerce, Healthcare, Telecom; "All" is prepended by the
client. Counts at launch: automotive 1, banking 2, ecommerce 1, healthcare 2, telecom 1.

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
               providers[]: {id, label, models[]: {id, label, family, temperature: {min,max,step,default} | {fixed, reason},
                                                    supports_tools, context_window, withdrawn?, price_per_min_usd | null}}}
VoiceCatalog { languages[]: {code, label, stt_default: {provider, model|null}, tts_default: {provider, model, voice_id}},
               stt[]: {provider, label, supports_auto, default_model|null, auto_rule, models[]: {id, label, description, languages[], builtin_turn_detection, withdrawn?, price_per_min_usd|null}},
               tts[]: {provider, label, capabilities: {speed, expressiveness, volume}, default_model,
                       default_voice_by_language: {code: voice_id},
                       voice_listing: {source: live | curated, server_search, gender_filter, language_filter, previews},
                       models[]: {id, label, description, withdrawn?, price_per_min_usd|null}},
               noise_cancellation[]: {provider, model, label, description, default, price_per_min_usd|null},
               ambient_sounds[]: {id, label},
               controls[]: {path, label, min, max, step, unit, display} }
Voice        { voice_id, name, description, gender|null, languages[], preview_url|null, model_ids[] }
```

Launch contents below are exact (FR-039, FR-046 to FR-048). Prices come from 001's seed and are
repeated only for reading convenience; 002 T090 checks that every entry has an exact rate.

### 8.1 Languages (46)

`multi` Multilingual first, then by label: `ar` Arabic, `bn` Bengali, `zh` Chinese, `zh-CN`
Chinese (Simplified), `zh-TW` Chinese (Traditional), `da` Danish, `nl` Dutch, `en` English,
`en-AU` English (Australia), `en-IN` English (India), `en-NZ` English (New Zealand), `en-GB`
English (UK), `en-US` English (US), `fr` French, `fr-CA` French (Canada), `de` German, `gu`
Gujarati, `he` Hebrew, `hi` Hindi, `hi-Latn` Hindi (Latin script), `id` Indonesian, `it` Italian,
`ja` Japanese, `kn` Kannada, `ko` Korean, `ms` Malay, `ml` Malayalam, `mr` Marathi, `no`
Norwegian, `or` Odia, `pl` Polish, `pt` Portuguese, `pt-BR` Portuguese (Brazil), `pa` Punjabi,
`ru` Russian, `es` Spanish, `es-419` Spanish (Latin America), `sv` Swedish, `taq` Tamasheq, `ta`
Tamil, `te` Telugu, `th` Thai, `tr` Turkish, `uk` Ukrainian, `ur` Urdu.

Differences from the reference list of 47: its duplicate "Spanish (Latin America)" (`es-LATAM`
next to `es-419`) is dropped, and Odia uses the standard code `or` instead of `od`. A language
ships only if at least one speech recognition option and one voice cover it (T090 check);
otherwise it is withheld until covered.

Per-language defaults: STT `deepgram` Auto, except `bn`, `gu`, `hi`, `hi-Latn`, `kn`, `ml`, `mr`,
`or`, `pa`, `ta`, `te` which default to `sarvam` Auto; TTS `elevenlabs` `eleven_flash_v2_5` with the
language's default voice from `default_voice_by_language`.

### 8.2 Language models

Providers: `azure_openai` "Azure OpenAI" (default) and `openai` "OpenAI"; both offer the same three
models under the same ids. Default `{azure_openai, gpt-5.1}`.

| id | Label | Family | Temperature | Tools | Price/min | Bundles |
|---|---|---|---|---|---|---|
| `gpt-5.1` | GPT-5.1 | gpt-5 | fixed 1.0 ("This model only supports temperature 1.0") | yes | 0.0165 | 20,000 input, 200 output tokens |
| `gpt-5.2` | GPT-5.2 | gpt-5 | fixed 1.0 | yes | 0.0315 | same |
| `gpt-5-mini` | GPT-5 Mini | gpt-5 | fixed 1.0 | yes | 0.0015 | same |

Added later (003 T069, migration `s003_0004`): provider `anthropic` "Anthropic" with
`claude-haiku-5-5` "Claude Haiku 5.5" (0.0021/min) and `claude-sonnet-5-5` "Claude Sonnet 5.5"
(0.0420/min), family `claude`, temperature fixed ("This model does not take a temperature
setting"), tools yes, same bundles. Each rate is the vendor list price of the bundle. Live calls
need the platform's `ANTHROPIC_API_KEY`.

The analysis model select offers "Same as the agent's model" (null) plus these three. The
temperature rule stays data, so a later ranged model needs no editor change.

### 8.3 Speech recognition

| Provider | Model id | Label | Description (Callwright wording) | Languages | Built-in turn detection | Price/min |
|---|---|---|---|---|---|---|
| `deepgram` "Deepgram" | null | Auto | Picks Nova-3 for English, Nova-2 otherwise | all Deepgram languages | per resolved model | 0.0085 |
| | `nova-3` | Nova-3 | Most accurate for English | English variants | no | 0.0085 |
| | `nova-2` | Nova-2 | Broad language coverage (36 languages) | 36 languages | no | 0.0058 |
| | `flux-general-en` | Flux | Conversational English, lowest latency | English variants | yes | 0.0085 |
| `assemblyai` "AssemblyAI" | null | Auto | English model for English, multilingual model for es, fr, de, it, pt | English variants, es, fr, de, it, pt | yes | 0.0030 |
| | `universal-streaming` | Universal Streaming | English-focused | English variants | yes | 0.0030 |
| | `universal-streaming-multilingual` | Universal Streaming Multilingual | Spanish, French, German, Italian, Portuguese | es, fr, de, it, pt | yes | 0.0030 |
| `sarvam` "Sarvam AI" | null | Auto | Uses Saarika v2.5 | Indic languages, `en-IN` | no | 0.0060 |
| | `saarika:v2.5` | Saarika v2.5 | Transcribes in the spoken language | Indic languages, `en-IN` | no | 0.0060 |
| | `saaras:v3` | Saaras v3 | Newest Sarvam model | Indic languages, `en-IN` | no | 0.0060 |

Every provider offers Auto (`supports_auto: true`), so the model field is never blank (the
reference offered no Auto for Sarvam and showed an empty field). `auto_rule` is data:
`{default: <model>, by_language: {<code or prefix>: <model>}}`; 003 applies it at call time
and meters the resolved model.

### 8.4 Voices (text-to-speech)

| Provider | Default model | Models (label, price/min) | Voice listing |
|---|---|---|---|
| `elevenlabs` "ElevenLabs" | `eleven_flash_v2_5` | Flash v2.5 0.045; Flash v2 0.045; Turbo v2.5 0.045; Turbo v2 0.045; Multilingual v2 (highest quality) 0.090 | live: workspace plus premade voices, server search, previews |
| `cartesia` "Cartesia" | `sonic-2` | Sonic 2 0.0275; Sonic 2 (2025-03-07) 0.0275; Sonic 3 0.0275; Sonic Turbo 0.0275 | live: full list cached 1 h, local search on name and description, gender and language filters, no previews |
| `fishaudio` "Fish Audio" | `s2.1-pro` | S2.1 Pro 0.015; S2 Pro (multi-speaker) 0.015; S1 0.015 | curated: platform allow-list in `voices/catalog.yaml` (business-suitable voices with language tags), local search, language filter, previews where the vendor has samples |

All three providers support speed, expressiveness and volume. TTS bundle: 750 characters per
minute. Sarvam text-to-speech is not offered at launch (no price row; ElevenLabs Multilingual and
Flash cover the Indic languages); adding it later is one catalog entry, one pricing row and one
adapter.

### 8.5 Noise cancellation

| provider / model | Label | Description (Callwright wording) | Default | Price/min |
|---|---|---|---|---|
| `sanas` / `vi` | Voice isolation | Removes background noise and other voices; best for noisy callers | yes | 0.0000 |
| `sanas` / `st` | Standard noise removal | Removes noise and keeps every voice; best when several people speak | | 0.0000 |
| `ai_coustics` / `standard` | Lightweight noise removal | Light processing with the lowest overhead | | 0.0000 |
| null | Off | No noise cancellation | | |

### 8.6 Control ranges (FR-042, FR-047)

`controls[]` is served with the voice catalog and is the only source of ranges for the editor
and for any override UI elsewhere (004 flow nodes). Temperature ranges stay per model (8.2).

| path | Label | min | max | step | Display |
|---|---|---|---|---|---|
| `tts.speed` | Voice speed | 0.5 | 2.0 | 0.1 | `1.0x` |
| `tts.expressiveness` | Expressiveness | 0 | 2 | 0.1 | two decimals |
| `tts.volume` | Volume | 0 | 2 | 0.05 | percent of normal (1.0 = 100%) |
| `call_behavior.end_on_silence_s` | End call after silence | 10 | 300 | 10 | `30 s`, `1 min 30 s` |
| `call_behavior.max_duration_s` | Maximum call duration | 30 | 3,600 | 30 | minutes input, exact `m min s s` helper |
| `call_behavior.ring_duration_ms` | Ring time | 0 | 30,000 | 500 | seconds with one decimal (`1.5 s`) |
| `call_behavior.interruption_sensitivity` | Interruption sensitivity | 0 | 1 | 0.05 | two decimals, Low / Medium / High marks |
| `call_behavior.responsiveness` | Responsiveness | 0 | 1 | 0.05 | two decimals, Slow / Medium / Fast marks |
| `advanced.webhook_timeout_ms` | Webhook timeout | 1,000 | 30,000 | 500 | seconds |
| `advanced.dtmf.timeout_ms` | Keypad pause | 1,000 | 10,000 | 500 | seconds |
| `advanced.background_audio.volume` | Background volume | 0 | 3 | 0.05 | percent of normal (0.8 = 80%, max 300%) |

Every default in section 4 lies on its step (checked by T090). The reference showed 0.94 and 0.79
labels on 0.95 and 0.80 thumbs and used a different speed step and a 0 to 1 "stability" range on
flow nodes; one table removes both defects.

## 9. Redis keys

| Key | TTL | Purpose |
|---|---|---|
| `voices:{provider}:{sha1(filters,cursor)}` | 1 h | voice browser cache |
| `rl:prompt_ai:{workspace_id}:{minute}` | 60 s | 20 requests per minute |
| `idem:agents:{workspace_id}:{key}` | 24 h | agent id created by a create or duplicate request with this `Idempotency-Key` (FR-038) |

## 10. Relationships

```text
workspaces 1--* agents 1--* agent_versions
agents *--1 agent_versions (draft_version_id), agents *--0..1 agent_versions (pinned_version_id)
agent_versions 0..1--* agent_versions (restored_from)
templates 1--* agents (template_id, informational)
workspaces 1--* ambient_audio_files  (referenced by storage_key inside configs)
calls (003) *--1 agent_versions
```
