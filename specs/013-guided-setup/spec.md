# Feature specification: guided setup tour (013)

Created: 2026-11-03. Status: implemented on branch `w9-tour`.

## Why
A new user lands on an empty dashboard with eleven product areas in the sidebar. The setup
checklist says what to do, not where to click. The user asked for "some guided setup tutorial
with option to skip or follow along till the end".

## User stories
1. **First run (P1).** A new user (no agents yet) sees a welcome card once after sign-in: set up
   a first agent in about three minutes, with Start tour and Skip for now.
2. **Follow along (P1).** Each step highlights the real control with a spotlight and a popover
   (title, one or two sentences, step counter, Back, Next, Skip tour). Steps that ask for an
   action advance when the user does it (opens the templates, creates the agent, opens the Voice
   tab, publishes, ends the test call) and offer "Do it for me" where the app can do it.
3. **Skip, pause, resume, restart (P1).** Skip tour ends it at any step. Esc pauses it; a small
   resume chip brings it back at the same step, also after a reload or on another device. The
   account menu's "Guided setup" entry restarts it from the first step at any time.
4. **Existing users (P2).** Anyone whose workspace already has an agent never gets the welcome
   card, but can start the tour from the account menu.

## Requirements
- FR-001: Progress is stored per user on the server: status `not_started`, `in_progress`,
  `skipped` or `completed`, the current step id and when it was saved
  (`GET/PATCH /v1/me/preferences`). A user reads and writes only their own row (RLS on user and
  workspace).
- FR-002: The tour drives navigation: each step names its route and the tour opens it. A step
  whose control does not appear within a few seconds still shows its text, centred, without a
  spotlight.
- FR-003: Steps: agents, template, prompt, voice, cost, test call, publish, channels, calls,
  quality, then a recap with links. The agent steps follow the agent the tour created, or the
  most recently updated agent.
- FR-004: Keyboard: focus moves into the popover on each step and Tab stays in it (the
  highlighted control stays usable with the pointer); Esc pauses; the arrow keys go back and
  forward. Screen readers hear each step through a polite live region.
- FR-005: Below 640 px the popover is a bottom sheet. Reduced motion turns off the spotlight
  glide and the halo. Light and dark themes use the design tokens.
- FR-006: While another dialog is open (the template preview, a leave confirmation) the tour
  stays out of the way and comes back when it closes.

## Out of scope
Per-feature tips outside the setup path, analytics on tour completion, tours for flow agents.
