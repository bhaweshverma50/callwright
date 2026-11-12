# Contributing

Live demo: https://callwright-one.vercel.app. Setup and deploy steps are in [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Pull requests

1. **Branch** from `main` as `<type>/<short-topic>`, e.g. `feat/drive-connectors`, `fix/sarvam-key-gate`.
2. **Title** follows [Conventional Commits](https://www.conventionalcommits.org): `type(scope): summary`, at most 72 characters. Types: `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `build`, `ci`, `chore`, `revert`. Add `!` after the type for a breaking API or contract change. The title becomes the squash commit on `main`.
3. **Description** uses the template. Summary, Changes, Testing, and Risk and rollout must have content (`None` is fine for rollout).
4. **Size**: one concern per PR, ideally under 800 changed lines excluding generated files (contracts, API clients, lockfiles). A spec that is bigger lands as a stack: contract and migration first, then the API, then the web.
5. **Draft** until CI is green and you have reviewed your own diff.

The `pr-rules` check enforces the title and description. The `ci` and `voice-worker` workflows must pass.

## Review

- **Who**: at least one approval from a code owner (`.github/CODEOWNERS`). Changes to money, auth, RLS, secrets or migrations get a second careful read by the owner even if small.
- **Turnaround**: first review within one working day; the author answers comments within one working day.
- **Comments** are prefixed so intent is clear:
  - `blocker:` must change before merge (bug, security, data loss, contract break).
  - `issue:` should change; the author may push back with a reason.
  - `suggestion:` optional improvement.
  - `nit:` style or wording; never blocks.
  - `question:` the reviewer needs to understand something before approving.
- **Resolving**: the author pushes a fix and replies with the commit; the reviewer resolves the thread. Do not resolve someone else's blocker yourself.
- **Re-review**: any push after approval that changes behaviour needs a fresh approval.

## Merging

- **Squash and merge** only. The branch is deleted on merge.
- Merge when: CI green, required approval in, every `blocker:` and `issue:` thread resolved, branch up to date with `main`.
- The author merges their own PR after approval, then deploys (or says in the PR who will).
- Migrations, new env vars or secrets: follow the Risk and rollout section of the PR, and set the secrets before the code that reads them is deployed.
