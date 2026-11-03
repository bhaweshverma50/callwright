# Plan notes: scheduled callbacks (011)

## Design
- API module `services/api/app/callbacks` (models, schemas, service, router, jobs). Table
  `scheduled_callbacks`, migration `s011_0001` (after `s003_0004`), forward-only, RLS like 010's
  tables, partial unique index: one open callback per source call. Security definer
  `callbacks_due(now, limit)` lets the cron find due rows across workspaces.
- 010's `outbound/service.py` now takes a `Requester` (workspace, optional user, `requested_by`)
  instead of a principal, and exposes `check_policies` (policies at a given instant) and
  `place` (policies, admission, room). `POST /v1/outbound-calls` is unchanged.
- Calling hours: booking refuses rather than moving the time (the caller agreed to a time and
  only they can agree to another; 010 also refuses rather than queues, research R9). At dial
  time a block fails the callback with the reason and logs a policy decision.
- Recipient zone: the call's `timezone` variable when the number allows it, else the number's
  zones. Inbound calls now get the caller's number zone as `timezone` (it was UTC), so
  `{{current_time}}` and the agent's sense of "tomorrow at 5" are the caller's.
- Agent: the callback uses the call's own agent (it knows the conversation), from the number
  the call used, even when the number's outbound agent differs; the note travels as
  `callback_note` and the worker tells the agent on the callback why it is calling.
- Worker: built-in `schedule_callback` next to the built-in `end_call` for single-prompt agents
  (`worker/tools/schedule_callback.py`); the agent's instructions get the caller's current local
  date and time and a callback rule (`CALLBACK_INSTRUCTION`). Always present, refused on
  non-phone calls.
- Web: drawer card on the source call, Callbacks list with a status filter, MSW mocks.

## Constitution check
I: no vendor code. II: no hot-path change beyond one longer system prompt; the tool call is one
internal request (5 s timeout) only when the caller asks. III: callbacks are ordinary outbound
calls, priced and charged by 003; a refused callback is never charged. IV: tool calls are
recorded as `tool_call` events. V: RLS on the new table, service-token internal endpoint.
VI: no new service; one cron. VII: contract `contracts/callbacks.yaml`, drift tests, money paths
reuse 010's tests plus `tests/integration/test_callbacks.py`.

## Deploy
Migrate (`s011_0001`), API image, jobs worker (new cron `place_due_callbacks` every minute at
:20), voice worker and textsim image, web. No new settings or secrets.
