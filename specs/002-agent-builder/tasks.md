---
description: "Task list for 002-agent-builder"
---

# Tasks: Agent Builder

**Input**: Design documents from `specs/002-agent-builder/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md;
feature 001 phases 1 to 3 and the 001 quote endpoint (001 T069) and `charge_feature` (001 T078)

**Tests**: Required. Principle VII: contract tests for every operation, money tests for the
assistant charge and cost card parity, all written first and failing before implementation.

**Organization**: Grouped by user story (US1 to US6 from spec.md). Paths follow
research/architecture.md section 2 and plan.md.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US6; Setup, Foundational and Polish tasks carry no story label

---

## Phase 1: Setup

- [ ] T001 Create module packages with empty `router.py`, `schemas.py`, `models.py`, `service.py` under `services/api/app/{agents,agent_versions,templates,llms,voices,prompt_ai}/` and register routers in `services/api/app/main.py`
- [ ] T002 [P] Add dependencies `PyYAML`, `python-magic`, `boto3` (S3-compatible client) to `services/api/pyproject.toml`; `react-hook-form` and `diff` to `apps/web/package.json`
- [ ] T003 [P] Add `pg_trgm` extension creation to `services/api/app/migrations/versions/0005_agents.py` header and create the migration file skeletons `0005_agents.py`, `0006_templates.py`, `0007_ambient_audio.py`
- [ ] T004 Run `scripts/assemble_contracts.py` to include `specs/002-agent-builder/contracts/*.yaml` and regenerate `apps/web/src/api/schema.d.ts`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: AgentConfig, catalogs, validation, version recording, and tables every story uses.

**CRITICAL**: No user story work starts before this phase is complete.

### Tests first

- [ ] T005 [P] Unit tests for AgentConfig structure and ranges (every row of data-model.md section 4, all errors collected in one pass) in `services/api/tests/unit/agents/test_config_schema.py`
- [ ] T006 [P] Unit tests for variable extraction (`{{ name }}` spacing, invalid names flagged, reserved built-ins rejected, max 50, unused default and missing default warnings) in `services/api/tests/unit/agents/test_variables.py`
- [ ] T007 [P] Unit tests for webhook URL rules (https only outside development, IP literals and hosts resolving to loopback, RFC 1918, RFC 4193, link-local and metadata ranges refused) in `services/api/tests/unit/agents/test_webhook_url.py`
- [ ] T008 [P] Unit tests for catalog loading and pricing join (fixed vs ranged temperature, withdrawn entries hidden but resolvable, null price when no pricing row, per-language defaults) in `services/api/tests/unit/llms/test_catalog.py` and `services/api/tests/unit/voices/test_catalog.py`
- [ ] T009 [P] Unit tests for `validate_config` classification (errors vs publish blockers vs warnings; fixed temperature normalised with warning; clamp on model change; voice not in provider; STT model not covering language; single-model STT auto-selected; hook results merged) in `services/api/tests/unit/agents/test_validate_config.py`
- [ ] T010 [P] Unit tests for canonical JSON and hash stability (key order, whitespace, unicode, snapshot-only `tools` included) in `services/api/tests/unit/agent_versions/test_canonical.py`

### Implementation

- [ ] T011 Implement AgentConfig v1 Pydantic models, collect-all-errors validation, JSON Pointer mapping and the upcaster registry in `services/api/app/agents/schemas.py`
- [ ] T012 [P] Implement platform defaults (spec Assumptions, research R23) in `services/api/app/agents/defaults.py`
- [ ] T013 [P] Implement placeholder extraction and reserved names in `services/api/app/agents/variables.py`
- [ ] T014 [P] Implement webhook URL checks in `services/api/app/agents/webhook_url.py`
- [ ] T015 [P] Implement canonical JSON + sha256 in `services/api/app/agent_versions/canonical.py`
- [ ] T016 [P] Implement hook registries (`register_validator`, `register_snapshot_resolver`, `register_usage_checker`, `register_duplicate_hook`) in `services/api/app/agents/hooks.py`
- [ ] T017 [P] Write `services/api/app/llms/catalog.yaml` (launch providers and models with temperature rules) and the loader plus pricing join in `services/api/app/llms/service.py`
- [ ] T018 [P] Write `services/api/app/voices/catalog.yaml` (languages with STT/TTS defaults, STT providers and models with language coverage, TTS providers with capability flags and default models, NC options, 7 built-in ambient sounds) and the loader plus pricing join in `services/api/app/voices/service.py`
- [ ] T019 Implement `validate_config(type, config, agent_id=None)` in `services/api/app/agents/service.py` using T011 to T018 until T005 to T009 pass
- [ ] T020 Fill migration `services/api/app/migrations/versions/0005_agents.py`: `agents` and `agent_versions` tables, deferred FKs between them, type-immutability trigger, version immutability trigger, published-version-same-agent trigger, RLS policies, trigram and `jsonb_path_ops` GIN indexes
- [ ] T021 [P] Create SQLAlchemy models in `services/api/app/agents/models.py` (Agent) and `services/api/app/agent_versions/models.py` (AgentVersion)
- [ ] T022 Implement `create_version(agent_id, config, note, source, publish=False)` with per-agent numbering under row lock, snapshot resolvers, hash dedupe and publish-blocker capture in `services/api/app/agent_versions/service.py`
- [ ] T023 [P] Write integration test that `UPDATE`/`DELETE` on `agent_versions` and `UPDATE agents.type` raise, in `services/api/tests/integration/agent_versions/test_immutability.py`
- [ ] T024 [P] Add web route skeleton in `apps/web/src/app/router.tsx` for `/agents`, `/agents/new`, `/agents/templates`, `/agents/new/single`, `/agents/:id`, `/agents/:id/edit`, and the type redirect in `apps/web/src/routes/agents/agentRedirect.tsx`

**Checkpoint**: Configs validate against the catalog; versions can be recorded and are immutable.

---

## Phase 3: User Story 1 - Create and configure a single-prompt agent (Priority: P1) MVP

**Goal**: Type chooser, blank editor with all sections from catalog defaults, validation summary, save with versions and conflict detection, voice browser, ambient uploads.

**Independent Test**: Quickstart section 3: create with `{{customer_name}}`, a default, a voice and a webhook; reopen and confirm values and version 1.

### Tests for User Story 1 (write first, must fail)

- [ ] T025 [P] [US1] Contract tests for `createAgent`, `getAgentDefaults`, `validateAgentConfig`, `getAgent`, `renameAgent`, `saveAgentDraft` in `services/api/tests/contract/test_agents_contract.py`
- [ ] T026 [P] [US1] Contract tests for `contracts/llms.yaml` in `services/api/tests/contract/test_llms_contract.py`
- [ ] T027 [P] [US1] Contract tests for `contracts/voices.yaml` (catalog, voice browser with recorded vendor fixtures, ambient list/upload/delete incl. 409, 413, 415) in `services/api/tests/contract/test_voices_contract.py`
- [ ] T028 [P] [US1] Integration test for saving in `services/api/tests/integration/agents/test_save_draft.py`: create requires a valid config; change records version n+1; unchanged config returns `created=false`; name-only change records no version; stale `If-Match` returns 412 `draft_changed`; all errors returned together
- [ ] T029 [P] [US1] Unit tests for voice listing adapters normalisation and cursor paging against fixtures in `services/api/tests/unit/voices/test_adapters.py`
- [ ] T030 [P] [US1] Integration test for ambient uploads (magic-byte check, 10 MB limit, 20-file limit, signed preview URL, delete refused while referenced) in `services/api/tests/integration/agents/test_ambient_audio.py`
- [ ] T031 [P] [US1] Playwright journey chooser, blank form, aggregated errors, fixed-temperature lock, variable auto-detection, save, reload persists, leave guard, in `apps/web/tests/e2e/agents-create.spec.ts`

### Implementation for User Story 1

- [ ] T032 [US1] Implement `create_agent`, `get_agent`, `rename_agent`, `update_draft` (If-Match, validate, version via `create_version`, `draft_revision` bump) in `services/api/app/agents/service.py`
- [ ] T033 [US1] Implement API schemas and routes `/v1/agents` (POST), `/defaults`, `/validate`, `/{agent_id}` (GET, PATCH), `/{agent_id}/draft` with ETag headers in `services/api/app/agents/schemas.py` and `services/api/app/agents/router.py`
- [ ] T034 [P] [US1] Implement `GET /v1/llms/catalog` in `services/api/app/llms/router.py` and `services/api/app/llms/schemas.py`
- [ ] T035 [P] [US1] Implement voice listing adapters in `services/api/app/voices/adapters/elevenlabs.py`, `cartesia.py`, `fishaudio.py`, `sarvam.py` (static from YAML) with Redis caching in `services/api/app/voices/service.py`
- [ ] T036 [US1] Implement migration `services/api/app/migrations/versions/0007_ambient_audio.py`, model in `services/api/app/voices/models.py`, upload/list/delete service with S3 and usage check via `jsonb_path_ops` lookup in `services/api/app/voices/service.py`
- [ ] T037 [US1] Implement routes `GET /v1/voices/catalog`, `GET /v1/voices/{provider}/voices`, `/v1/voices/ambient-audio` in `services/api/app/voices/router.py` and `services/api/app/voices/schemas.py`
- [ ] T038 [P] [US1] Build `apps/web/src/routes/agents/NewAgentTypePage.tsx` (two cards, bullets, "cannot be changed later", continue to templates or flow creation)
- [ ] T039 [US1] Build `apps/web/src/routes/agents/editor/useAgentDraft.ts` (react-hook-form, debounced `POST /v1/agents/validate`, pointer-to-field error mapping, save via POST then PUT with If-Match, 412 handling) and `AgentEditorPage.tsx` (header with copyable agent id, version badge, Save, wrong-type guard for flow agents, LeaveGuard and ErrorSummaryDialog from 001)
- [ ] T040 [P] [US1] Build `apps/web/src/routes/agents/editor/BasicSection.tsx`, `ModelPicker.tsx`, `TemperatureControl.tsx` (fixed lock with reason, clamp notice), `VariablesEditor.tsx` (auto-detected plus manual, defaults, reserved and unused markers)
- [ ] T041 [P] [US1] Build `apps/web/src/routes/agents/editor/VoiceSection.tsx`, `SttPickerDialog.tsx` (Auto, single-model lock), `VoicePickerDialog.tsx` (search, gender and language filters, preview where available, retry on 503), `NoiseCancellationSelect.tsx`
- [ ] T042 [P] [US1] Build `apps/web/src/routes/agents/editor/CallBehaviorSection.tsx` (silence 10 to 300 s slider, max duration in minutes, ring time, interruption and responsiveness with Low/Medium/High labels)
- [ ] T043 [P] [US1] Build `apps/web/src/routes/agents/editor/AdvancedSection.tsx`, `WebhookField.tsx`, `BackgroundAudioField.tsx` (built-ins plus "Your uploads", upload, volume as percent), `PronunciationEditor.tsx`, voicemail and keypad subsections, analysis model select
- [ ] T044 [US1] Extend `services/api/tests/integration/test_rls_isolation.py` for `agents`, `agent_versions`, `ambient_audio_files`

**Checkpoint**: A single-prompt agent can be created, edited and saved with versions recorded.

---

## Phase 4: User Story 2 - Find and manage agents (Priority: P1)

**Goal**: List with search and type filter, duplicate, delete with usage guard.

**Independent Test**: Quickstart section 4.

### Tests for User Story 2 (write first, must fail)

- [ ] T045 [P] [US2] Contract tests for `listAgents`, `duplicateAgent`, `deleteAgent` in `services/api/tests/contract/test_agents_list_contract.py`
- [ ] T046 [P] [US2] Integration tests in `services/api/tests/integration/agents/test_list_search.py`: partial name case-insensitive, exact id, type filter, newest-updated first, pagination, deleted agents hidden
- [ ] T047 [P] [US2] Integration tests in `services/api/tests/integration/agents/test_duplicate_delete.py`: duplicate name "(copy)", same draft, version 1 `source=duplicate`, no published version, duplicate hooks called; delete soft, versions still readable by id, registered usage checker produces 409 `agent_in_use`
- [ ] T048 [P] [US2] Performance test: 1,000 agents, search p95 under 300 ms, in `services/api/tests/integration/agents/test_list_perf.py`

### Implementation for User Story 2

- [ ] T049 [US2] Implement `list_agents` (trigram search, exact id short-circuit, summaries with published version), `duplicate_agent`, `delete_agent` in `services/api/app/agents/service.py`
- [ ] T050 [US2] Add routes `GET /v1/agents`, `POST /v1/agents/{agent_id}/duplicate`, `DELETE /v1/agents/{agent_id}` in `services/api/app/agents/router.py`
- [ ] T051 [P] [US2] Build `apps/web/src/routes/agents/AgentsListPage.tsx` and `AgentCard.tsx` (badges, model, voice, language, published version, dates, search box, type filter, empty state, duplicate, delete confirm with attachment list on 409)

**Checkpoint**: US1 and US2 work independently.

---

## Phase 5: User Story 3 - Track, compare, publish and restore versions (Priority: P2)

**Goal**: History, keyed diff, publish/unpublish with blocker re-check, restore (optionally publish), test snapshots for 003.

**Independent Test**: Quickstart section 5: three saves, compare 1 vs 3, publish 2, restore 1, history shows 4 with 2 published.

### Tests for User Story 3 (write first, must fail)

- [ ] T052 [P] [US3] Contract tests for all `contracts/agent_versions.yaml` operations in `services/api/tests/contract/test_agent_versions_contract.py`
- [ ] T053 [P] [US3] Unit tests for the keyed diff (variables by name, pronunciation by word ignoring case, tool ids by value, scalar replace, add/remove, stable ordering) in `services/api/tests/unit/agent_versions/test_diff.py`
- [ ] T054 [P] [US3] Integration tests in `services/api/tests/integration/agent_versions/test_publish_restore.py`: publish sets pointer; publish re-evaluates blockers against current catalog (withdrawn component refused 422 `publish_blocked`); unpublish; restore records `source=restore` with `restored_from`; restore with `publish=true`; restore with stale If-Match 412; versions of a deleted agent readable
- [ ] T055 [P] [US3] Integration test in `services/api/tests/integration/agent_versions/test_snapshot_for_test.py`: unchanged draft reuses the draft version; changed resolved tools produce a `source=test` version; published pointer untouched; hidden from history unless `include_test=true`
- [ ] T056 [P] [US3] Vitest for `versionLabels.ts` coverage (every AgentConfig path in data-model section 4 has a label) in `apps/web/src/routes/agents/versions/versionLabels.test.ts`
- [ ] T057 [P] [US3] Playwright journey history drawer, compare with readable labels and line diff, publish badge, restore in 3 clicks, in `apps/web/tests/e2e/agents-versions.spec.ts`

### Implementation for User Story 3

- [ ] T058 [US3] Implement keyed diff in `services/api/app/agent_versions/diff.py` until T053 passes
- [ ] T059 [US3] Implement `list_versions`, `get`, `get_published`, `diff`, `publish`, `unpublish`, `restore`, `snapshot_for_test` in `services/api/app/agent_versions/service.py`
- [ ] T060 [US3] Implement schemas and routes in `services/api/app/agent_versions/schemas.py` and `services/api/app/agent_versions/router.py`
- [ ] T061 [P] [US3] Build `apps/web/src/routes/agents/versions/VersionDrawer.tsx` (newest first, published and draft badges, source, note, author), `VersionCompare.tsx` (labels, old/new, line diff via `diff`), `versionLabels.ts`
- [ ] T062 [P] [US3] Build `apps/web/src/routes/agents/versions/PublishButton.tsx` (publish draft version, show blockers, unpublish with confirm) and wire restore confirm ("restore to draft" or "restore and publish") into `VersionDrawer.tsx`

**Checkpoint**: Versions support 003 (test snapshots, published version) and 004 (create_version).

---

## Phase 6: User Story 4 - See what a minute will cost while configuring (Priority: P2)

**Goal**: Cost card from 001's quote, prices in pickers, unpriced lines, surcharge-risk notice.

**Independent Test**: Quickstart section 6.

### Tests for User Story 4 (write first, must fail)

- [ ] T063 [P] [US4] Money test in `services/api/tests/integration/agents/test_cost_card_parity.py`: for default, NC-off and premium selections, the per-minute total from `POST /v1/pricing/quote` equals the sum of the catalog `price_per_min_usd` values shown in pickers plus platform; unpriced component makes `complete=false` and a publish blocker `unpriced`
- [ ] T064 [P] [US4] Vitest for `apps/web/src/routes/agents/editor/surchargeRisk.test.ts` (about 3,300 words triggers at a 20,000 bundle, 1,000 words does not, bundle read from quote)
- [ ] T065 [P] [US4] Vitest for `apps/web/src/routes/agents/editor/CostCard.test.tsx` (five lines, NC line hidden when off, "price unavailable", total marked incomplete, refetch on selection change only)

### Implementation for User Story 4

- [ ] T066 [US4] Build `apps/web/src/routes/agents/editor/CostCard.tsx` (debounced 250 ms quote query keyed by selection, lines, total, bundle explainer) and `surchargeRisk.ts`
- [ ] T067 [P] [US4] Show per-minute price in `ModelPicker.tsx`, `SttPickerDialog.tsx` and the voice model select in `VoiceSection.tsx` from catalog `price_per_min_usd`

**Checkpoint**: Cost visible at every priced choice.

---

## Phase 7: User Story 5 - Start from an industry template (Priority: P2)

**Goal**: Template picker with categories, preview, use template into the editor.

**Independent Test**: Quickstart section 7.

### Tests for User Story 5 (write first, must fail)

- [ ] T068 [P] [US5] Contract tests for `contracts/templates.yaml` in `services/api/tests/contract/test_templates_contract.py`
- [ ] T069 [P] [US5] Seed test in `services/api/tests/unit/templates/test_seed_files.py`: every `seed/*.yaml` parses, overlays on defaults without errors, has a unique slug, and every category has at least one template
- [ ] T070 [P] [US5] Integration tests in `services/api/tests/integration/templates/test_sync_and_use.py`: sync upserts by slug and deactivates removed files; `POST /v1/agents {template_id}` overlays template on defaults, sets `template_id`, version 1 `source=template` noting the template, unavailable voice replaced with language default plus `component_replaced` warning; inactive template 404

### Implementation for User Story 5

- [ ] T071 [US5] Implement migration `services/api/app/migrations/versions/0006_templates.py` and model in `services/api/app/templates/models.py`
- [ ] T072 [P] [US5] Write launch templates in `services/api/app/templates/seed/` (at least one each for healthcare, banking, insurance, retail, telecom, automotive, real_estate, hospitality, support; original Callwright copy)
- [ ] T073 [US5] Implement sync job in `services/api/app/templates/jobs.py` (CLI `python -m app.templates.jobs sync`, run on deploy) and list/get/categories in `services/api/app/templates/service.py`
- [ ] T074 [US5] Implement routes in `services/api/app/templates/router.py` and `services/api/app/templates/schemas.py`; add the template overlay path to `create_agent` in `services/api/app/agents/service.py`
- [ ] T075 [P] [US5] Build `apps/web/src/routes/agents/TemplatesPage.tsx` ("Start from scratch" first, "All" plus category chips, search) and `TemplatePreviewDialog.tsx` (prompt, greeting, language, "Use template" opens the editor)

**Checkpoint**: Template path to a saved agent in under 3 minutes (SC-001).

---

## Phase 8: User Story 6 - Write the prompt with AI help (Priority: P3)

**Goal**: Charged, rate-limited, stateless assistant with apply and undo in the editor.

**Independent Test**: Quickstart section 8.

### Tests for User Story 6 (write first, must fail)

- [ ] T076 [P] [US6] Contract tests for `contracts/prompt_ai.yaml` (200, 402, 422, 429, 504) in `services/api/tests/contract/test_prompt_ai_contract.py`
- [ ] T077 [P] [US6] Money tests in `services/api/tests/integration/prompt_ai/test_charging.py`: one `feature_charge` and one `prompt_generation` usage event per successful request; same `Idempotency-Key` charges once; nothing charged on 402, 429 or 504
- [ ] T078 [P] [US6] Unit tests for proposal extraction (reply only, reply with proposal, malformed proposal ignored, invalid variable names dropped) in `services/api/tests/unit/prompt_ai/test_proposal.py`
- [ ] T079 [P] [US6] Vitest for `apps/web/src/routes/agents/editor/AssistantPanel.test.tsx` (proposal diff shown, Apply marks form dirty without saving, Undo restores, add-funds message on 402)

### Implementation for User Story 6

- [ ] T080 [US6] Implement the API-side model gateway `services/api/app/llms/client.py` with adapters `services/api/app/llms/adapters/azure_openai.py`, `openai.py`, `anthropic.py` and a deterministic `fake.py` for dev and tests
- [ ] T081 [US6] Write assistant instructions in `services/api/app/prompt_ai/system_prompt.md` and implement `services/api/app/prompt_ai/service.py` (credit refusal, 20/min limit via `core/rate_limit.py`, 60 s timeout, proposal parsing, `billing.charge_feature`)
- [ ] T082 [US6] Implement `POST /v1/prompt-ai/generate` in `services/api/app/prompt_ai/router.py` and `services/api/app/prompt_ai/schemas.py`
- [ ] T083 [P] [US6] Build `apps/web/src/routes/agents/editor/AssistantPanel.tsx` (chat, proposal card with diff against current prompt, Apply, Undo)

**Checkpoint**: All six stories independently functional.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T084 [P] OpenTelemetry spans for save, publish, validate and vendor voice listing in `services/api/app/agents/service.py`, `services/api/app/agent_versions/service.py`, `services/api/app/voices/service.py`
- [ ] T085 [P] Keyboard and screen-reader pass on the editor sections, dialogs and version drawer in `apps/web/src/routes/agents/`
- [ ] T086 [P] Document the interfaces for 003, 004, 005, 007, 010 (table in plan.md) as docstrings in `services/api/app/agents/hooks.py` and `services/api/app/agent_versions/service.py`
- [ ] T087 Run `scripts/assemble_contracts.py --check` and the drift test, then every step of `specs/002-agent-builder/quickstart.md`

---

## Phase 10: Cross-spec additions (architecture v1.1)

**Purpose**: AgentConfig fields other features rely on. Added during cross-spec reconciliation on 2026-10-16.

- [ ] T088 [P] Add `recording` (`inherit | on | off`, default `inherit`) to AgentConfig in `services/api/app/agents/schemas.py`, the editor's Advanced tab in `apps/web/src/routes/agents/`, and `validate_config`; resolved at call admission by 003 against 001's `recording_default`
- [ ] T089 Accept snapshot-only `knowledge` block (kb ids plus retrieval settings resolved by 005) alongside `tools` and `flow` in version snapshots in `services/api/app/agent_versions/service.py`; contract test update in `services/api/tests/contract/test_agent_versions_contract.py`

## Dependencies & Execution Order

### Phase Dependencies

- Setup (Phase 1): after 001 Phase 2; T004 after T001
- Foundational (Phase 2): after Setup; blocks all stories; T019 after T011 to T018; T022 after T020 and T021
- US1 (Phase 3): after Foundational
- US2 (Phase 4): after Foundational; UI duplicates/deletes agents created in US1 but tests seed their own
- US3 (Phase 5): after Foundational; UI drawer mounts in the US1 editor (T039)
- US4 (Phase 6): after US1 editor (T039, T040, T041); needs 001 quote (001 T069)
- US5 (Phase 7): after Foundational; editor hand-off needs T039
- US6 (Phase 8): after US1 editor; needs 001 `charge_feature` (001 T078)
- Polish (Phase 9): after the stories in scope

### Downstream features

- 003 needs: `snapshot_for_test`, `get_published`, `get` (US3)
- 004 needs: `create_agent` (US1), `create_version` (Foundational), hooks (Foundational)
- 005 needs: `update_draft` (US1), `register_snapshot_resolver` and `register_validator` (Foundational)
- 010 needs: `register_usage_checker` (Foundational), `get_published` (US3)

### Within Each Story

Tests first and failing, then migrations and models, services, routes, UI.

### Parallel Opportunities

- Foundational: T005 to T010 together; T012 to T018 together
- US1: T025 to T031 together; T034, T035 together; T038, T040 to T043 together after T039 is stubbed
- US3: T052 to T057 together; T061, T062 together
- US5: T068 to T070 together; T072 and T075 alongside T071 to T074

## Parallel Example: User Story 1

```bash
Task: "Contract tests for agents in services/api/tests/contract/test_agents_contract.py"
Task: "Contract tests for llms in services/api/tests/contract/test_llms_contract.py"
Task: "Contract tests for voices in services/api/tests/contract/test_voices_contract.py"
Task: "Save-draft integration test in services/api/tests/integration/agents/test_save_draft.py"
Task: "Voice adapter tests in services/api/tests/unit/voices/test_adapters.py"
```

## Implementation Strategy

### MVP First

1. Phases 1 and 2.
2. US1 (create and save) and US2 (list and manage): an operator can build and find agents.
3. Then US3 so 003 can run test calls against versions and live channels against published ones.

### Incremental Delivery

US4 (cost card) and US5 (templates) next, both P2 and independent of each other; US6 last.

## Notes

- Never write `tools` (snapshot-only) from the draft save path; only resolvers add it to versions.
- Catalog YAML changes are data changes: add a pricing row in 001's catalog in the same release.
- Keep validation in one function (`validate_config`); the editor never re-implements catalog rules.
