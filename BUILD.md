# Build Plan and Conventions

Implementation follows the specs in `specs/` and `research/architecture.md` (v1.2). Work runs in
waves; agents inside a wave work in parallel on separate branches and directories, and the
integrator merges each wave into `main` before the next starts.

## Waves

| Wave | Scope | Branches |
|---|---|---|
| 1 | Repo scaffold, 001 backend; web scaffold, design system, shell and 001 pages; voice-worker scaffold and the worker side of 003 | `w1-api`, `w1-web`, `w1-worker` |
| 2 | 002 agent builder (API and web); 003 API side (sessions, calls write side, admission, events, post-call steps, webhooks) | `w2-agents`, `w2-runtime` |
| 3 | 004 flows, 005 tools and knowledge, 006 calls and analytics, 010 channels | `w3-*` |
| 4 | 007 quality and evals, then 008 testing and simulation | `w4-*` |
| 5 | 009 issues and auto-fix, end-to-end polish | `w5-*` |

## Ownership inside a wave

- Each agent owns only the directories its brief names. Root files (`docker-compose.yml`,
  `Makefile`, `.github/workflows/ci.yml`, root `README.md`) belong to the API agent in wave 1 and
  to the integrator afterwards.
- Never edit another spec's files without the brief saying so; record needed changes in your
  final report instead.

## Local environment

- `docker compose up -d` starts Postgres 16 with pgvector on host port **55432** and Redis on
  **56379** (host ports avoid clashing with locally installed services on 5432 and 6379).
- API on port 8100, web dev server on 5180, voice-worker health on 8190.
- `.env.example` lists every variable; real vendor keys are optional. Without keys, adapters run
  in fake mode so tests and the offline harness work.

## Database migrations (Alembic)

- One linear history. Revision ids are `s<spec>_<nnnn>` (for example `s001_0001`, `s002_0003`),
  file names `s<spec>_<nnnn>_<slug>.py`.
- Within a wave, each branch chains from the head on `main` when the wave started. The
  integrator re-chains `down_revision` when merging so history stays linear.

## Quality bar

- Python: `uv` project per service, Python 3.12, ruff, mypy (strict on `core` and money code),
  pytest. Money, pricing and calibration code is test-first.
- Web: pnpm, TypeScript strict, ESLint, Vitest, Testing Library.
- Contracts: `scripts/assemble_contracts.py` builds `contracts/openapi.yaml` from
  `specs/*/contracts/*.yaml`; contract tests check the running API against it.
- Mark finished tasks `[x]` in the spec's `tasks.md`. Commit in small logical commits with
  messages that end with the co-author trailer.
- House style for docs: no em dashes.
