# Research: Google Drive knowledge sync (022)

Decisions for the narrowed 022 scope: a Google connection, Drive folder sources on knowledge
bases, scheduled and manual sync, archive and restore, the mass-archive guard and run history.

## Current state

- Knowledge (005, `services/api/app/knowledge/`): `knowledge_bases`, `kb_documents`, `kb_chunks`
  (migration `s005_0001`). Documents are uploaded through `POST /knowledge-bases/{kb_id}/documents`,
  checked by `service.create_document` (size 20 MiB, sniffed type `pdf | docx`, SHA-256,
  `duplicate_matches`, quotas `MAX_DOCS_PER_KB = 200` and `MAX_WORKSPACE_BYTES = 1 GiB`), stored at
  `ws/{ws}/kb/{kb}/{doc}/{sha}.{ext}` and ingested by the arq job `ingest_document`.
- Replace: a new row with `replaces_doc_id`; the old row keeps serving because search
  (`_SEARCH_SQL`) reads only `status = 'ready'`, and is deleted in the transaction that marks the
  new one ready. A failed replacement leaves the old one serving.
- `UNIQUE (kb_id, sha256)` blocks identical content twice in one knowledge base, including a
  replacement identical to the document it replaces.
- Ingestion is charged in `ingest` through `llms.charges.charge_tokens(feature_key="knowledge_ingestion")`
  with idempotency key `kb_ingest:{doc}:{sha}`. There is no credit pre-flight.
- Agents reference knowledge bases in `agents.draft_config.kb_ids`; the published snapshot pins
  them; search takes `kb_ids` from the call's agent version and `knowledge/router.py:277` refuses
  any other. This is the per-agent isolation FR-020 keeps.
- Secrets: `core/secrets.py` envelope AES-GCM (`SECRETS_MASTER_KEY`), table `secrets`,
  `put_secret / get_secret / delete_secret`, `mask_secret`.
- Jobs: modules declare `Feature(jobs=..., crons=...)` in `install.py`; crons use `arq.cron`.
  Workspace-less sweeps call a `SECURITY DEFINER` lookup and open one transaction per workspace
  (`callbacks_due`, `kb_documents_workspace_for`).
- No OAuth or Google Drive code, and no general audit log, exist today.

## R1. Sync by full listing and diff, gated by Drive metadata

- **Decision**: Each sync lists the whole source (the folder and, when included, every subfolder,
  or the shared drive) with `files.list`, then diffs the listing against the source's file table.
  A file is downloaded only when its Drive metadata changed: `md5Checksum` for binary files,
  `version` for Google Docs. Everything is listed before anything is applied; a failure part way
  through the listing applies nothing.
- **Rationale**: Drive's change feed is per user or per shared drive, not per folder. Using it for
  a folder means tracking every folder in the tree and every parent change, and still needs a full
  listing to recover from a lost page token. A full listing of the largest allowed source
  (5,000 items) is 5 to 10 requests plus one per subfolder, well inside Drive's quota and SC-002's
  2 minutes, and it detects moves, deletions and lost access in one pass. Applying only after a
  complete listing is what makes the archive rules safe (FR-014, FR-015).
- **Alternatives**: `changes.list` with a stored page token: fewer requests on huge drives, much
  more state and edge cases (Principle VI). Push notifications (`changes.watch`): need a public
  webhook and channel renewal; the 15-minute schedule does not need them.

## R2. Content check: Drive metadata, then bytes, then text

