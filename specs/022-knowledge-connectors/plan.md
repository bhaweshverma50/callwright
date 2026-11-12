# Implementation Plan: Google Drive knowledge sync (022)

**Branch**: `knowledge-connectors` | **Date**: 2026-11-12 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/022-knowledge-connectors/spec.md` (scope narrowed
2026-11-12 to Google Drive sync and a minimal Connections page)

## Summary

Keep knowledge bases in step with Google Drive. A new `connectors` API module owns Google
connections (read-only Drive, plus Sheets access requested now and held for the Google Sheets tool
that follows): OAuth authorization code with PKCE, started by the API and completed by the web app's
callback page, with the refresh token in 001's encrypted `secrets` store and health from tests and
real use. The `knowledge` module gains Drive sources, a sync job and run history. Each sync lists
the whole source through a small `DriveClient` port, diffs it against `kb_source_files`, and only
then applies changes: new files go through 005's existing intake and ingestion (so chunking,
embedding, charging and the 2-per-workspace limit are unchanged); changed files become 005
replacements, so the old version serves until the new one is ready; Drive metadata, byte hashes and
extracted-text hashes skip unchanged files before anything is charged. Removed files are archived
through a new `archived` document status, which search already ignores, so the call path does not
change. The mass-archive guard (`max(2, 20%)`) and error classification before the diff (lost access
changes nothing) are written test-first. An arq cron enqueues due sources every minute with one job
id per source. Per-agent isolation is unchanged: agents still search only the knowledge bases
attached to their version (005).

## Technical Context

**Language/Version**: Python 3.12 (API and jobs worker); TypeScript 5 (web). No voice worker change.
**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, arq, httpx (shared
client), 005's `extract`, `chunking` and embeddings, 001's `core/secrets.py`. Web: TanStack Query,
React Router, existing `components`. No new dependency (no Google client libraries, research R11).
**Storage**: PostgreSQL 16 with RLS: new `connections`, `kb_sources`, `kb_source_files`,
`kb_sync_runs`, `connector_activity`; `kb_documents` gains `archived` status, `archived_at` and
`source_id`. Refresh tokens in `secrets`. Synced files in the existing object store under 005's key
layout. OAuth state in Redis (10 minutes).
**Testing**: pytest: unit tests for the diff, the content gates and the mass-archive allowance
(test-first); integration tests against `FakeDriveClient` for every acceptance scenario and the fault
set in SC-003; contract tests for `connectors.yaml` and the changed 005 document schemas; an
isolation test for SC-005; a no-charge test for SC-002. Web: unit tests for the Connections page,
callback page, add-source dialog, sources panel and archived documents; one Playwright mock flow
(connect, add source, see documents).
**Target Platform**: Cloud Run (API), the realtime VM (jobs worker and cron), Vercel (web).
**Project Type**: Web service + SPA.
**Performance Goals**: no-change sync of 200 files under 2 minutes with zero processing (SC-002);
a Drive edit searchable within 20 minutes at the default schedule and 5 minutes after Sync now
(SC-001); call-time search unchanged (005 SC-002: 95% under 300 ms).
**Constraints**: Calls never reach Drive (FR-019); a failed or partial listing applies nothing
(FR-015, FR-016); tokens never leave the secrets store (FR-004); forward-only migration; house
style (no em dashes).
**Scale/Scope**: up to 200 documents per knowledge base and 5,000 Drive items per source; 1 new
API module (`connectors`), 1 extended (`knowledge`, new `sources/` package); 2 new web routes
(`/settings/connections`, `/settings/connections/callback`) and a Sources panel and Archived view on
the knowledge base page.

## Constitution Check

*GATE: passed before Phase 0 and re-checked after Phase 1 design.*

| Gate | Principle | How this plan satisfies it | Status |
|---|---|---|---|
| Vendor behind adapter | I | Google Drive sits behind the `DriveClient` port (`knowledge/sources/drive.py`) with `HttpDriveClient` and `FakeDriveClient`, selected by `CONNECTORS_DRIVE_MODE`. Embeddings stay behind 005's `EmbeddingAdapter`. A later source (Notion, SharePoint) is another client plus a `kind` value. | Pass |
| Latency impact stated | II | Not on the turn path. `kb_search`, `_SEARCH_SQL` and the worker are unchanged; archived documents leave search because search already reads only `ready` (R8). No benchmark run needed; 005's search latency test still covers the path. | Pass |
| Metering impact stated | III | No new meter or price. Synced files are charged through 005's `knowledge_ingestion` path with its idempotency key `kb_ingest:{doc}:{sha}`, so a retried job never charges twice. Three content gates (R2) mean unchanged files are never charged (FR-024, SC-002 money test). Scheduled syncs pause at zero balance. | Pass |
| Measurability path | IV | Every sync writes a run with eight counts and per-file errors (FR-022); SC-001 to SC-007 each map to a quickstart step and an automated test. | Pass |
| Tenancy and privacy | V | RLS on all five new tables; workspace-less crons use narrow `SECURITY DEFINER` lookups returning ids only. Refresh tokens encrypted in `secrets` and never in any schema. OAuth state is single use and bound to workspace and user. Search isolation per agent unchanged and tested (SC-005). Synced copies follow 005's storage encryption and signed URLs. | Pass |
| Complexity justified | VI | No new service or queue; one module plus a package in `knowledge`. Deviations below. | Pass |
| Contract and money tests | VII | `connectors.yaml` contract tests written first; 005's `Document`, `DocumentStatus` and `KnowledgeBase` schema changes with their contract tests updated; money tests: unchanged files charge nothing, a retried sync charges once, scheduled syncs pause at zero balance. | Pass |

Post-design re-check: Pass. The design adds no service, keeps the call path untouched and keeps every
new read inside RLS.

## Project Structure

### Documentation (this feature)

```text
specs/022-knowledge-connectors/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/connectors.yaml
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
services/api/app/
├── core/config.py            # EXTEND: GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET,
│                             #   GOOGLE_OAUTH_REDIRECT_URI, CONNECTORS_DRIVE_MODE (R17)
├── connectors/               # NEW module (feature "connectors", prefix conn)
│   ├── install.py            # FEATURE: router, id_prefixes {conn}
│   ├── models.py             # Connection, ConnectorActivity
│   ├── schemas.py
│   ├── router.py             # /connections, google/start, google/complete, test, drive browse
│   ├── oauth.py              # state + PKCE in Redis, authorization URL, code exchange, ID token, revoke
│   ├── service.py            # create or reconnect, health updates, access_token(conn), remove
│   └── activity.py           # append connector_activity rows
├── knowledge/
│   ├── install.py            # EXTEND: jobs sync_source, sync_due, purge_archived; crons; id_prefixes {ksrc, ksr}
│   ├── models.py             # EXTEND: Document.archived_at, Document.source_id; KnowledgeSource,
│   │                         #   SourceFile, SyncRun
│   ├── service.py            # EXTEND: intake() shared by upload and sync (R7); counts ignore archived;
│   │                         #   archive / restore; 409 managed_by_source on replace and delete
│   ├── jobs.py               # EXTEND: ingest hook moves pending_doc_id to doc_id on ready, clears it on failure
│   ├── router.py             # EXTEND: ?status=archived, restore
│   └── sources/              # NEW package
│       ├── drive.py          # DriveClient port, HttpDriveClient, FakeDriveClient, error classes (R6, R11)
│       ├── diff.py           # pure: listing + known files -> plan (add, update, rename, remove, skip)
│       ├── guard.py          # pure: mass-archive allowance and decision (R9)
│       ├── sync.py           # run a sync: lock, refresh token, list, classify, diff, apply, record
│       ├── service.py        # source CRUD, held-archive confirm or cancel, remove keep or archive
│       ├── router.py         # /knowledge-bases/{kb_id}/sources...
│       └── schemas.py
├── dev/                      # EXTEND: /dev/fake-drive/seed, change, revoke, outage (dev routes only)
├── features.py               # EXTEND: register connectors
└── migrations/versions/s022_0001_drive_sync.py

