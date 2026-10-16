# Billing (`/billing`) and the app shell

Live walkthrough, 2026-10-16. Screens: `screens/billing-*`, `screens/shell-*`, `screens/misc-*`.

## Billing page

- Eyebrow "BILLING", title "Your credit, in real time.", subtitle "Track your balance, top up instantly, and review every transaction."
- **ACCOUNT BALANCE** card: "$5.000" (3 decimals), "USD", "Updated live". GET `/billing/balance` returns `{user_id, balance}` (key is `balance`, not `credits_balance`; `/auth/me` carries `credits_balance`).
- **ADD FUNDS** card:

| Control | Type | Behaviour |
|---|---|---|
| Custom amount (USD) | number, placeholder "5", helper "Minimum $5" | Add stays disabled while empty. Values 4, 0, 5.5 and 10001 all enable Add; no maximum, decimals allowed. |
| Add | button | Amount below 5: nothing happens (no request, no message). Valid amount: POST `/billing/create-checkout-session` `{amount_usd}` (blocked; "Network Error" snackbar). |
| $25, $100, $500, $1000 | preset chips | One click immediately starts checkout with that amount (same POST); the chip does not fill the custom field and there is no confirm step. |

- **FEATURE USAGE**: a static range label "2026-09-16 → 2026-10-16" (last 30 days, not clickable, no date picker) and "No usage charges yet in this window." GET `/usage/me` returns `{window:{from,to}, rows:[], total_raw_cost_usd, total_billable_cost_usd}` (note the extra `total_raw_cost_usd`, i.e. raw cost vs billed cost with markup).
- **Transaction history** table: DATE, TYPE, AMOUNT, BALANCE AFTER, CALL ID, DESCRIPTION. Empty "No transactions yet". Rows per page: 10, 20 (default), 50. No type or date filters. GET `/billing/transactions?page=1&page_size=20` returns `{transactions[], total, page, page_size, total_pages}`.

## App shell

**Top bar (right side)**: balance chip (wallet icon + "$5.000", not clickable, no tooltip), account email text, avatar square with the first initial ("B", not clickable), and a logout icon button (no tooltip, no confirm per bundle; not clicked).

**Sidebar**: collapsed by default (icons only) with a "»" button (aria-label "Expand sidebar"). Collapsed icons show tooltips with the item label. Expanded order with section headers:
- Dashboard (`/dashboard`)
- Agent Builder (`/agents`)
- Call History (`/calls`)
- QUALITY: Datasets (`/datasets`), Simulations (`/simulations`)
- FEEDBACK LOOP: Review (`/review`), Calibration (`/calibration`), Issues (`/issues`)
- Phone Numbers (`/phone-numbers`)
- Knowledge Base (`/knowledge-base`)
- Billing (`/billing`)

Bottom of the sidebar: a "BV" initials badge (workspace/user, not clickable). There is no settings link, no user menu, no "Voice · Hold space" button and no balance in the sidebar.

**Global behaviour**:
- Snackbars bottom-left for errors ("Network Error").
- Error dialog pattern "Couldn't <action> / N ISSUES NEED ATTENTION / numbered list / OK" (agent create, flow save).
- Unsaved-changes guard on the flow builder (SPA navigation): "Unsaved changes / You have unsaved changes that will be lost. Leave without saving?" with "Stay on page" / "Leave anyway". The single-prompt create form has no guard.

## Other routes

| Route | Result |
|---|---|
| `/settings` | renders "Not Found" inside the shell (the settings page from the bundle is gone) |
| `/experiments` | redirects to `/simulations` |
| `/analytics-chat` | redirects to `/dashboard` |
| unknown path | redirects to `/dashboard` |
| `/calls/:id/compare?sim=` (bad ids) | "Simulation not found. Go back" |
| `/issues/:id` (bad id) | "Issue not found." |
| `/simulations/:id` (bad id) | "Simulation not found." |
| `/datasets/:id` (bad id) | "Failed to load dataset: Request failed with status code 404" |

API hygiene note: GET `/simulator/experiments/doesnotexist` returns HTTP 503 with a raw Postgres error ("invalid input syntax for type uuid") in the body. Callwright should validate ids and return clean 404s.
