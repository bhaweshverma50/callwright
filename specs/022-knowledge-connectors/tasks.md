---
description: "Task list for 022-knowledge-connectors (Google Drive knowledge sync)"
---

# Tasks: Google Drive knowledge sync

**Input**: Design documents from `specs/022-knowledge-connectors/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/connectors.yaml,
quickstart.md; 001 to 013 merged (migration head `s002_0005`). If 023 merges first, rebase the
migration's `down_revision` onto 023's head.

**Branch**: `knowledge-connectors`. Spec-kit scripts need `SPECIFY_FEATURE=022-knowledge-connectors`
because the branch name has no number.

**Tests**: Required (Principle VII). Contract tests, the sync safety tests (diff, content gates,
mass-archive guard, error classification) and the money tests are written first and must fail
before implementation. API tests run against `FakeDriveClient` (`CONNECTORS_DRIVE_MODE=fake`); no
test reaches Google.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US5 from spec.md

---

## Phase 1: Setup

- [X] T001 Add `022-knowledge-connectors` to `contracts/features.txt` and run `make contracts` to regenerate `contracts/openapi.yaml`; confirm `make contracts-check` passes
- [X] T002 [P] Add settings to `services/api/app/core/config.py`: `google_oauth_client_id: str = ""`, `google_oauth_client_secret: SecretStr = SecretStr("")` (accepts `enc:v1:`), `google_oauth_redirect_uri: str = ""`, `connectors_drive_mode: Literal["live", "fake"] = "live"`, and a `google_configured` property (all three set); staging and prod refuse `fake` mode in the existing dev-default check
- [X] T003 [P] Add `GOOGLE_OAUTH_CLIENT_SECRET` to `OPTIONAL_SECRETS` and `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_REDIRECT_URI` to the API and worker env in `deploy/cloudrun/deploy.sh` and `deploy/vm/render-env.sh`; document all four in `docs/OPERATIONS.md` with the Google Cloud setup steps (Drive and Sheets APIs, consent screen in Testing, test users, scopes `openid email drive.readonly spreadsheets`, redirect URIs) and the 7-day refresh-token expiry in Testing mode (research R16)
- [X] T004 [P] Add the 022 row (`connectors, knowledge (sources)` | `/settings/connections, knowledge base Sources panel`) to section 3 and the prefixes `conn_`, `ksrc_`, `ksr_` to section 4 of `research/architecture.md`

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: tables, models, the Drive client port and fake, module registration and the shared
contract changes. Every story needs these.

### Tests first

- [X] T005 [P] Unit test the fake Drive client in `services/api/tests/unit/test_fake_drive.py`: seeded tree with folders, subfolders, a shared drive, Docs, PDF, DOCX, Sheet, shortcut and oversize files; `list_tree` pages and walks subfolders; `download`/`export` return bytes; `revoke`, `outage` and `unshare` switches raise the error classes from research R6
- [X] T006 [P] Migration test in `services/api/tests/integration/test_migration_s022.py`: the five new tables have RLS forced and the tenant policy; `connector_activity` refuses UPDATE and DELETE for `callwright_app`; `kb_documents.status` accepts `archived`; the four `SECURITY DEFINER` functions exist and return only ids and workspace ids

### Implementation

- [X] T007 Write migration `services/api/app/migrations/versions/s022_0001_drive_sync.py` (revision `s022_0001`, down `s002_0005`): create `connections`, `kb_sources`, `kb_source_files`, `kb_sync_runs`, `connector_activity` with columns, CHECKs, uniques and indexes from data-model.md; the inline RLS block per table (grants SELECT, INSERT only on `connector_activity`); alter `kb_documents`: replace the status CHECK to add `archived`, add `archived_at`, add `source_id` FK ON DELETE SET NULL, and the two partial indexes; create `kb_sources_due`, `kb_sources_workspace_for`, `kb_documents_archived_before`, `kb_sync_runs_before` as `LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public` with `REVOKE ALL FROM PUBLIC` and `GRANT EXECUTE TO callwright_app` (depends on T006)
- [X] T008 [P] ORM models `Connection`, `ConnectorActivity` in `services/api/app/connectors/models.py`
- [X] T009 [P] ORM models `KnowledgeSource`, `SourceFile`, `SyncRun` and new `Document.archived_at`, `Document.source_id` in `services/api/app/knowledge/models.py`
- [X] T010 [P] Drive client port in `services/api/app/knowledge/sources/drive.py`: dataclasses `DriveItem` (id, name, mime_type, parents, path, md5, version, size, web_view_link, is_folder, is_shortcut, trashed), `DriveRoot`; protocol `DriveClient` (`refresh(refresh_token) -> AccessToken`, `account(token)`, `get_root(token, root_kind, root_id, drive_id)`, `list_tree(token, root, include_subfolders, max_items=5000)`, `list_folders(token, parent, drive_id, page_token)`, `list_shared_drives(token, page_token)`, `download(token, file_id)`, `export_docx(token, file_id)`); error classes `TokenRevoked`, `RootUnavailable`, `GoogleTemporary`, `FileUnavailable`, `SourceTooLarge`, `ExportTooLarge`
- [X] T011 [P] `FakeDriveClient` with an in-memory tree and switches (`revoke`, `outage`, `unshare`, `corrupt`, `touch_metadata`) plus presets `clinic`, `property`, `big` in `services/api/app/knowledge/sources/fake_drive.py` (depends on T010; T005 passes)
- [X] T012 `HttpDriveClient` in `services/api/app/knowledge/sources/http_drive.py` on the shared `httpx.AsyncClient`: token endpoint `https://oauth2.googleapis.com/token`, Drive v3 `files.get`, `files.list` (fields limited to what `DriveItem` needs, `pageSize=1000`, `supportsAllDrives`, `includeItemsFromAllDrives`, `corpora=drive` for shared drives), `drives.list`, `alt=media` download and `files.export` DOCX; maps responses to the R6 error classes; retries `GoogleTemporary` 3 times (1, 4, 16 s with jitter); calls only `oauth2.googleapis.com` and `www.googleapis.com/drive/v3`, never the Sheets API (FR-007a), asserted by a unit test with a recording transport in `services/api/tests/unit/test_http_drive.py` (depends on T010)
- [X] T013 `drive_client(settings, http)` factory in `services/api/app/knowledge/sources/__init__.py` selecting live or fake by `connectors_drive_mode`, exposed on the runtime for API and worker (depends on T011, T012)
- [X] T014 [P] `record(session, action, subject_type, subject_id, actor_user_id, detail)` in `services/api/app/connectors/activity.py`
- [X] T015 Register the `connectors` feature: `services/api/app/connectors/install.py` (`FEATURE = Feature("connectors", routers=(router,), id_prefixes=frozenset({"conn"}))`) and add it to `FEATURES` in `services/api/app/features.py` before `knowledge`; add `{"ksrc", "ksr"}` to the knowledge feature's `id_prefixes` in `services/api/app/knowledge/install.py` (depends on T008, T009)
- [X] T016 Extend `specs/005-tools-knowledge/contracts/knowledge.yaml`: `DocumentStatus` adds `archived`; `Document` adds `archived_at`, `managed` (boolean) and `source` (`$ref` to 022's `DocumentSource`, nullable); `KnowledgeBase` adds `archived_count` and `source_count`; `GET /knowledge-bases/{kb_id}/documents` `status` filter adds `archived`; Replace upload and document DELETE document 409 `managed_by_source`; run `make contracts` (depends on T001)
- [X] T017 Run `pnpm gen:api` in `apps/web` to refresh `apps/web/src/api/schema.d.ts` and `apps/web/src/lib/contract.gen.ts` (depends on T016)
- [X] T018 [P] Dev routes in `services/api/app/dev/router.py` (only with `ENABLE_DEV_ROUTES` and fake mode, registered with `include_in_schema=False` so the contract drift test ignores them, like the existing dev routes): `POST /dev/fake-drive/seed {preset}`, `POST /dev/fake-drive/change {edits, renames, deletes, adds, touch_metadata, corrupt}`, `POST /dev/fake-drive/revoke`, `POST /dev/fake-drive/outage {on}` (depends on T011)
- [X] T019 [P] Web mock module `apps/web/src/mocks/connectors/store.ts` and `handlers.ts` (connections, OAuth start and complete, drive folders, sources, runs, restore) registered in `apps/web/src/mocks/registry.ts`; extend the knowledge mocks in `apps/web/src/mocks/tools.ts` with `source`, `managed`, `archived` documents (depends on T017)

**Checkpoint**: migration applies on a fresh and an existing database; existing knowledge tests pass unchanged; T005 and T006 pass.

---

## Phase 3: User Story 1, connect a Google account (Priority: P1) MVP part 1

**Goal**: the owner connects a Google account with read-only Drive (required) and Sheets
(optional, unused) access, sees its health, tests it, reconnects it and removes it.

**Independent test**: quickstart A1; revoke through the fake client and Test shows "revoked".

### Tests first

- [X] T020 [P] [US1] Contract tests for `/connections`, `/connections/google/start`, `/connections/google/complete`, `/connections/{id}`, `/connections/{id}/test` in `services/api/tests/contract/test_connectors_contract.py` (google_configured false returns 503 `connector_unavailable`)
- [X] T021 [P] [US1] Unit tests in `services/api/tests/unit/test_oauth_state.py`: state is single use, expires after 600 s, is bound to workspace and user; PKCE S256 challenge matches the verifier; the authorization URL carries the four scopes, `access_type=offline`, `prompt=consent`, `include_granted_scopes=true` and the configured redirect URI
- [X] T022 [P] [US1] Integration tests in `services/api/tests/integration/test_connections_flow.py`: complete creates a connection with email, scopes, `sheets_access` true and `healthy`; `error=access_denied` creates nothing (`oauth_declined`); Drive scope missing returns `oauth_scope_missing`; Sheets missing creates the connection with `sheets_access` false; the same Google `sub` again reconnects the existing row (200); state from another workspace is refused; Test after `revoke` sets `revoked`; remove with a source row present returns 409 `connection_in_use` listing it; remove revokes at Google and deletes the secret; a non-owner gets 403; reconnect signed in with a different Google account returns 400 `oauth_account_mismatch` and changes nothing; no response body contains a token; with `caplog` at DEBUG across connect, test, sync and remove, no refresh token, access token, authorization code or PKCE verifier appears in any log record (FR-004); every add, reconnect and remove writes `connector_activity`

### Implementation

- [X] T023 [P] [US1] Schemas `Connection`, `ConnectionDetail`, `ConnectionUser`, `ConnectorActivity`, start and complete bodies in `services/api/app/connectors/schemas.py` matching `contracts/connectors.yaml`
- [X] T024 [US1] OAuth helpers in `services/api/app/connectors/oauth.py`: `start(redis, workspace_id, user_id, connection_id)` storing `{workspace_id, user_id, verifier, connection_id}` under `oauth_state:{state}` for 600 s and building the authorization URL; `consume_state` (GETDEL); `exchange_code` (token endpoint with PKCE verifier); `id_token_claims` (decode the ID token returned over TLS by the token endpoint, check `aud` equals the client id and `iss`); `revoke(token)` best effort (depends on T002, T021)
- [X] T025 [US1] Connection service in `services/api/app/connectors/service.py`: `complete(...)` (scope checks; when the state names a connection, a different `sub` raises `oauth_account_mismatch` with the masked email; upsert by `(workspace_id, provider, account_subject)`, `put_secret` under `conn:{id}:refresh`, activity); `access_token(session, conn)` (refresh through the Drive client, update `last_success_at` or mark `revoked` on `TokenRevoked` and set every source of the connection to `needs_attention / access_lost`); `test(...)`; `remove(...)` (409 with users, revoke, `delete_secret`, activity); `list_with_users(...)` (depends on T014, T024)
- [X] T026 [US1] Router in `services/api/app/connectors/router.py`: the five connection operations; owner-only dependency on start, complete, remove; 503 `connector_unavailable` when not configured; declare every non-2xx status from the contract in each route's `responses=` so `test_statuses_match` passes (depends on T023, T025; T020 and T022 pass)
- [X] T027 [P] [US1] Web API hooks in `apps/web/src/api/connections.ts`: `useConnections`, `useConnection`, `startGoogleConnection`, `completeGoogleConnection`, `testConnection`, `deleteConnection`; query keys `connectionKeys`
- [X] T028 [P] [US1] Paths `CONNECTIONS_PATH = "/settings/connections"` and `CONNECTIONS_CALLBACK_PATH = "/settings/connections/callback"` in `apps/web/src/lib/paths.ts`; lazy routes in `apps/web/src/router.tsx` under the shell
- [X] T029 [US1] `ConnectionsPage` and `ConnectionCard` in `apps/web/src/routes/settings/connections/`: empty state with "Connect Google"; card with email, "Drive (read-only)", "Sheets" with the note "Not used until the Google Sheets tool is turned on" or "Sheets access not granted" with Reconnect, health `Badge`, last success, Test, Reconnect, Remove (`ConfirmDialog`; 409 lists the knowledge bases using it); "Google Drive is not configured on this server" when `google_configured` is false (depends on T027, T028)
- [X] T030 [US1] `ConnectionCallback` page in `apps/web/src/routes/settings/connections/ConnectionCallback.tsx`: reads `code`, `state`, `error`, posts once (single in-flight request as in `routes/public/VerifyEmail.tsx`), shows the result and links back; removes the query string (depends on T027, T028)
- [X] T031 [P] [US1] Link card "Connections: Google Drive and Sheets" on `apps/web/src/routes/settings/SettingsPage.tsx`
- [X] T032 [P] [US1] Web tests `apps/web/src/routes/settings/connections/ConnectionsPage.test.tsx` and `ConnectionCallback.test.tsx`: empty, healthy, revoked, Sheets not granted, not configured, declined callback, success callback

**Checkpoint**: quickstart A1 passes in fake mode.

---

## Phase 4: User Story 2, sync a knowledge base from a Drive folder (Priority: P1) MVP part 2

**Goal**: add a folder or shared drive as a source; the first sync imports Docs, PDF and DOCX,
lists skipped files, and only agents with the knowledge base attached can search them.

**Independent test**: quickstart A2.

### Tests first

- [X] T033 [P] [US2] Contract tests for `/connections/{id}/drive/shared-drives`, `/connections/{id}/drive/folders`, `GET/POST /knowledge-bases/{kb_id}/sources`, `GET /knowledge-bases/{kb_id}/sources/{source_id}` and the changed `Document` schema in `services/api/tests/contract/test_connectors_contract.py` and `services/api/tests/contract/test_knowledge_contract.py`
- [X] T034 [P] [US2] Unit tests for the add path of the diff in `services/api/tests/unit/test_sync_diff.py`: new supported files become adds; Sheets, Slides, Forms, images become `unsupported_type`; shortcuts `shortcut`; size over 20 MiB `too_large`; folders are walked not imported; subfolders excluded when `include_subfolders` is false; trashed items ignored
- [X] T035 [P] [US2] Integration tests in `services/api/tests/integration/test_source_first_sync.py`: `clinic` preset imports 10 documents with `source` and `web_view_link` and lists 2 skipped with reasons; documents become ready through `ingest_document`; Replace upload and DELETE on a synced document return 409 `managed_by_source`; reprocess of a failed synced document is allowed; the same file through two sources of one knowledge base yields one document and one `duplicate` entry; a file identical to an uploaded document is `duplicate` with `duplicate_of_doc_id`; with 195 documents already present only 5 import and the rest are `kb_full` with the source `needs_attention / kb_full`; adding the same folder twice returns 409 `source_exists`; a revoked connection returns 409 `connection_revoked`; `source_added` activity is written
- [X] T036 [P] [US2] Isolation test in `services/api/tests/integration/test_source_isolation.py` (SC-005): two agents, two knowledge bases with separate sources; `POST /internal/knowledge/search` for each agent's version returns only its own knowledge base's passages, and requesting the other knowledge base is refused; the fake Drive client's call counter does not change during any search (SC-004)
- [X] T037 [P] [US2] Money test in `services/api/tests/integration/test_sync_charges.py` (first part): a first sync of N files charges `knowledge_ingestion` once per document with key `kb_ingest:{doc}:{sha}`; re-running the same sync job after a crash before the run finished charges nothing extra

### Implementation

- [X] T038 [US2] Refactor `services/api/app/knowledge/service.py`: extract `intake(session, store, kb, data, *, file_name, display_name, uploaded_by, source_id=None, replace_doc_id=None) -> IntakeResult` (size, sniff, sha256, `duplicate_matches`, quotas, row, storage put) used by `create_document`; for `source_id` set, upload-only warnings are skipped and outcomes are returned as `created | duplicate(doc_id) | kb_full | workspace_storage_full`; existing upload behaviour and tests unchanged
- [X] T039 [US2] Managed documents in `services/api/app/knowledge/service.py` and `router.py`: 409 `managed_by_source` on Replace (when `replace_doc_id` targets a synced document) and DELETE; serialize `managed` and `source` (join `kb_source_files` on `doc_id` and `kb_sources`) in document responses (depends on T038)
- [X] T040 [P] [US2] Schemas `KnowledgeSource`, `KnowledgeSourceCreate`, `KnowledgeSourceDetail`, `SourceFileIssue`, `SyncRun`, `SyncCounts`, `DriveFolder`, `DriveFolderPage` in `services/api/app/knowledge/sources/schemas.py`
- [X] T041 [US2] Pure diff in `services/api/app/knowledge/sources/diff.py`: `plan(listing, known_files, include_subfolders) -> SyncPlan(adds, updates, renames, removals, skips, unchanged)` with the add and skip rules (updates, renames and removals are filled in US3) (depends on T034)
- [X] T042 [US2] Sync engine in `services/api/app/knowledge/sources/sync.py` for the first sync and adds: lock the source `FOR UPDATE SKIP LOCKED`, create the `running` run, get the access token through `connectors.service.access_token`, `get_root`, `list_tree`, `plan`, download or export each add (`ExportTooLarge` becomes `export_too_large`, `FileUnavailable` becomes `download_failed`), `intake` with `source_id`, enqueue `ingest_document`, upsert `kb_source_files`, finish the run with counts and up to 500 errors, set state, `root_name`, `last_success_at`, `next_sync_at` (depends on T013, T025, T038, T041)
- [X] T043 [US2] Job `sync_source(ctx, source_id, trigger)` in `services/api/app/knowledge/sources/jobs.py` resolving the workspace through `kb_sources_workspace_for`, with job id `kb_sync:{source_id}`; register it in `services/api/app/knowledge/install.py` `jobs` (depends on T042)
- [X] T044 [US2] Source service in `services/api/app/knowledge/sources/service.py`: `create` (connection must be healthy, unique root per knowledge base, `shared_drive` forces subfolders, enqueue the `first` sync, activity `source_added`), `list`, `get` with `not_imported` (depends on T043)
- [X] T045 [US2] Routers: sources list, create, get in `services/api/app/knowledge/sources/router.py` (mounted with the knowledge feature); drive browse `shared-drives` and `folders` in `services/api/app/connectors/router.py` (map `TokenRevoked` to 409 `connection_revoked`, `GoogleTemporary` to 502 `google_unavailable`; declare 409, 502 and 503 in `responses=`) (depends on T040, T044; T033, T035 pass)
- [X] T046 [US2] Knowledge base counts in `services/api/app/knowledge/service.py` (`Counts`): add `source_count`; `archived_count` stays 0 until US3
- [X] T047 [P] [US2] Web API in `apps/web/src/api/knowledge.ts`: `useSources(kbId)` (polls every 3 s while any source is `pending` or `syncing`), `useSource`, `createSource`, `useDriveFolders(connectionId, parent, driveId)`, `useSharedDrives`; `KbDocument` gains `managed`, `source`
- [X] T048 [US2] `AddDriveSourceDialog` in `apps/web/src/routes/knowledge/sources/AddDriveSourceDialog.tsx`: pick a healthy connection (or link to Connections), browse My Drive and shared drives (breadcrumbs, folders only, paging), choose a folder or a whole shared drive, subfolders switch, Create; errors through `problemMessage` (depends on T047)
- [X] T049 [US2] Sources panel in `apps/web/src/routes/knowledge/KnowledgeBasePage.tsx` with `SourceCard` (`apps/web/src/routes/knowledge/sources/SourceCard.tsx`: root name, account, state badge, last sync, next sync, document count, "Not imported (n)" list with reasons); "Add Google Drive source" button next to Upload; document rows show a Drive badge, path and "Open in Drive" link, and hide Replace and Delete for managed documents (depends on T048)
- [X] T050 [P] [US2] Source state labels (`pending` "Waiting", `syncing`, `healthy`, `needs_attention` with reason text) and skip reason help in `apps/web/src/routes/knowledge/kbStatus.tsx`
- [X] T051 [P] [US2] Web tests `apps/web/src/routes/knowledge/sources/AddDriveSourceDialog.test.tsx` and `SourceCard.test.tsx`; extend `apps/web/src/routes/knowledge/KnowledgeBasePage` tests for managed rows

**Checkpoint**: quickstart A2 passes; the MVP (US1 + US2) is demoable.

---

## Phase 5: User Story 3, stay in step with Drive (Priority: P1)

**Goal**: scheduled and manual syncs; only real content changes are processed; renames update
names; removed files are archived and restorable for 30 days; the old version serves until the new
one is ready.

**Independent test**: quickstart A3 and A5 step 2.

### Tests first

- [X] T052 [P] [US3] Unit tests in `services/api/tests/unit/test_content_gates.py`: same md5 or version and size means no download; same bytes means metadata only; a Google Doc with different export bytes but the same normalised text means no new version; different text means a new version
- [X] T053 [P] [US3] Extend `services/api/tests/unit/test_sync_diff.py`: renames and moves inside the tree are `renames` (no processing); edits are `updates`; files missing, trashed or moved out are `removals`; a `kept` file missing is not a removal; a file that reappears with the archived document's content restores it instead of importing a copy; a file moved from source A to source B of the same knowledge base keeps one document, relinked to B and serving search, whether A or B syncs first (no processing, counted as `renamed`, no `duplicate` entry)
- [X] T054 [P] [US3] Integration tests in `services/api/tests/integration/test_source_changes.py`: the edit, rename, delete, add scenario gives 1 updated, 1 renamed, 1 archived, 1 added, 7 unchanged; the edited document's old version answers search until the new one is ready; a corrupt new version fails, the old one keeps serving, the failed row is removed and the run lists `processing_failed`; restore returns the document to search with no processing and the next sync marks it `kept`; restore of a non-archived document returns 409 `not_archived`; the Archive action on a kept document archives it and on any other document returns 409 `not_kept`; archived documents are excluded from counts and `attachable`; the purge deletes documents archived over 30 days ago with their chunks and object
- [X] T055 [P] [US3] Integration tests in `services/api/tests/integration/test_sync_schedule.py`: `sync_due` enqueues only due, idle sources; Sync now while running returns 409 `sync_running` with the run; a stale `running_run_id` older than 30 minutes is replaced; PATCH `interval_minutes` reschedules `next_sync_at` from the last run; values outside 5 to 1,440 return 422; removing a source with `documents=keep` turns documents into uploads and with `documents=archive` archives them; `source_removed` activity is written; after a successful run `next_sync_at` is at most 15 minutes ahead at the default interval and every changed file's ingestion is queued in that same run (SC-001); deleting a knowledge base removes its sources, files and runs and keeps the connection
- [X] T056 [P] [US3] Extend `services/api/tests/integration/test_sync_charges.py`: a no-change sync of 200 files downloads nothing, charges nothing and finishes in under 2 minutes on the fake client (SC-002); a metadata-only change charges nothing

### Implementation

- [X] T057 [US3] Diff rules for updates, renames, removals, `kept` and restore-by-hash in `services/api/app/knowledge/sources/diff.py`; in `sync.py`, an add whose `intake` returns `duplicate` of a document that is archived or linked to a `removed` source file in the same knowledge base relinks that document to this source file (`kb_documents.source_id`, `kb_source_files.doc_id`) and restores it, instead of skipping (research R7) (depends on T053)
- [X] T058 [US3] Content gates in `services/api/app/knowledge/sources/sync.py`: metadata gate, byte SHA-256 gate, and for Google Docs `text_sha256` from `knowledge.extract` on the DOCX export; store `md5`, `drive_version`, `sha256`, `text_sha256` on `kb_source_files` (depends on T052, T057)
- [X] T059 [US3] Updates through 005 Replace in `services/api/app/knowledge/sources/sync.py`: `intake(..., replace_doc_id=current)` sets `pending_doc_id`; renames update `display_name`, `name` and `path` only (depends on T058)
- [X] T060 [US3] Ingestion hook in `services/api/app/knowledge/jobs.py`: in the transaction that marks a document ready and deletes the replaced one, move `kb_source_files.pending_doc_id` to `doc_id`; when a pending version fails permanently, clear `pending_doc_id`, set the file `failed / processing_failed` and delete the failed row and its object (depends on T059)
- [X] T061 [US3] Archive and restore in `services/api/app/knowledge/service.py`: `archive(doc_ids)` (status `archived`, `archived_at`, keep chunks and object), `restore(doc_id)` (status `ready`, quota check, source file `kept` when its file is missing); `Counts` ignore `archived` and add `archived_count`; `GET .../documents?status=archived`; `POST .../documents/{doc_id}/restore` and `POST .../documents/{doc_id}/archive` (kept documents only, else 409 `not_kept`) in `services/api/app/knowledge/router.py` (depends on T039)
- [X] T062 [US3] Removals in `services/api/app/knowledge/sources/sync.py` call `archive` (the guard is added in US4) (depends on T057, T061)
- [X] T063 [US3] Crons in `services/api/app/knowledge/install.py`: `sync_due` every minute (`second={10}`, `unique=True`) calling `kb_sources_due(now, 100)` and enqueuing `sync_source(..., "scheduled")`; `purge_archived` daily at 04:45 through `kb_documents_archived_before(now - 30 days)` and the existing document delete path (depends on T043, T061)
- [X] T064 [US3] Source endpoints in `services/api/app/knowledge/sources/router.py` and `service.py`: `POST .../sync` (202 with the queued run, 409 `sync_running` with the active run), `PATCH` (subfolders, interval), `DELETE ?documents=keep|archive` (409 while syncing; `keep` clears `source_id`; activity `source_removed`) (depends on T061; T054, T055 pass)
- [X] T065 [P] [US3] Web API in `apps/web/src/api/knowledge.ts`: `syncSource`, `updateSource`, `deleteSource`, `restoreDocument`, `archiveDocument`, documents `status=archived`
- [X] T066 [US3] Web: "Sync now" and schedule select (5 min, 15 min, 1 h, 6 h, 24 h) and subfolders switch on `SourceCard`; `RemoveSourceDialog` in `apps/web/src/routes/knowledge/sources/RemoveSourceDialog.tsx` (keep or archive); "Archived" tab on the documents panel in `KnowledgeBasePage.tsx` with days left and Restore; an "Archive" row action and a "File missing in Drive" badge on kept documents; `archived` document status in `kbStatus.tsx` (depends on T065)
- [X] T067 [P] [US3] Web tests for Sync now (busy state on 409), schedule change, remove keep or archive, archived tab restore in `apps/web/src/routes/knowledge/sources/SourceCard.test.tsx` and `RemoveSourceDialog.test.tsx`

**Checkpoint**: quickstart A3 passes; T056 money test passes.

---

## Phase 6: User Story 4, never lose knowledge to a bad sync (Priority: P1)

**Goal**: the 20% guard holds mass archiving for confirmation; lost access, revoked tokens and
Google outages change nothing.

**Independent test**: quickstart A4.

### Tests first

- [X] T068 [P] [US4] Unit tests in `services/api/tests/unit/test_mass_archive_guard.py`: allowance `max(2, floor(0.20 * active))` for active 0, 1, 8, 10, 11, 100, 101; at or under the allowance archives all; over it holds all; confirm archives only held documents still missing; cancel clears
- [X] T069 [P] [US4] Unit tests in `services/api/tests/unit/test_drive_errors.py`: each Google response in research R6 (token `invalid_grant`, 401 after refresh, root 404, root 403 `insufficientFilePermissions`, 429, 403 `rateLimitExceeded` and `userRateLimitExceeded`, 500, 503, network error, one file 403 during download) maps to the right error class and run effect
- [X] T070 [P] [US4] Integration tests in `services/api/tests/integration/test_sync_faults.py` (SC-003): revoked token, unshared folder, emptied folder (100% removal held), 50% removed (held), outage (run failed `google_unavailable`, retried next schedule), listing failing on page 3 of 5; in every case zero documents are deleted or archived without confirmation, searches still return the synced copy, and the connection or source shows the right state
- [X] T071 [P] [US4] Integration tests in `services/api/tests/integration/test_held_archive.py`: 25 of 100 removed holds all with the message "This sync would archive 25 of 100 documents" and run status `held`; cancel keeps them and the next sync holds again; confirm archives 25; 2 of 8 removed archives without asking; confirm with nothing held returns 409 `nothing_held`; confirm and cancel write activity
- [X] T072 [P] [US4] Integration test in `services/api/tests/integration/test_sync_credit.py`: with balance zero, scheduled syncs pause with `needs_attention / no_credit` and retry after 60 minutes, Sync now and source create return 402, searches keep working
- [X] T073 [P] [US4] Integration test for `source_too_large` in `services/api/tests/integration/test_sync_faults.py`: a tree over 5,000 items fails the run before applying anything

### Implementation

- [X] T074 [US4] Pure guard in `services/api/app/knowledge/sources/guard.py`: `allowance(active)`, `decide(removals, active) -> Archive(ids) | Hold(ids, would_archive, of)` (depends on T068)
- [X] T075 [US4] Error classification and all-or-nothing listing in `services/api/app/knowledge/sources/sync.py`: check the root first; complete `list_tree` before planning; on `TokenRevoked` mark the connection and its sources; on `RootUnavailable` set `needs_attention / access_lost`; on `GoogleTemporary` after retries fail the run; on `SourceTooLarge` fail with `source_too_large`; per-file `FileUnavailable` continues (depends on T069, T062)
- [X] T076 [US4] Wire the guard into removals in `services/api/app/knowledge/sources/sync.py`: `Hold` stores `held_archive`, sets `needs_attention / mass_archive` with the message, records the run as `held` with `held_back`, leaves `next_sync_at` set so other changes keep syncing (depends on T074, T075)
- [X] T077 [US4] Held-archive confirm and cancel in `services/api/app/knowledge/sources/service.py` and `POST .../held-archive/{decision}` in `router.py`, with activity (depends on T076; T071 passes)
- [X] T078 [US4] Credit pre-flight in `services/api/app/knowledge/sources/jobs.py` and `service.py`: scheduled runs check `billing.get_balance(...) > 0` and pause with `no_credit` (next check in 60 minutes); manual sync and source create return 402 `insufficient_credit` (depends on T043; T072 passes)
- [X] T079 [US4] Reconnect resumes sources in `services/api/app/connectors/service.py`: on a successful reconnect, sources with `access_lost` caused by the token go back to `pending` and get a `reconnect` run queued (depends on T025, T075)
- [X] T080 [US4] `HeldArchiveBanner` in `apps/web/src/routes/knowledge/sources/HeldArchiveBanner.tsx` (message, confirm with `ConfirmDialog` tone danger, cancel) and the access-lost state on `SourceCard` with a Reconnect link to `CONNECTIONS_PATH`; no-credit state links to Billing (depends on T066)
- [X] T081 [P] [US4] Web tests `apps/web/src/routes/knowledge/sources/HeldArchiveBanner.test.tsx` and access-lost, no-credit states in `SourceCard.test.tsx`

**Checkpoint**: quickstart A4 passes; all SC-003 fault tests pass.

---

## Phase 7: User Story 5, see what each sync did (Priority: P2)

**Goal**: run history with trigger, counts and per-file errors, kept 90 days; connection and
source activity visible.

**Independent test**: quickstart A5.

### Tests first

- [X] T082 [P] [US5] Contract tests for `GET .../runs` and `GET .../runs/{run_id}` in `services/api/tests/contract/test_connectors_contract.py`
- [X] T083 [P] [US5] Integration tests in `services/api/tests/integration/test_sync_runs.py`: runs list newest first with trigger `first`, `manual`, `scheduled`, `reconnect`; detail shows per-file errors capped at 500 with `errors_truncated`; runs older than 90 days are purged; `GET /connections/{id}` shows the last 50 activity entries

### Implementation

- [X] T084 [US5] Runs endpoints in `services/api/app/knowledge/sources/router.py` and `service.py` (paged list, detail) (depends on T082)
- [X] T085 [US5] Cron `purge_sync_runs` daily at 04:50 through `kb_sync_runs_before(now - 90 days)` in `services/api/app/knowledge/install.py` (depends on T063)
- [X] T086 [US5] Activity on `GET /connections/{id}` (`ConnectionDetail.activity`, last 50) in `services/api/app/connectors/service.py` (depends on T014; T083 passes)
- [X] T087 [P] [US5] Web API `useSyncRuns(kbId, sourceId, page)` and `useSyncRun` in `apps/web/src/api/knowledge.ts`
- [X] T088 [US5] `SourceHistoryDrawer` in `apps/web/src/routes/knowledge/sources/SourceHistoryDrawer.tsx`: table of runs (started, duration, trigger, status, the eight counts), run detail with per-file errors and reasons; opened from `SourceCard`; activity list on `ConnectionCard` detail (depends on T087)
- [X] T089 [P] [US5] Web test `apps/web/src/routes/knowledge/sources/SourceHistoryDrawer.test.tsx`

**Checkpoint**: quickstart A5 passes.

---

## Phase 8: Polish and cross-cutting

- [X] T090 [P] Playwright flow in `apps/web/tests/e2e/knowledge-drive.spec.ts` (mock project): connect Google, add a folder source to a knowledge base, see synced documents with Drive badges, Sync now, restore an archived document
- [X] T091 [P] Simulations check in `services/api/tests/integration/test_source_isolation.py`: a text simulation (008) of the clinic agent retrieves synced passages exactly as a live call does (FR-019)
- [X] T092 [P] `ruff`, `mypy` (strict on the new money-adjacent sync code) and `pnpm lint`, `pnpm typecheck` clean
- [ ] T093 Run the full API suite (`make test`), `make contracts-check`, `pnpm gen:api:check`, `pnpm test`, `pnpm e2e`; run quickstart part A in fake mode and record results in `specs/022-knowledge-connectors/quickstart-results.md`, including the time from Sync now to the edited text being searchable (SC-001: under 5 minutes)
- [ ] T094 Real Google check: complete the Google Cloud setup from `docs/OPERATIONS.md`, run quickstart part B with a real folder, add the results to `quickstart-results.md`
- [X] T095 Raise the MR: summary, scope note (Drive sync plus Connections; MCP, summary cards and other connection kinds deferred; Sheets access requested and unused until the Sheets tool), screenshots of the Connections page, Sources panel and sync history, and the test list


## Phase 9: PR #1 review follow-ups

- [X] T096 New versions take over their file row before the old version is deleted; versions not taken keep the served markers; processing failures show on the file and are retried (`knowledge/jobs.py`, `sources/sync.py`); tests in `tests/integration/test_sync_versions.py`
- [X] T097 Claim heartbeat, owner-only release, 25-minute job timeout and cancelled runs finished (`sources/sync.py`, `core/feature.py`, `worker.py`)
- [X] T098 Per-file isolation of temporary Google errors; Drive ids validated; Drive responses mapped without `raise_for_status()` (`sources/sync.py`, `sources/http_drive.py`)
- [X] T099 Archived documents keep their real status (`knowledge.unarchive`, ingest never overwrites `archived`)
- [X] T100 Revoke at Google only when no other connection uses the account (`google_account_connections`)
- [X] T101 Web: specific messages for connector codes, refresh after a sync, no Replace for synced documents, every archived page, archived error state
- [X] T102 Invariants I1 to I6 in `data-model.md`, checked over random multi-sync sequences in `tests/integration/test_sync_invariants.py`
- [X] T103 Beta allowlist `CONNECTORS_WORKSPACES`, kill switch `CONNECTORS_SYNC_PAUSED` / Redis `connectors:sync_paused`, `metric=kb_sync_run` log line, spec sections How it works, Operations, Rollout and compliance, Later, and the runbook in `docs/OPERATIONS.md`
- [ ] T104 Measure first-sync time for 200 files and the SC-001 edit-to-searchable time against real Google on the hosted stack; record in `quickstart-results.md`
- [ ] T105 Decide data retention after access is lost (spec "Rollout and compliance") and implement it

## Traceability

Each research decision and the tests that prove it.

| Decision | Tests |
|---|---|
| R1 Full listing and diff, gated by Drive metadata | `test_sync_diff.py` (all), `test_edit_rename_delete_add`, `test_outage_and_partial_listing_apply_nothing`, `test_sync_invariants.py` |
| R2 Content check: markers, then bytes, then text | `test_content_gates.py` (all), `test_unchanged_and_metadata_only_syncs_process_nothing`, `test_unchanged_200_file_source_charges_nothing_and_is_quick` |
| R3 Google Docs exported as DOCX | `test_files_download_and_export`, `test_errors_are_classified` (export limit), `test_clinic_folder_imports_supported_files_and_lists_the_rest` |
| R4 OAuth with PKCE, completed by the web app | `test_oauth_state.py` (all), `test_connections_flow.py` (connect, decline, scopes, mismatch, other workspace), `ConnectionCallback.test.tsx` |
| R5 Refresh token in `secrets`, access token per run; revoke only when unshared | `test_tokens_never_reach_logs`, `test_remove_refused_while_in_use_then_revokes`, `test_a_google_account_shared_with_another_workspace_is_not_revoked`, `test_full_flow_touches_only_drive_and_oauth_hosts` |
| R6 Errors decide what a sync may do | `test_errors_are_classified`, `test_network_errors_become_temporary_after_retries`, `test_unmapped_statuses_are_temporary_not_http_errors`, `test_sync_faults.py` (all), `test_one_failing_file_does_not_fail_the_run`, `test_several_temporary_failures_in_a_row_end_the_run` |
| R7 Synced files reuse the upload pipeline | `test_first_sync_charges_once_per_document`, `test_identical_content_is_imported_once`, `test_failed_new_version_keeps_the_old_one`, `test_repeated_edits_keep_one_document_and_a_delete_archives_it`, `test_a_failed_new_version_is_retried_while_the_old_one_serves` |
| R8 Archive is a document status | `test_documents_accept_archived_status_and_source`, `test_restore_keeps_and_archive_action`, `test_purge_deletes_documents_archived_over_30_days_ago`, `test_archived_documents_keep_their_real_status` |
| R9 Mass-archive guard | `test_mass_archive_guard.py` (all), `test_emptied_folder_and_half_removed_are_held`, `test_held_archive.py` (all) |
| R10 Scheduling and one sync at a time | `test_due_sources_are_claimed_once`, `test_sync_now_while_running_and_stale_runs`, `test_a_run_taken_over_as_stale_never_touches_the_source`, `test_a_cancelled_sync_is_recorded_and_releases_the_source`, `test_the_sync_job_gets_its_own_timeout`, `test_the_kill_switch_pauses_scheduled_syncs` |
| R11 Drive client behind a port | `test_fake_drive.py` (all), `test_http_drive.py` (all) |
| R12 Folder picker in Callwright | `test_ids_that_could_change_a_drive_query_never_reach_google`, `test_folder_ids_are_validated_and_synced_files_are_flagged_on_upload`, `KnowledgeSources.test.tsx` "adds a Drive folder through the folder browser", `knowledge-drive.spec.ts` |
| R13 Limits | `test_full_knowledge_base_imports_up_to_the_limit`, `test_too_large_folder_fails_before_applying`, `test_interval_changes_and_limits`, `test_errors_are_capped` |
| R14 Activity record | `test_activity_is_append_only`, `test_connect_creates_a_healthy_connection`, `test_remove_refused_while_in_use_then_revokes` |
| R15 Managed documents | `test_synced_documents_cannot_be_replaced_or_deleted_by_upload`, `test_folder_ids_are_validated_and_synced_files_are_flagged_on_upload`, `KnowledgeSources.test.tsx` "never offers to replace a document synced from Drive" |
| R16 Google verification and Testing mode | Process, not code: `docs/OPERATIONS.md` section 15 and spec "Rollout and compliance"; live check in `quickstart-results.md` |
| R17a Sheets access requested, unused | `test_drive_access_is_required_sheets_is_optional`, `test_full_flow_touches_only_drive_and_oauth_hosts` (no Sheets host) |
| R17 Settings | `test_not_configured_returns_503`, `test_unconfigured_server_matches_the_contract`, `test_production_refuses_the_fake_drive_and_reads_the_drive_switches`, `test_the_beta_allowlist_gates_new_connections_and_sources` |
| R18 Latency and simulations | `test_each_agent_searches_only_its_own_synced_knowledge` (calls make zero Drive requests), `test_simulations_search_the_synced_copy_like_calls` |

---

## Dependencies

- Phase 1, then Phase 2 (T007 migration, then models T008 and T009, then registration T015;
  Drive port T010, then fake T011 and live client T012, then the factory T013).
- US1 needs Phase 2.
- US2 needs US1 (a connection and `access_token`) and Phase 2.
- US3 needs US2 (sources and the sync engine).
- US4 needs US3 (removals exist to guard; the error classification wraps the full sync).
- US5 needs US2 for runs; T086 activity can land any time after US1.
- Polish after all stories.

Story order: Phase 2 > US1 > US2 > US3 > US4 > US5.

## Parallel examples

- Phase 2: T005 and T006 together; then T008, T009, T010, T014 together; then T011 and T012.
- US1: T020, T021, T022 together; T023, T027, T028, T031 together while T024 to T026 are built.
- US2: T033 to T037 together; T040, T047, T050 alongside T038 to T046.
- US3: T052 to T056 together; T065 alongside T057 to T064.
- US4: T068 to T073 together; T080 after T076.

## Implementation strategy

1. **MVP (Phase 2 + US1 + US2)**: connect Google and import a folder. Demoable on its own: a
   knowledge base filled from Drive, searchable only by its own agents.
2. **US3**: keeping in step. Commit after its checkpoint with the money tests passing.
3. **US4**: the safety guards. Do not enable scheduled syncs for real users before this lands.
4. **US5**: history.
5. Commit after each checkpoint (one commit or small series per story) so the MR reviews story by
   story. Real Google is needed only for T094.
