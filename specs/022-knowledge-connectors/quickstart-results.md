# Quickstart results: Google Drive knowledge sync (022)

Recorded 2026-11-12 on branch `knowledge-connectors`.

## Automated checks

| Check | Result |
|---|---|
| Full API suite (`pytest`, local Postgres and Redis) | 2,155 passed, 3 skipped (existing skips) |
| 022 API tests after the last changes (contract, sources, sync) | all passed |
| `make contracts-check` | up to date |
| `pnpm gen:api:check` | up to date |
| Web unit tests (Vitest, Node 22) | 73 files, 384 tests passed |
| Web lint (`eslint`, `prettier --check`) and `tsc -b` | clean |
| API lint (`ruff check`, `ruff format --check`) and `mypy` on the new modules | clean |
| Playwright mock flow `tests/e2e/knowledge-drive.spec.ts` | passed |

## Quickstart part A (fake Drive), by automated test

| Step | Covered by |
|---|---|
| A1 connect, test, decline, Drive required, Sheets optional | `test_connections_flow.py`, `ConnectionsPage.test.tsx`, `ConnectionCallback.test.tsx` |
| A2 first sync, skipped files, per-agent isolation, managed documents | `test_source_first_sync.py`, `test_source_isolation.py` |
| A3 edit, rename, delete, add; metadata-only change; failed new version; restore and kept | `test_source_changes.py`, `test_sync_charges.py` |
| A4 held archiving, small sources, revoked, unshared, outage, partial listing, reconnect | `test_sync_faults.py`, `test_held_archive.py` |
| A5 history and schedule | `test_sync_runs.py`, `test_sync_schedule.py` |
| A6 remove connection in use, remove source keep or archive, no credit | `test_connections_flow.py`, `test_sync_schedule.py`, `test_sync_credit.py` |

Measured in tests: a no-change sync of a 200-file source makes 3 Drive requests (token, root,
listing), processes nothing, charges nothing and finishes in well under 2 minutes (SC-002). After a
sync the next one is due within 15 minutes at the default interval (SC-001).

## Not yet done

- Quickstart part A by hand against a running local stack (`make api`, `make worker`, `pnpm dev`).
- Part B with a real Google account (needs the Google Cloud OAuth client, T094).
