# Data model: Google Drive knowledge sync (022)

One migration, `s022_0001_drive_sync.py` (down revision: the current head, `s002_0005` at the
time of writing). Forward only. Every new table is a tenant table with the standard RLS block
(`ENABLE` and `FORCE ROW LEVEL SECURITY`, policy `{table}_tenant` on `app.workspace_id`, grants to
`callwright_app`), except where noted.

New ID prefixes: `conn_` (connection), `ksrc_` (knowledge source), `ksr_` (sync run). Declared in
the `connectors` and `knowledge` features' `id_prefixes` and added to research/architecture.md
section 4.

## Changed tables

### `kb_documents` (005)

| Change | Type | Rules |
|---|---|---|
| `status` CHECK | | adds `archived`: `uploaded, processing, ready, failed, archived` |
| `archived_at` | timestamptz null | set when archived, cleared on restore |
| `source_id` | text null FK `kb_sources(id)` ON DELETE SET NULL | set for synced documents; null means an ordinary upload |

Index: `(source_id)` where `source_id IS NOT NULL`; `(status, archived_at)` where
`status = 'archived'` for the purge.

State transitions added to 005's diagram:

```
ready --sync archive, or remove source with "archive"--> archived
archived --restore (within 30 days), or its content reappears in a source of the same KB--> ready
ready (kept, file missing) --Archive action--> archived
archived --purge (archived_at older than 30 days)--> (row, chunks and object removed)
```

`UNIQUE (kb_id, sha256)` stays. Archived documents still hold their hash, so a file that comes
back with the same content restores the archived document instead of importing a copy (R7, R9).

## New tables

### `connections`

| Column | Type | Rules |
|---|---|---|
| id | text PK | `conn_` |
| workspace_id | text NOT NULL FK workspaces | RLS |
| provider | text | CHECK `google` |
| kind | text | CHECK `oauth` |
| account_subject | text | Google account id (`sub`) |
| account_email | text | shown on the page |
| scopes | text[] | granted scopes; must include `drive.readonly` |
| sheets_access | boolean | true when `spreadsheets` was granted; unused in 022 (held for the Sheets tool) |
| secret_name | text | `conn:{id}:refresh` in `secrets` (001) |
| health | text | CHECK `healthy, failing, revoked`, default `healthy` |
| health_reason | text null | short reason, e.g. `invalid_grant`, `rate_limited` |
| last_success_at | timestamptz null | last successful Drive call |
| last_checked_at | timestamptz null | last Test or use |
| created_by | text | user id |
| created_at, updated_at | timestamptz | |

Unique `(workspace_id, provider, account_subject)`: reconnecting the same Google account updates
the row (R4). The refresh token never appears in this table.

### `kb_sources`

| Column | Type | Rules |
|---|---|---|
| id | text PK | `ksrc_` |
| workspace_id | text NOT NULL | RLS |
| kb_id | text NOT NULL FK knowledge_bases ON DELETE CASCADE | |
| connection_id | text NOT NULL FK connections ON DELETE RESTRICT | FR-006 |
| kind | text | CHECK `google_drive` |
| root_kind | text | CHECK `folder, shared_drive` |
| root_id | text | Drive folder id, or shared drive id |
| drive_id | text null | shared drive id when the folder is inside one |
| root_name | text | shown on the page, refreshed on each sync |
| include_subfolders | boolean | default true; always true for `shared_drive` |
| interval_minutes | int | 5 to 1,440, default 15 |
| state | text | CHECK `pending, syncing, healthy, needs_attention`, default `pending` |
| attention_reason | text null | CHECK `access_lost, mass_archive, kb_full, no_credit, source_too_large` |
| held_archive | jsonb null | `{doc_ids: [...], would_archive: n, of: m, run_id}` while a mass archive waits |
| last_success_at | timestamptz null | |
| next_sync_at | timestamptz null | null while paused for confirmation |
| running_run_id | text null | the active run |
| running_since | timestamptz null | the active run's last heartbeat (every minute); silent for 10 minutes is stale (R10) |
| created_by | text | |
| created_at, updated_at | timestamptz | |

Unique `(kb_id, root_id)`: the same folder cannot be added twice to one knowledge base. Index
`(next_sync_at)` where `running_run_id IS NULL`.

### `kb_source_files`

One row per Drive item the source has seen (imported, skipped or failed).

