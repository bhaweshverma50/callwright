# Datasets and Simulations

Live walkthrough, 2026-10-16. No calls, datasets or simulations exist on the account, so only list pages, dialogs and empty states could be exercised. Screens: `screens/datasets-*`, `screens/simulations-*`.

## Datasets (`/datasets`)

- Eyebrow "DATASETS", title "Curated collections.", subtitle "Bundle interesting calls into datasets for regression checks and bulk evaluation."
- Button **New dataset**.
- Table columns: NAME, AGENT, ITEMS, UPDATED (plus an actions column). Empty: "No datasets yet. Create one to bundle calls for regression testing."
- GET `/datasets`.

**New dataset** dialog:

| Field | Control | Validation |
|---|---|---|
| Name | text | "Name required" inline error when Create is clicked empty (Create is never disabled) |
| Description (optional) | multiline | |
| Cancel / Create | buttons | |

- No agent picker in the dialog (the API supports `agent_id`, the UI does not send it).
- Blocked: POST `/datasets` `{name, description}`. Server errors are shown inline under Name ("Network Error") plus a snackbar.

Detail route `/datasets/:id`: an unknown id shows "Failed to load dataset: Request failed with status code 404" (raw axios message).

Adding calls to a dataset only happens from the call Quality modal ("Add to dataset"), which needs calls.

## Simulations (`/simulations`)

- Eyebrow "SIMULATIONS", copy "Replay historical calls through your agent (or a variant) and compare evaluator verdicts side by side."
- Tabs with counts: **Batch (0)** (default) and **Individual (0)**.
- Agent filter: autocomplete, placeholder "All agents", options "All agents" + agent names, with Clear and Open buttons. Filtering is client side (no request).
- GETs: `/simulator/experiments?limit=`, `/simulator/runs?limit=`.
- Empty states:
  - Batch: "No batch simulations yet. Run one from Call History → select several calls → "Run simulation"."
  - Individual: "No individual simulations yet. Replay one from a call detail page."
- There is no "New simulation" or "Run" button on this page; simulations start only from Call History selection or the call detail page.
- Detail route `/simulations/:id` with an unknown id: "Simulation not found."
