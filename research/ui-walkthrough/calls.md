# Call History (`/calls`)

Live walkthrough, 2026-10-16. The account has zero calls, so row-level UI (recording player, transcript dialog, cost popover, Quality modal, row-selection actions such as Run simulation / Add to dataset, the compare page) could not be exercised. Screens: `screens/calls-*`.

## Page

- Eyebrow "CALL HISTORY", title "Every call, on the record.", subtitle "Recordings, transcripts, sentiment, latency - filter and replay any conversation."
- Toolbar: **Sort by** select, **Filters** button (shows a count badge when filters are active).
- Table header "RECENT CALLS (N)" with a select-all checkbox column and 19 columns, in order: CALL ID, DATE, AGENT ID, AGENT NAME, FROM NUMBER, TO NUMBER, TYPE, CHANNEL, DISCONNECT REASON, DURATION, STATUS, COST, AVG LATENCY, RECORDING, TRANSCRIPT, SUMMARY, SENTIMENT, ANALYSIS, QUALITY.
- No column-visibility menu, no density toggle, no export button.
- Empty state: "No calls found".
- Footer pagination: "Rows per page:" select (10, 20 default, 50, 100), "0–0 of 0", previous/next page buttons.

## Sort by

| Option | Query |
|---|---|
| Date (newest first) (default) | `sort_by=start_timestamp&sort_order=desc` |
| Date (oldest first) | `sort_by=start_timestamp&sort_order=asc` |
| Duration (longest first) | `sort_by=duration&sort_order=desc` |
| Duration (shortest first) | `sort_by=duration&sort_order=asc` |

Endpoint: GET `/calls/user/{user_id}/paginated?page=1&page_size=20&sort_by=&sort_order=` plus filter params. Every filter change refetches immediately (no Apply button).

## Filters dialog

Modal titled "Filters", buttons "Clear all filters" and "Close". Escape closes the whole dialog.

| Field | Control | Options | Query param |
|---|---|---|---|
| Status | multi-select | Registered, Ongoing, Ended, Not Connected | `call_status=ended,ongoing` (comma joined) |
| Type | multi-select | Web Call, Inbound, Outbound | `call_type` |
| Channel | multi-select | WebRTC, SIP, WhatsApp | `channel` |
| Disconnection Reason | multi-select | User Hangup, Agent Hangup, Call Transfer, Voicemail Reached, Inactivity, Max Duration Reached, Dial Failed, Connection Failed, Recording Failed, Concurrency Limit Reached, Insufficient Balance, Agent Error, System Error | `disconnection_reason` |
| Sentiment | multi-select | Positive, Neutral, Negative | `user_sentiment` |
| Your label | select | Any, Good, Bad, Needs review, Unannotated | `annotation_label=bad` |
| Agent | autocomplete, placeholder "Any agent" | agent names | `agent_id` |
| Search Call ID | text, placeholder "Enter call ID..." | | `call_id` (debounced) |
| Start Date / End Date | native date inputs | | `start_date=2026-09-30T18:30:00.000Z` (local midnight converted to UTC ISO) |
| From Number / To Number | text, placeholders "Enter from number..." / "Enter to number..." | | `from_number=+1555` (the `+` is NOT URL-encoded, so the server likely receives a space) |

Active filter chips appear above the table: "Active Filters: Status: ended, Status: ongoing, Agent: Test Flow Agent, Call ID: abc, From: +1555, Start: 2026-10-01" with "Clear All". The "Your label" filter is applied and counted in the badge (7) but gets no chip.

## Not reachable (no data)

Row checkbox selection, bulk actions, recording player, transcript dialog, cost breakdown popover, Quality modal (annotations, add to dataset, simulations), `/calls/:id/compare`. Their behaviour is documented from the bundle in the functional spec, sections 7 and 8.