| Column | Type | Rules |
|---|---|---|
| id | text PK | bare ULID (child row, no public prefix) |
| workspace_id | text NOT NULL | RLS |
| source_id | text NOT NULL FK kb_sources ON DELETE CASCADE | |
| drive_file_id | text | |
| name | text | current Drive name |
| path | text | folder path from the root, e.g. `Policies/2026` |
| mime_type | text | |
| web_view_link | text null | link to the original (FR-017) |
| drive_version | text null | Google Docs `version` |
| md5 | text null | binary files' `md5Checksum` |
| size_bytes | bigint null | |
| sha256 | text null | bytes of the last processed version |
| text_sha256 | text null | normalised extracted text (Google Docs, R2) |
| doc_id | text null FK kb_documents ON DELETE SET NULL | the document serving search |
| pending_doc_id | text null | a new version being processed (R7); ingestion moves `doc_id` to it when it is ready, before the old version is deleted. `sha256`, `text_sha256` and the change markers describe the newest version taken in; a version that was not taken leaves them on the served one so the next sync tries again |
| state | text | CHECK `synced, skipped, failed, removed, kept` |
| reason | text null | CHECK `unsupported_type, too_large, export_too_large, shortcut, duplicate, kb_full, workspace_storage_full, download_failed, processing_failed` |
| duplicate_of_doc_id | text null | when `reason = duplicate` |
| message | text null | readable detail for skipped and failed files |
| last_seen_run_id | text null | |
| updated_at | timestamptz | |

Unique `(source_id, drive_file_id)`. Index `(doc_id)`, `(pending_doc_id)`.

### `kb_sync_runs`

| Column | Type | Rules |
|---|---|---|
| id | text PK | `ksr_` |
| workspace_id | text NOT NULL | RLS |
| source_id | text NOT NULL FK kb_sources ON DELETE CASCADE | |
| trigger | text | CHECK `first, scheduled, manual, reconnect` |
| status | text | CHECK `running, succeeded, held, failed` |
| failure_reason | text null | `access_lost, connection_revoked, google_unavailable, source_too_large, internal` |
| started_at | timestamptz | |
| finished_at | timestamptz null | |
| added, updated, unchanged, renamed, archived, held_back, skipped, failed | int | default 0 |
| errors | jsonb | up to 500 `{drive_file_id, name, reason, message}`; `errors_truncated` int counts the rest |
| errors_truncated | int | default 0 |

Index `(source_id, started_at DESC)`. Purged after 90 days by the daily cron.

### `connector_activity`

Append-only (grants SELECT and INSERT only to `callwright_app`).

| Column | Type | Rules |
|---|---|---|
| id | bigint identity PK | |
| workspace_id | text NOT NULL | RLS |
| actor_user_id | text null | null for system actions |
| action | text | CHECK `connection_added, connection_reconnected, connection_removed, source_added, source_removed, held_archive_confirmed, held_archive_cancelled` |
| subject_type | text | `connection` or `source` |
| subject_id | text | kept after the subject is deleted |
| detail | jsonb | e.g. `{account_email}`, `{kb_id, root_name, documents: "keep"}` |
| created_at | timestamptz | |

Index `(workspace_id, subject_id, created_at DESC)`.

## Security-definer functions

All `LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public`, `REVOKE ALL FROM PUBLIC`,
`GRANT EXECUTE TO callwright_app`. They return ids and workspace ids only.

| Function | Returns | Used by |
|---|---|---|
| `kb_sources_due(p_now timestamptz, p_limit int)` | `(id, workspace_id)` of sources with `next_sync_at <= p_now` and no live `running_run_id` | cron `sync_due` |
| `kb_sources_workspace_for(p_source_id text)` | `workspace_id` | job `sync_source` |
| `kb_documents_archived_before(p_before timestamptz, p_limit int)` | `(id, workspace_id)` | daily purge |
| `kb_sync_runs_before(p_before timestamptz, p_limit int)` | `(id, workspace_id)` | daily purge |

## Derived values (API, not stored)

- Knowledge base counts (005 `Counts`) ignore `archived` documents for `status` and `attachable`,
  and gain `archived_count` and `source_count`.
- Document `managed` = `source_id IS NOT NULL`; `source` = `{source_id, root_name, path,
  web_view_link}` joined from `kb_source_files` on `doc_id`.
- Connection `users` = sources referencing it, with their knowledge base names.
- Source `active_documents` = linked documents with status `ready`, `processing` or `uploaded`;
  the mass-archive allowance is `max(2, floor(0.20 * active_documents))` (R9).

## Validation rules from the spec

| Rule | Where |
|---|---|
| Only the owner manages connections (FR-007) | route dependency on connections routes |
| Connection in use cannot be removed (FR-006) | FK RESTRICT plus a 409 listing the sources |
| Interval 5 to 1,440 minutes (FR-010) | schema and CHECK |
| One sync per source at a time (FR-010) | `running_run_id`, `FOR UPDATE SKIP LOCKED`, arq job id |
| Archive at most `max(2, 20%)` per sync (FR-014) | sync service, test-first |
| Lost access changes nothing (FR-015) | error classification before diff (R6) |
| Synced documents are not editable by upload (FR-017) | 409 `managed_by_source` in document routes |
| Tokens never leave the secrets store (FR-004) | `secrets` table, no token field in any schema |
