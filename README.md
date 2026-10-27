# Callwright

A platform for building, running and continuously improving AI voice agents. Implementation
follows the spec-kit features under `specs/` in waves (see `BUILD.md`).

- `.specify/memory/constitution.md`: project principles every plan is checked against
- `research/architecture.md`: high-level design and binding conventions (layout, modules, API, IDs, call lifecycle)
- `research/calldash-functional-spec.md`: functional spec of the reference product, recovered from its public web bundle
- `research/`: crawl evidence (screens, page text, endpoint list, observed response shapes)
- `specs/NNN-*`: spec-kit features, each with spec, plan, research, data model, contracts, quickstart and tasks

Workflow: `/speckit-specify` > `/speckit-clarify` > `/speckit-plan` > `/speckit-tasks` > `/speckit-implement`.

## Running locally

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/) and Python 3.12. No vendor accounts are
needed: the API defaults to an offline identity provider and a fake Stripe.

```bash
cp .env.example .env          # optional; every value has a working default
make up                       # Postgres 16 + pgvector on :55432, Redis on :56379
make migrate                  # Alembic migrations (001, 003, 002, then FKs), then the agent templates
make api                      # API on http://localhost:8100 (docs at /v1/docs)
make worker                   # arq jobs worker (nightly ledger reconciliation)
make test                     # pytest: unit, contract and integration (needs `make up`)
make lint typecheck           # ruff and mypy
make contracts                # rebuild contracts/openapi.yaml from specs/*/contracts
```

Dev sign-up without email: `POST /v1/auth/register`, then read the verification link from the API
log or `GET /v1/dev/mail` and send its `token_hash` to `POST /v1/auth/verify-email`. The new
workspace starts with $5.00 of trial credit. Top-ups in fake mode open
`/v1/dev/fake-checkout/{id}`, whose Pay button sends a signed webhook through the real handler.

| Service | Port |
|---|---|
| Postgres (pgvector) | 55432 |
| Redis | 56379 |
| API | 8100 |
| Web dev server | 5180 |
| Voice worker health | 8190 |

Other commands: `make db-reset` (drop and re-migrate the dev schema),
`uv run --directory services/api python -m app.billing.jobs reconcile --now` (ledger check),
`uv run --directory services/api python -m app.usage.seed_demo --workspace ws_...` (demo usage).

Operations reference (hosting, deploys, telephony lab, homepage playground, test checkout): `docs/OPERATIONS.md`. Current state: `STATUS.md`.