- **Decision**: Three gates before a file is processed again:
  1. Drive metadata unchanged (same `md5Checksum` or `version`, same size): no download. A changed
     name or folder updates `display_name` and the stored path only (FR-011).
  2. Downloaded bytes have the same SHA-256 as the current document: metadata update only.
  3. For Google Docs, the export is not byte-stable, so the extracted text is hashed
     (`text_sha256`, SHA-256 of the normalised text from 005's `extract()`); the same text means
     no new version.
  Only a real content change creates a new document version, which is the only thing that embeds
  and charges.
- **Rationale**: FR-011 and FR-024 (no charge for unchanged files) and SC-002. Extraction is local
  and free; embedding is the paid step.
- **Alternatives**: Bytes only: every Google Doc touch would be charged again. `modifiedTime`
  only: changes when comments or sharing change.

## R3. Google Docs are exported as DOCX

- **Decision**: Google Docs are exported with `files.export` as
  `application/vnd.openxmlformats-officedocument.wordprocessingml.document` and enter the pipeline
  as `file_type = 'docx'`. PDF and DOCX are downloaded with `alt=media`. Everything else is skipped
  by MIME type before any download: Sheets, Slides, Forms, images, shortcuts, folders (walked, not
  imported). Drive's export limit is 10 MB; larger Docs are skipped with `export_too_large`.
  Sizes over 20 MiB are skipped from metadata (`too_large`) without downloading.
- **Rationale**: DOCX keeps headings and tables, which 005's heading-aware chunker uses. No change
  to the `file_type` CHECK constraint.
- **Alternatives**: `text/plain` export: loses headings. PDF export: page numbers but worse text.

## R4. OAuth: authorization code with PKCE, completed by the web app

- **Decision**:
  - `POST /v1/connections/google/start` (owner only) creates a random `state`, a PKCE verifier and
    stores `{workspace_id, user_id, verifier, connection_id?}` in Redis for 10 minutes. It returns
    Google's authorization URL with `scope = openid email https://www.googleapis.com/auth/drive.readonly
    https://www.googleapis.com/auth/spreadsheets`, `include_granted_scopes=true`,
    `access_type=offline`, `prompt=consent`, `code_challenge_method=S256` and `redirect_uri = GOOGLE_OAUTH_REDIRECT_URI` (the web app's
    `/settings/connections/callback`, registered on the Google OAuth client).
  - Google redirects the browser to the web app. The callback page posts `{code, state}` to
    `POST /v1/connections/google/complete` with the normal bearer token. The API checks the state
    belongs to the same workspace and user, exchanges the code at Google's token endpoint, reads the
    account from the ID token (`sub`, `email`) and reads the granted scopes from the token response.
    `drive.readonly` is required (`oauth_scope_missing` otherwise). `spreadsheets` is optional:
    Google's consent screen lets users untick individual scopes, so its absence is stored and shown
    as "Sheets access not granted" with Reconnect, never treated as a failure.
  - The same Google account (`sub`) already connected in the workspace reconnects that connection
    instead of creating a second one.
  - Reconnect (`connection_id` in the state) with a different `sub` is refused with
    `oauth_account_mismatch`, showing the connection's masked email; nothing changes.
- **Rationale**: The SPA authenticates with bearer tokens, not cookies, so an API-side redirect
  callback could not tell which user and workspace it serves without another session mechanism.
  Completing from the web app reuses the existing auth. PKCE and the single-use state stop code
  injection and cross-workspace replay.
- **Alternatives**: API callback with a signed state carrying the workspace: works, but the API
  then serves an HTML redirect page and must trust the state alone for identity. Google Identity
  Services popup (token model): no refresh token, so scheduled syncs could not run.

## R5. Tokens: refresh token in `secrets`, access token per run

- **Decision**: The refresh token is stored with `put_secret` under the name
  `conn:{connection_id}:refresh` (AAD binds it to the workspace and name). Access tokens are never
  stored: each sync, test or folder browse exchanges the refresh token for an access token (valid
  about an hour) and keeps it in memory for that operation. Removing a connection revokes the
  refresh token at Google (best effort) and deletes the secret.
- **Rationale**: Principle V and FR-004. One token request per sync is negligible.
- **Alternatives**: Caching access tokens in Redis: a second encrypted store for no measurable
  gain at a 15-minute cadence.

## R6. Errors decide what a sync may do

- **Decision**: Every Drive error is classified before anything is applied:

  | Error | Meaning | Effect |
  |---|---|---|
  | Token refresh `invalid_grant`, or 401 after a fresh token | Access revoked or expired | Connection `revoked`; every source using it `needs_attention / access_lost`; run `failed` |
  | 404 or 403 `insufficientFilePermissions` on the source root | Folder deleted, unshared or moved out of reach | Source `needs_attention / access_lost`; run `failed` |
  | 429, 403 `rateLimitExceeded` / `userRateLimitExceeded`, 5xx, network | Temporary | Retry 3 times inside the run (1, 4, 16 s with jitter), then run `failed` with the reason; next scheduled sync retries |
  | 403 or 404 on one file during download | That file only | File `failed` in the run; the rest of the sync continues |

  A failed run never archives, updates or deletes documents (FR-015, FR-016).
- **Rationale**: Losing access must look like "nothing changed", never like "every file was
  deleted". Classifying at the root before diffing is what guarantees SC-003.

## R7. Synced files reuse the upload pipeline

- **Decision**: Refactor `service.create_document` into an intake function shared by the upload
  route and the sync job: size and type checks, SHA-256, quotas, storage `put`, `kb_documents` row.
  The sync calls it with `source_id` set, skips the upload-only warnings (`warn_other_kb`,
  `warn_same_name`) and maps the outcomes:
  - New file: a new document, linked from the source file (`doc_id`).
  - Changed file: a new document with `replaces_doc_id = current doc`, linked as `pending_doc_id`.
    `ingest` already deletes the old document when the new one is ready; a hook in that same
    transaction moves `pending_doc_id` to `doc_id`. If the new version fails, the old one keeps
    serving (FR-012), the source file records the failure, and the failed row is deleted so it
    does not count against the 200-document limit.
  - Same content as another document in the knowledge base (`blocked_same_kb`): skipped with
    `duplicate`, recording which document it duplicates.
  - Quota exceeded: skipped with `kb_full` (200 documents) or `workspace_storage_full` (1 GiB),
    and the source goes to `needs_attention / kb_full`.
  - Same content as a document in the knowledge base that is archived, or linked to a source
    file now marked `removed` (a move between two sources of the same knowledge base, in either
    sync order): the document is relinked to this source file and restored to `ready` if archived.
    No processing, no charge, counted as `renamed`. Only a match with a live document of another
    file is a `duplicate`.
- **Rationale**: One extraction, chunking, embedding and charging path. Charges, retries and the
  per-workspace concurrency limit (2 ingestions) apply unchanged.

## R8. Archive is a document status

- **Decision**: Add `archived` to the `kb_documents.status` CHECK constraint, plus `archived_at`.
  Archiving keeps the chunks and the stored object; restoring sets the status back to `ready` with
  no processing. A daily cron deletes documents archived more than 30 days ago through the existing
  delete path (row, chunks by cascade, object). `GET .../documents?status=archived` lists them.
- **Rationale**: Search already filters `status = 'ready'`, so archived documents leave search with
  no change to `_SEARCH_SQL` or the worker: zero effect on the call path (Principle II). Keeping
  the chunks makes restore instant and free.
- **Alternatives**: An `archived_at` column with the status unchanged: needs a search SQL change on
  the hot path. Moving rows to an archive table: two copies of the document model.

## R9. Mass-archive guard

- **Decision**: After a complete listing, removals are the source's linked documents whose files
  are missing, trashed or moved outside the source. Allowed per sync:
  `max(2, floor(0.20 * active documents of the source))`. If removals exceed it, the sync archives
  none of them, applies everything else, stores the held document ids on the source
  (`held_archive`), sets `needs_attention / mass_archive`, and records the run as `held`. Confirm
  archives exactly the held set (documents that reappeared meanwhile are skipped). Cancel clears it;
  the next sync checks again. A restored document whose file is still missing is marked `kept` and
  is never archived by sync again.
- **Rationale**: FR-014 and SC-003, including the "up to 2 always allowed" small-source rule.

## R10. Scheduling and one sync at a time

- **Decision**:
  - Cron `sync_due` every minute (`second={10}`) calls the `SECURITY DEFINER` function
    `kb_sources_due(p_now, p_limit 100)` (sources with `next_sync_at <= now` and no live run),
    moves each one's `next_sync_at` forward by its interval at once (so a source still waiting in
    the queue is not enqueued again a minute later) and enqueues `sync_source(source_id)`. Each
    enqueue has its own job id: arq keeps finished job ids for an hour, so a fixed id would block
    the next sync. The row lock below is what guarantees one sync at a time.
  - "Sync now" and the first sync claim the source in the request (a `running` run row), and the
    job continues that run, so the response can return the run.
  - `sync_source` takes the source row `FOR UPDATE SKIP LOCKED`, sets `running_run_id`, and clears
    it at the end. A `running_run_id` older than 30 minutes is treated as stale and replaced.
  - "Sync now" enqueues the same job id; if a run is active it returns 409 `sync_running` with that
    run (FR-010, acceptance 3.7).
  - `next_sync_at = finished_at + interval_minutes`, interval 5 to 1,440, default 15.
  - Scheduled syncs check `billing.get_balance(...) > 0` first. With no credit the source shows
    `needs_attention / no_credit` and the next check is in 60 minutes. Search keeps working.