services/api/tests/
├── unit/test_sync_diff.py  test_mass_archive_guard.py  test_content_gates.py  test_drive_errors.py
│        test_oauth_state.py
├── contract/test_connectors_contract.py   (+ test_knowledge_contract.py updated)
└── integration/test_connections_flow.py  test_source_first_sync.py  test_source_changes.py
                test_sync_faults.py  test_held_archive.py  test_archive_restore.py
                test_source_isolation.py  test_sync_charges.py  test_sync_schedule.py

contracts/features.txt          # EXTEND: 022-knowledge-connectors
specs/005-tools-knowledge/contracts/knowledge.yaml   # EXTEND: archived status, Document.source,
                                                     #   archived_at, managed; KB archived_count, source_count

apps/web/src/
├── api/connections.ts        # NEW: hooks for connections, start, complete, test, drive browse
├── api/knowledge.ts          # EXTEND: sources, runs, sync, held archive, restore, archived filter
├── lib/paths.ts              # EXTEND: CONNECTIONS_PATH, CONNECTIONS_CALLBACK_PATH
├── router.tsx                # EXTEND: two settings routes
├── routes/settings/
│   ├── SettingsPage.tsx      # EXTEND: link card to Connections
│   └── connections/          # NEW: ConnectionsPage, ConnectionCard, ConnectionCallback
├── routes/knowledge/
│   ├── KnowledgeBasePage.tsx # EXTEND: Sources panel, Drive badge and link on rows, Archived tab with
│   │                         #   Restore, managed rows hide Replace and Delete
│   ├── kbStatus.tsx          # EXTEND: archived document status, source states
│   └── sources/              # NEW: AddDriveSourceDialog (folder browser), SourceCard,
│                             #   SourceHistoryDrawer, HeldArchiveBanner, RemoveSourceDialog
└── mocks/connectors/         # NEW: handlers + store (connections, sources, runs, fake folders)

