# Quickstart: Google Drive knowledge sync (022)

Validates the feature end to end. Part A runs fully offline with the fake Drive client
(`CONNECTORS_DRIVE_MODE=fake`), which serves an in-memory folder tree you can change through the
dev routes. Part B repeats the main path against a real Google account.

## Setup

1. `make up`, `make migrate`, then `make api`, `make worker` and the web app (`pnpm dev` in
   `apps/web`). For part A also set `CONNECTORS_DRIVE_MODE=fake`, `ENABLE_DEV_ROUTES=true` and
   any non-empty `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` and
   `GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5180/settings/connections/callback`.
2. Sign in, create two agents, "Clinic front desk" and "Property enquiries", and two knowledge
   bases, "Clinic policies" and "Property listings". Attach "Clinic policies" to the clinic agent
   only and "Property listings" to the property agent only.
3. Seed the fake Drive: `POST /v1/dev/fake-drive/seed` with the `clinic` preset (folder
   "Clinic policies" with 10 supported files: 6 Google Docs, 2 PDF, 2 DOCX; plus a Google Sheet
   and a 30 MB PDF) and the `property` preset (folder "Listings", 5 files).

## A1. Connect Google (Story 1)

1. Settings > Connections > Connect Google Drive. In fake mode the consent step returns at once.
2. Expect one connection showing the fake account's email address, "Drive (read-only)",
   "Sheets" (with the note that it is not used yet) and "Healthy". Run Test: the check time updates.
3. `POST /v1/dev/fake-drive/consent {"decline": true}`, then connect again: no second connection,
   and the page says access was not granted.
4. `POST /v1/dev/fake-drive/consent {"scopes": ["drive"]}`: the connection works and shows "Sheets
   access not granted" with Reconnect. With `{"scopes": ["sheets"]}`: refused, Drive access is
   required.

## A2. First sync and per-agent isolation (Story 2, SC-005, SC-007)

1. Open "Clinic policies" > Add Google Drive source > pick the connection > "Clinic policies"
   folder, subfolders on. Expect the source to show "Syncing", then "Healthy".
2. Expect 10 documents, each with a Drive badge and a link to the original, and the source's
   "Not imported" list showing the Sheet (unsupported type) and the 30 MB PDF (over 20 MB).
3. Add the "Listings" folder to "Property listings".
4. Search preview in "Clinic policies" for a sentence from one Google Doc: it is found.
5. Text-test the clinic agent with that question: it answers from the Doc. Text-test the property
   agent with the same question: no clinic passage is retrieved (check the call's tool events).
6. Try Delete and Upload > Replace on a synced document: both refuse with "This document comes from
   Google Drive".

## A3. Stay in step (Story 3, SC-002)

1. With nothing changed, Sync now. The run shows 10 unchanged, 0 processed, and the workspace's
   credit balance did not move. It finishes in seconds.
2. Through `POST /v1/dev/fake-drive/change`: edit one Doc's text, rename one PDF, delete one DOCX,
   add one new Doc. Sync now.
3. Expect the run: 1 updated, 1 renamed, 1 archived, 1 added, 7 unchanged. Search finds the new
   text and the new Doc, the renamed PDF shows its new name, and the deleted DOCX is under
   "Archived" with Restore.
4. Edit the same Doc again but only change its sharing (`touch_metadata`): next run shows it
   unchanged (no new version, no charge).
5. Restore the archived DOCX: it is back in search at once. Sync now: it stays (marked kept).
6. Make one edit whose new version fails processing (`corrupt` flag): the run lists it failed and
   the previous version still answers searches.

## A4. Never lose knowledge (Story 4, SC-003)

1. Seed the `big` preset (100 files) into a third knowledge base and let it sync.
2. Remove 25 files from the fake folder and Sync now. Expect nothing archived, the source in
   "Needs attention: This sync would archive 25 of 100 documents", and the run status "held".
3. Cancel: the 25 documents stay. Sync now: held again. Confirm: 25 archived, restorable.
4. In a knowledge base with 8 synced documents, remove 2 files and Sync now: both archived without
   asking.
5. `POST /v1/dev/fake-drive/revoke`, then Sync now. Expect the connection "Revoked", every source
   "Needs attention: access lost", no document changed, and searches still answering.
6. Reconnect from the Connections page: the connection is healthy, sources resume on their next
   sync with no setup.
7. `POST /v1/dev/fake-drive/outage` (rate limit every call), Sync now: run failed with "Google
   unavailable", nothing archived; clear the outage and the next run succeeds.

## A5. History (Story 5)

1. Open the source's history: runs show trigger (first, manual, scheduled), the eight counts and
   per-file errors.
2. Set the interval to 5 minutes and wait: a scheduled run appears within 6 minutes.

## A6. Guards

1. Remove the connection while sources use it: refused, listing both sources.
2. Remove the "Property listings" source with "Keep documents": its documents become ordinary
   uploads (Delete and Replace work again). Remove another with "Archive documents": all archived.
3. Set the workspace balance to zero (dev billing route): scheduled syncs pause with "No credit",
   searches keep working; Sync now returns "Out of credit".

## B. Real Google account

1. In Google Cloud: enable the Google Drive API and Google Sheets API, configure the consent
   screen in Testing with your account as a test user, scopes `openid`, `email`,
   `.../auth/drive.readonly` and `.../auth/spreadsheets`, and create an OAuth client (Web
   application) with the redirect URI `http://localhost:5180/settings/connections/callback`.
2. Set the three `GOOGLE_OAUTH_*` values and `CONNECTORS_DRIVE_MODE=live`, restart the API and
   worker.
3. Connect your account, add a real folder with a few Docs and a PDF, and repeat A2 steps 1 to 5
   and A3 steps 2 and 3 by editing files in Drive.
4. Note: in Testing mode Google expires refresh tokens after 7 days, so the connection will show
   "Revoked" after a week; Reconnect fixes it (research R16).

## Checks

- `make test` (unit, contract and integration, including the sync fault tests).
- `make contracts-check` and `pnpm gen:api:check` after adding 022 to `contracts/features.txt`.
- `pnpm test` and `pnpm e2e` in `apps/web` (mock project covers the connect and add-source flow).
