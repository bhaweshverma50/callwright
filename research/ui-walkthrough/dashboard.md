# Dashboard (`/dashboard`), analytics chat, voice copilot

Live walkthrough, 2026-10-16 (account with zero calls). Screens: `screens/dashboard-*`, `screens/voice-copilot-*`.

## Header and filter bar

- Eyebrow "01 · OVERVIEW", status "LIVE · UPDATED NOW", **Refresh** button (refetches GET `/dashboard/stats` only).
- Title "Your voice agents, in numbers." Subtitle "Every call, every sentiment, every disconnect - live across your entire fleet of agents."
- Filter bar (staged, needs Apply):

| Control | Type | Options / default | Behaviour |
|---|---|---|---|
| Period | segmented text buttons | All time (default), 7d, 30d, 90d, Custom | Changing it does not fetch; it enables **Apply filters** |
| Custom range | two native date inputs, appear when Custom is selected | default last 30 days (2026-09-16 to 2026-10-16) | |
| Agent | multi-select autocomplete, placeholder "Any agent" | agent names | |
| Apply filters | button | disabled until something changes | fetches GET `/dashboard/stats?start_date&end_date[&agent_ids]`, GET `/dashboard/quality?start_date&end_date` and the same with `&compare=true` |

- After Apply, an "ACTIVE" chip row shows the range ("2026-10-09 → 2026-10-16", removable ×) and a **Clear all** button.
- Presets are day-granular dates (`start_date=2026-10-09&end_date=2026-10-16` for 7d).

## Sections (empty-state copy)

1. KPI tiles: TOTAL CALLS (sub "Daily avg"), TOTAL DURATION ("Peak day"), TOTAL COST ("Per call" $0.000), AVG DURATION ("Per call").
2. "02 Call activity / Daily volume, duration, and average across the selected window": VOLUME "Calls per day" (Total, Range N days); TALK TIME "Total talk time" (Total, Sessions).
3. "03 Quality & outcomes / Why calls end, how long they last, and how they feel": DISCONNECTS "Why calls ended" (Top reason); AVG "Average call duration" (Overall avg); SENTIMENT "Conversation mood" (Analyzed); CHANNELS "Call channels" (Total). Empty charts show "No data".
4. "04 Channels & agents / Where calls come in, and who's handling them": LEADERBOARD "Most active agents" (Showing top N); DISTRIBUTION "Calls by agent · top 10" (Top agent share).
5. "05 Quality checks / How each evaluator scored across the selected window": "Agent health / Last 30 days vs prior 30 days" ("No headline evaluators have scored calls in this window yet."); QUALITY CHECKS "Per-evaluator pass rate" ("No evaluator runs in this window. Enable quality checks in Agent Builder, then come back.", "0 calls evaluated in window").

Response shapes seen:
- `/dashboard/stats`: `{overview:{total_calls, total_duration_seconds, total_cost, avg_duration_seconds, avg_cost}, disconnection_reasons:{13 keys}, sentiment:{positive, negative, neutral, unknown}, call_types:{web_calls, inbound_calls, outbound_calls}, daily_stats[], top_agents[], agent_distribution[]}` (KPIs are nested under `overview`, and there is an `avg_cost`).
- `/dashboard/quality?compare=true`: `{window:{from,to}, prior_window:{from,to}, total_calls_evaluated, per_evaluator[], per_evaluator_prior[]}`.

## "Ask about your data" panel

- Floating pill button "Ask about your data" (bottom centre, with a record-dot icon).
- Opens a right-side panel: eyebrow "ANALYTICS · CHAT", title "Ask about your data.", copy "Ask questions about your calls, costs, agents, and performance in plain English." "TRY ASKING" suggestion rows with →: "Total calls this month", "Cost breakdown by agent", "Busiest day last week", "Average call duration trend".
- Input textarea "Ask about your data…" + send icon (disabled when empty). Header icons: expand (OpenInFull) and close.
- Expanded mode shows a "New chat" button and a collapse icon.
- Sending: user bubble, then error text "Something went wrong. Please try again." when the request fails. Blocked: POST `/analytics/chat` `{messages:[{role, content}], timezone}`.
- `/analytics-chat` as a route now redirects to `/dashboard` (the standalone page is gone; only the panel remains).

## Voice copilot (hold Space)

- On every page load the app calls POST `/voice-commands/stream-token` (blocked here; it is a write by method only).
- Holding Space (focus outside inputs) immediately shows a toast at the top left: "Microphone access is blocked. Check your browser permissions." (the headless browser denies the mic). No other overlay appeared; releasing Space leaves the toast. With a mic, the bundle shows "Listening... release Space or click to stop".
- There is no visible "Voice · Hold space" button in the current sidebar; the feature is keyboard-only.