apps/web/tests/e2e/knowledge-drive.spec.ts            # NEW: mock project flow
research/architecture.md      # EXTEND: section 3 row for 022, section 4 prefixes conn_, ksrc_, ksr_
```

**Structure Decision**: One new API module, `connectors`, because connections are workspace-level
and will be shared by later sources and tools; Drive sources live in `knowledge/sources/` because
they only feed knowledge bases. research/architecture.md section 3 gains:
`| 022 knowledge-connectors | connectors, knowledge (sources) | /settings/connections, knowledge base Sources panel |`.
Cross-owner edits, listed again in tasks: 005 `knowledge/service.py` (intake refactor, archive,
managed documents), `knowledge/jobs.py` (pending version hook), `knowledge/router.py` and the 005
knowledge contract; 001 `core/config.py` and the Settings page; the dev routes module.

### Sync flow

1. Cron `sync_due` (every minute) gets due sources from `kb_sources_due` and enqueues
   `sync_source` with job id `kb_sync:{source_id}`; Sync now enqueues the same job.
2. `sync_source` locks the source, records a `running` run, checks credit (scheduled only), and gets
   an access token from `connectors.service.access_token` (a revoked token marks the connection and
   its sources and stops).
3. It checks the root, then lists the whole tree (all pages, all subfolders). Any error stops the
   run here: nothing is applied (R6).
4. `diff.plan()` compares the listing with `kb_source_files` and returns adds, updates (metadata
   changed), renames, removals and skips.
5. Updates are downloaded or exported; byte and text hashes drop the ones with no real change (R2).
6. Adds and real updates go through `knowledge.service.intake()` and are enqueued for 005's
   `ingest_document`; quota and duplicate outcomes become skips.
7. `guard.decide()` archives removals within `max(2, 20%)` or holds them all (R9).
8. The run is finished with its counts and errors; the source's state, `last_success_at` and
   `next_sync_at` are set. Ingestion finishing later moves each pending version into place.

## Complexity Tracking

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| New `connectors` module and `connections` table | FR-001 to FR-007: a workspace-level connection with health, reused by every source of the workspace and by later sources and tools | Storing tokens on each source repeats the sign-in per knowledge base and cannot show one health per Google account |
| `connector_activity` append-only table | FR-025 needs who-did-what records that survive deleting the connection or source; no audit log exists (018 not built) | Actor columns on rows are lost on delete |
| `DriveClient` port with a fake | Principle I and VII: offline tests of every fault in SC-003 and a local demo without Google | Calling Google directly makes the fault tests and the quickstart need a real account |
| `archived` document status | FR-013: archive and restore without processing, and no change to the call-time search | A separate archive table duplicates the document model; an `archived_at` flag needs a search SQL change on the hot path |
| Web-completed OAuth callback | The SPA authenticates with bearer tokens; the callback page posts code and state with the user's token, so the API knows the workspace and user without a cookie session | An API redirect callback needs either a cookie session or trusting the state alone for identity |
| New ID prefixes `conn_`, `ksrc_`, `ksr_` | Connections, sources and runs are addressable resources in URLs | Integer ids break the platform's prefixed-id convention and the id hygiene test |
