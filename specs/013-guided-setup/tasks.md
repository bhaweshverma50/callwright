# Tasks: guided setup tour (013)

- [x] T001 Contract `contracts/preferences.yaml`, added to `contracts/features.txt`; `make contracts`, `pnpm gen:api`
- [x] T002 Migration `s013_0001`: `user_preferences`, RLS on user and workspace (after `s011_0001`)
- [x] T003 API module `app/preferences`: `GET/PATCH /v1/me/preferences` with defaults and an upsert
- [x] T004 API tests: contract, auth, validation, defaults, partial updates, RLS isolation
- [x] T005 Web: preferences hooks and mock handlers
- [x] T006 Web: tour state machine (pure reducer) and step definitions
- [x] T007 Web: tour provider (auto-offer, persistence, navigation, target waiting, real-action advance)
- [x] T008 Web: spotlight and popover (bottom sheet on phones, focus, Esc, arrows, live region), welcome card, resume chip, recap
- [x] T009 Web: "Guided setup" in the account menu; tour anchors on the template grid, publish control and number import
- [x] T010 Tests: Vitest (machine, persistence, skip, resume, restart, advance on the real action) and mock e2e (complete, skip)