- **Rationale**: Reuses the arq cron and job-id patterns already in the codebase. No new queue.

## R11. Drive client behind a small port

- **Decision**: `knowledge/sources/drive.py` defines a `DriveClient` protocol (`refresh`,
  `account`, `get_root`, `list_tree`, `list_folders`, `list_shared_drives`, `download`, `export`)
  with an `HttpDriveClient` built on the shared `httpx.AsyncClient`, and a `FakeDriveClient` with an
  in-memory tree for tests, the mock web mode and the quickstart. Fixed Google hosts only
  (`oauth2.googleapis.com`, `www.googleapis.com`); no customer URLs, so the SSRF guard does not
  apply. Shared-drive calls pass `supportsAllDrives`, `includeItemsFromAllDrives` and
  `corpora=drive`.
- **Rationale**: Principle I (outside systems behind an adapter) and VII (offline tests).
- **Alternatives**: `google-api-python-client` and `google-auth`: synchronous, large dependency
  tree, and we use six endpoints.

## R12. Folder picker in Callwright, not Google Picker

- **Decision**: The add-source dialog browses Drive through the API:
  `GET /connections/{id}/drive/shared-drives` and `GET /connections/{id}/drive/folders?parent=`.
  Only folders are listed. The chosen root's id, name and kind are stored on the source.
