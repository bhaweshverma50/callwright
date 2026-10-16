# Callwright developer commands. Ports: Postgres 55432, Redis 56379, API 8100, web 5180.
API := services/api
UV := uv run --directory $(API)

.PHONY: help up down migrate templates-sync db-reset api worker test test-unit test-contract test-integration lint fmt typecheck contracts contracts-check

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

up: ## Start Postgres (pgvector) and Redis, wait until healthy
	docker compose up -d --wait postgres redis

down: ## Stop the local stack (data volumes are kept)
	docker compose down

migrate: ## Apply Alembic migrations to the dev database, then sync the agent templates
	cd $(API) && uv sync --quiet && uv run alembic upgrade head
	$(MAKE) templates-sync

templates-sync: ## Load the launch agent templates (002) into the database (idempotent)
	$(UV) python -m app.templates.jobs sync

db-reset: ## Drop and recreate the dev database schema, then migrate
	docker compose exec -T postgres psql -q -U callwright -d callwright \
	  -c "DROP SCHEMA IF EXISTS local_idp CASCADE; DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	$(MAKE) migrate

api: ## Run the API on :8100 with reload
	$(UV) uvicorn app.main:app --reload --port 8100

worker: ## Run the arq jobs worker
	$(UV) arq app.core.jobs.WorkerSettings

test: ## Run every API test (needs `make up`)
	$(UV) pytest -q

test-unit:
	$(UV) pytest -q tests/unit

test-contract:
	$(UV) pytest -q tests/contract

test-integration:
	$(UV) pytest -q tests/integration

lint: ## ruff lint and format check
	$(UV) ruff check .
	$(UV) ruff format --check .

fmt:
	$(UV) ruff format .
	$(UV) ruff check --fix .

typecheck: ## mypy (strict on core and money code)
	$(UV) mypy app

contracts: ## Rebuild contracts/openapi.yaml from specs/*/contracts
	$(UV) python ../../scripts/assemble_contracts.py

contracts-check: ## Fail when contracts/openapi.yaml is stale
	$(UV) python ../../scripts/assemble_contracts.py --check
