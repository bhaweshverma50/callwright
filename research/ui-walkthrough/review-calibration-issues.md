# Feedback loop: Review, Calibration, Issues

Live walkthrough, 2026-10-16. No calls or evaluations exist, so only empty states, filters and the Detect request could be exercised. Screens: `screens/review-*`, `screens/calibration-*`, `screens/issues-*`.

## Review queue (`/review`)

- Eyebrow "REVIEW QUEUE", title "Label the ones that matter", copy "Label a few calls so the Calibration page can learn which automated checks you can trust. Click a card → thumbs up/down inside the call modal → it drops from the queue."
- Strategy tabs with live counts (from GET `/review/queue/summary[?agent_id=]`). Default tab: **Mixed verdicts**.

| Tab | strategy param | Description shown |
|---|---|---|
| Random | `random` | "A random sample of calls you haven't labeled yet. Builds a baseline across your normal traffic." |
| Flagged | `failed` | "Unlabeled calls where at least one check flagged a failure. Confirm or refute the auto-verdict." |
| Mixed verdicts | `disagreement` | "Unlabeled calls where your checks split, some passed, some failed on the same call. Each label here teaches calibration the most." |

- Counter line "0 calls to label".
- Agent filter autocomplete ("All agents"); selecting an agent refetches the summary and queue (`GET /review/queue?strategy=disagreement&agent_id=…&limit=50`).
- **Refresh** button refetches the queue.
- Empty state: "Nothing to review. / Either every recent call in this category is already annotated, or the eval worker hasn't scored any yet."

## Calibration (`/calibration`)

- Eyebrow "CALIBRATION", title "Which checks agree with you?", copy "Agreement between automated evaluators and your annotations. High = trustworthy; low = needs tuning. Off-diagonal cells show how each evaluator misses: over-eager (flags clean calls) vs. missed problems."
- Agent filter autocomplete ("All agents", agent names); selection refetches GET `/calibration/evaluators?agent_id=` and `/calibration/summary?agent_id=`.
- Summary tiles: ANNOTATIONS 0, WITH EVALS 0, MIN SAMPLE 5 "for trustworthy %" (so `min_sample_for_signal` = 5).
- Empty state: "No calibration data yet. / Label calls with thumbs up/down in the Quality modal: once a call has both a human label and at least one evaluator score, it shows up here." Button **Open Review queue**.

## Issues (`/issues`)

- Eyebrow "ISSUES", copy "Recurring failure patterns the system has clustered from your evaluator results. Each issue ships with an LLM-drafted prompt edit you can validate then apply."
- Filter row:

| Control | Options | Default | Effect |
|---|---|---|---|
| Agent | All agents, agent names | All agents | refetches GET `/issues?agent_id=&status=&limit=20` |
| Status | all, open, validating, validated, applied, dismissed (lower-case labels) | all | refetches `/issues?status=open&limit=20` |
| Window | Last 7 days, Last 14 days, Last 30 days, Last 90 days (shown as "Last 14d") | Last 14 days | no request; only used by Detect |
| Source | Real calls only, Real calls + sims (shown as "Real calls" / "Real + sims") | Real calls only | no list request observed; changes the button to "Detect (incl. sims)" |
| Detect / Detect (incl. sims) | button | disabled until an agent is chosen | POST `/issues/detect` `{agent_id, days, include_simulations}` (blocked; "Network Error" snackbar) |

- Empty states: no agent: "Pick an agent and run "Detect issues" to surface recurring failure patterns." With agent: "No issues for this agent. Try running "Detect issues" to scan recent failures."
- `/issues/:id` with an unknown id: "Issue not found."
- Issue detail (fix kinds, Draft & auto-validate, Apply, Dismiss) is not reachable without detected issues.