- **Rationale**: Google Picker is built for the narrower `drive.file` scope, needs a browser API
  key, and picking a folder through it does not grant access to the files inside. With
  `drive.readonly` a simple folder browser is enough and testable with the fake client.

## R13. Limits

- **Decision**: 005's limits apply to synced documents (200 per knowledge base, 1 GiB per
  workspace). A listing that passes 5,000 items fails the run with `source_too_large` before
  anything is applied. Per-file errors kept per run: up to 500 (the rest are counted). Runs are
  kept 90 days (daily purge).
- **Rationale**: Bounded work per sync and per run record; the spec's assumption section matches.

## R14. Activity record

- **Decision**: A small append-only table `connector_activity` (who, what, when, subject):
  `connection_added`, `connection_reconnected`, `connection_removed`, `source_added`,
  `source_removed`, `held_archive_confirmed`, `held_archive_cancelled`. Grants allow SELECT and
  INSERT only. It is shown on the connection and source detail views.
- **Rationale**: FR-025 needs a record that survives deleting the thing it describes; no general
  audit log exists yet. When 018 (audit history) or 023 (team activity) lands, this table can be
  read into it.
- **Alternatives**: Actor columns on rows only: lost on delete. Waiting for 018: blocks FR-025.

## R15. Managed documents

- **Decision**: A document with `source_id` set is managed by its source:
  - Upload Replace and Delete return 409 `managed_by_source` ("This document comes from Google
    Drive. Change it in Drive, or remove the source.").
  - Reprocess of a failed synced document stays allowed.
  - Removing a source asks `documents=keep|archive`: `keep` clears `source_id` (they become
    ordinary uploads), `archive` archives them under the 30-day rule.
  - Deleting a knowledge base cascades to its sources, files and runs; the connection stays.
- **Rationale**: FR-017, FR-018 and the edge cases in the spec.

## R16. Google app verification and testing mode

- **Decision**: Document in the quickstart and deploy notes that `drive.readonly` is a restricted
  scope and `spreadsheets` a sensitive one. While the Google Cloud project is in "Testing", only listed test users can connect, and
  Google expires their refresh tokens after 7 days. The connection then shows `revoked` and the
  owner reconnects. Verification is a release task, not part of this feature.
- **Rationale**: Prevents the weekly "revoked" connection in demos from looking like a bug.

## R17a. Sheets access requested now, used later

- **Decision**: The connection asks for `https://www.googleapis.com/auth/spreadsheets` from the
  first version, stores whether it was granted (`sheets_access`), and nothing in 022 calls the
  Sheets API. The Google Sheets tool (next spec) uses it for live lookups and safe bookings.
- **Rationale**: Adding a scope later forces every workspace to reconnect. Live data such as slot
  availability and inventory belongs in tools, not in the knowledge base (stale after up to 15
  minutes, imprecise for exact lookups, and read-only), so the follow-up tool is the planned path
  for businesses without an API.
- **Alternatives**: `spreadsheets.readonly`: covers lookups but not bookings, so a second
  reconnect would follow. Asking at tool-creation time (incremental authorization): simplest for
  privacy, but the user explicitly chose to request it now.
- **Cost**: The consent screen shows "See, edit, create and delete all your Google Sheets
  spreadsheets", which some owners will hesitate over; the Connections page explains it is not used
  until the Sheets tool is turned on.

## R17. Settings

New `Settings` fields (empty disables the feature: the Connections page shows "Google Drive is not
configured on this server" and the routes return 503 `connector_unavailable`):

| Env var | Type | Purpose |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | str | OAuth client (Google Cloud project with the Drive and Sheets APIs enabled) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | SecretStr (may be `enc:v1:`) | OAuth client secret |
| `GOOGLE_OAUTH_REDIRECT_URI` | str | The web app's `/settings/connections/callback` URL; must match the OAuth client and an origin in `CORS_ORIGINS` |
| `CONNECTORS_DRIVE_MODE` | `live` \| `fake` | Fake client for tests, mock mode and local demos |

There is no web app URL setting today (only `CORS_ORIGINS`), so the redirect URI is explicit.

## R18. Latency and simulations

- **Decision**: No change to the voice worker, `kb_search` or `_SEARCH_SQL`. Simulations and test
  calls search the synced copy like any document (FR-019).
- **Rationale**: Principle II: the hot path is untouched, so no benchmark run is required; the
  existing knowledge search latency test (005 SC-002) still covers it.
