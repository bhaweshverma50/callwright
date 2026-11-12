<!--
Title: Conventional Commits, e.g. `feat(knowledge): sync knowledge bases from Google Drive`.
Types: feat, fix, perf, refactor, docs, test, build, ci, chore, revert. Max 72 characters.
The pr-rules check fails when the title or the required sections below are missing.
-->

## Summary

<!-- What changes for the user or the operator, in two to five sentences. Link the spec (specs/NNN-*) or issue. -->

## Changes

<!-- The main pieces, grouped by area (API, worker, web, contracts, deploy). Call out anything outside the spec. -->

## Testing

<!-- Commands you ran and their results; what you checked by hand. Screenshots or a short clip for UI changes. -->

## Risk and rollout

<!-- Migrations, new env vars or secrets, deploy order, feature flags, rollback plan. Write "None" if there is nothing. -->

## Checklist

- [ ] One concern per PR; under ~800 changed lines excluding generated files, or the split is explained above
- [ ] Tests added or updated for new behaviour and fixed bugs
- [ ] `make lint typecheck test` and `pnpm typecheck lint test` pass locally
- [ ] Contracts and generated clients are current (`make contracts-check`, `pnpm gen:api:check`)
- [ ] Migrations are forward-only and the chain stays linear
- [ ] No secrets, tokens or personal data in code, logs or fixtures
- [ ] Docs updated (`docs/OPERATIONS.md`, README, spec) where behaviour or setup changed
