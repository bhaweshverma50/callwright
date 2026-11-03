# Tasks: scheduled callbacks (011)

- [x] T001 Contract `contracts/callbacks.yaml`, added to `contracts/features.txt`; `make contracts`, `pnpm gen:api`
- [x] T002 Migration `s011_0001`: `scheduled_callbacks`, RLS, `callbacks_due()`
- [x] T003 010 outbound service: `Requester`, `check_policies`, `place`
- [x] T004 Public endpoints: list (status, source call), get, create, cancel
- [x] T005 Internal `POST /v1/internal/calls/{call_id}/callbacks`: recipient, zone, time, policies, reschedule, refusals, simulation mock
- [x] T006 Cron `place_due_callbacks`: claim, busy wait, missed, policies and admission, stale placing retry
- [x] T007 Inbound calls carry the caller's zone as `timezone`
- [x] T008 Worker: built-in `schedule_callback` tool and executor, callback instructions with the local time, callback-call note
- [x] T009 Textsim: the tool answers mocked, never reaches the API
- [x] T010 Web: drawer card, Callbacks list, mocks, agent editor capability line
- [x] T011 Tests: `tests/integration/test_callbacks.py`, `tests/unit/test_callback_time.py`, worker `test_schedule_callback.py`, textsim no-egress
