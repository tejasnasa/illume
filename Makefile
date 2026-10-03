# Developer entry points for Illume.
#
# Everything the two applications need day to day lives here: bootstrap, the dev
# servers, the database and its migrations, linting and formatting, the three test
# suites, and the standalone scripts under server/scripts/.
#
# Run `make` or `make help` for the full list.
#
# Postgres (with pgvector) and Redis are yours to supply -- there is no dev compose
# file. `make dev-infra` starts a pair on the default ports (5432 / 6379) for the dev
# servers; `make test-infra` starts a separate pair on the offset test ports
# (5433 / 6380) so a running dev stack is never touched. See docker-compose.test.yml.

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose -f docker-compose.test.yml
TEST_DB := postgresql://illume:test@localhost:5433/illume_test
STUB_PORT := 8099

# Celery's default `prefork` pool does not work on Windows, so `solo` is the fallback
# there. On Linux, `prefork --concurrency=1` is the intended shape and the one CI and
# production use: a single ingest already uses the machine (its overlapped stages are
# threads, not processes), and each peaks at several hundred MB.
ifeq ($(OS),Windows_NT)
  CELERY_POOL := --pool=solo
else
  CELERY_POOL := --pool=prefork --concurrency=1
endif

.PHONY: help install env setup \
        dev-infra dev-infra-down test-infra test-infra-down \
        migrate migrate-test migration downgrade db-truncate seed-e2e \
        api worker beat web stub \
        test test-be test-be-all test-be-one test-fe test-fe-ui \
        test-e2e test-e2e-prod test-e2e-report \
        cov cov-be cov-fe \
        lint lint-be lint-be-app lint-fe fmt fmt-be fmt-be-app fmt-fe \
        build-fe docker-build probe-ai clean

help:
	@echo "Bootstrap"
	@echo "  make install          install backend and frontend dependencies"
	@echo "  make env              create server/.env and client/.env from the examples"
	@echo "  make setup            install + env + migrate"
	@echo ""
	@echo "Infrastructure"
	@echo "  make dev-infra        start Postgres and Redis for development (5432 / 6379)"
	@echo "  make dev-infra-down   stop them, keeping their data"
	@echo "  make test-infra       start the offset test stack (5433 / 6380)"
	@echo "  make test-infra-down  stop the test stack"
	@echo ""
	@echo "Database"
	@echo "  make migrate          apply migrations to the database in server/.env"
	@echo "  make migrate-test     apply migrations to the test database"
	@echo "  make migration m=...  autogenerate a revision from the model changes"
	@echo "  make downgrade        roll back one revision"
	@echo "  make db-truncate      empty every table (destructive -- see the target)"
	@echo "  make seed-e2e         seed a user and two repositories for the E2E suite"
	@echo ""
	@echo "Dev servers -- each runs in the foreground, so use separate shells"
	@echo "  make api              FastAPI on :8000, reloading"
	@echo "  make worker           Celery worker, both queues"
	@echo "  make beat             Celery beat, the auto-update scheduler"
	@echo "  make web              Next.js on :3000"
	@echo "  make stub             OpenAI stub server on :$(STUB_PORT)"
	@echo ""
	@echo "Tests"
	@echo "  make test             both suites"
	@echo "  make test-be          backend tests, excluding slow (needs test-infra)"
	@echo "  make test-be-all      backend tests, including slow"
	@echo "  make test-be-one f=   a single backend path or test id"
	@echo "  make test-fe          frontend tests"
	@echo "  make test-fe-ui       frontend tests in the watch UI"
	@echo "  make test-e2e         Playwright against a real stack (needs test-infra)"
	@echo "  make test-e2e-prod    Playwright against the deployed site (needs client/.env.smoke)"
	@echo "  make test-e2e-report  open the last Playwright report"
	@echo "  make cov              both suites with coverage"
	@echo "  make cov-be           backend coverage"
	@echo "  make cov-fe           frontend coverage"
	@echo ""
	@echo "Lint, format, build"
	@echo "  make lint             both projects, the scope CI blocks on"
	@echo "  make lint-be          ruff + mypy over server/tests"
	@echo "  make lint-be-app      ruff + mypy over server/app (report-only, standing debt)"
	@echo "  make lint-fe          typegen + tsc + eslint over the client tests and config"
	@echo "  make fmt              autofix and format the trees CI blocks on"
	@echo "  make fmt-be-app       ruff over server/app (large diff -- see the target)"
	@echo "  make build-fe         production build of the client"
	@echo "  make docker-build     build the server image locally"
	@echo ""
	@echo "Other"
	@echo "  make probe-ai         probe a real LLM provider with the app's request shapes"
	@echo "  make clean            remove build and test artefacts"

# ------------------------------------------------------------------- bootstrap

install:
	cd server && uv sync
	cd client && npm install

# Never overwrites an existing .env.
env:
	@for d in server client; do \
	  if [ -f $$d/.env ]; then \
	    echo "$$d/.env already exists, leaving it alone"; \
	  else \
	    cp $$d/.env.example $$d/.env; \
	    echo "created $$d/.env"; \
	  fi; \
	done
	@echo
	@echo "DOMAIN is required by the backend but missing from server/.env.example --"
	@echo "add a bare hostname (localhost, or your domain) before starting the API."

setup: install env migrate

# -------------------------------------------------------------- infrastructure

# Mirrors the docker run pair in the README. Idempotent: an existing container is
# started rather than recreated, so the development database survives.
dev-infra:
	@docker start illume-postgres >/dev/null 2>&1 || docker run -d --name illume-postgres \
	  -e POSTGRES_USER=illume -e POSTGRES_PASSWORD=illume -e POSTGRES_DB=illume \
	  -p 5432:5432 pgvector/pgvector:pg16 >/dev/null
	@docker start illume-redis >/dev/null 2>&1 || docker run -d --name illume-redis \
	  -p 6379:6379 redis:7 >/dev/null
	@echo "Postgres on 5432 and Redis on 6379."

# Stops rather than removes: there is no volume, so `docker rm` would take the
# development database with it.
dev-infra-down:
	@docker stop illume-postgres illume-redis >/dev/null 2>&1 || true
	@echo "Stopped. The data is still in the containers."

test-infra:
	$(COMPOSE) up -d --wait

test-infra-down:
	$(COMPOSE) down

# -------------------------------------------------------------------- database

# Alembic reads SYNC_DATABASE_URL from server/.env, which in a configured checkout may
# point at production. Use `make migrate-test` when you mean the test database.
migrate:
	@echo "-> alembic upgrade head, against the SYNC_DATABASE_URL in server/.env"
	cd server && uv run alembic upgrade head

migrate-test:
	cd server && SYNC_DATABASE_URL=$(TEST_DB) uv run alembic upgrade head

# New model modules must also be imported in alembic/env.py, or autogenerate will not
# see them.
migration:
	@test -n "$(m)" || { echo 'usage: make migration m="what changed"'; exit 1; }
	cd server && uv run alembic revision --autogenerate -m "$(m)"

downgrade:
	cd server && uv run alembic downgrade -1

# Truncates every table in FK-safe order. Destructive: against a development database
# this loses every ingested repository, every chat turn and every stored key. Against
# the test stack it is harmless. It follows SYNC_DATABASE_URL like `migrate` does.
db-truncate:
	@echo "-> truncating every table in the database at SYNC_DATABASE_URL"
	cd server && uv run python -m app.scripts.clean

# Needs the API to be listening. Safe to re-run: the E2E user's repositories are
# deleted and rebuilt each time.
seed-e2e:
	cd server && uv run python scripts/seed_e2e.py

# ---------------------------------------------------------------- dev servers

api:
	cd server && uv run fastapi dev

# One process consumes both queues: `celery` for initial ingests and `sync` for
# background updates, so a sync serialises against an ingest rather than racing it.
worker:
	cd server && uv run celery -A app.core.celery worker --loglevel=info $(CELERY_POOL) -Q celery,sync

# The scheduler is a separate process from the worker. Only production needs `-s`; see
# docs/deployment.md.
beat:
	cd server && uv run celery -A app.core.celery beat --loglevel=info

web:
	cd client && npm run dev

# The E2E API points OPENAI_BASE_URL here, so every LLM call it makes lands on this
# process. Rarely needed by hand -- `make test-e2e` starts its own.
stub:
	cd server && uv run python scripts/openai_stub_server.py

# ----------------------------------------------------------------------- tests

test: test-be test-fe

test-be:
	cd server && uv run pytest -m "not slow"

test-be-all:
	cd server && uv run pytest

test-be-one:
	@test -n "$(f)" || { echo "usage: make test-be-one f=tests/unit/services/test_rag.py"; exit 1; }
	cd server && uv run pytest -m "not slow" $(f)

test-fe:
	cd client && npm run test:run

test-fe-ui:
	cd client && npm run test:ui

# Starts three servers of its own (the API, an OpenAI stub and a Next production build)
# and seeds its own database, so `test-infra` has to be up but nothing else does.
test-e2e:
	cd client && npm run test:e2e

# Runs against the deployed site: starts nothing, needs no infrastructure, and reads
# `client/.env.smoke`. It writes one chat turn to production and deletes it again.
test-e2e-prod:
	cd client && npm run test:e2e:prod

test-e2e-report:
	cd client && npm run test:e2e:report

cov: cov-be cov-fe

cov-be:
	cd server && uv run pytest --cov=app --cov-report=json:coverage.json -n auto

cov-fe:
	cd client && npm run test:coverage

# ----------------------------------------------------------- lint and format

lint: lint-be lint-fe

lint-be:
	cd server && uv run ruff check tests/ && uv run ruff format --check tests/ && uv run mypy tests/ --follow-imports=silent

# Report-only. server/app carries standing lint and type debt that CI deliberately does
# not block on; the leading `-` lets the run finish so the debt stays visible without
# becoming a merge gate.
lint-be-app:
	-cd server && uv run ruff check app/
	-cd server && uv run mypy app

# `next typegen` first: `next-env.d.ts` is gitignored, so on a fresh checkout `tsc` has
# none of the Next.js global types and fails on every asset import. CI does the same.
lint-fe:
	cd client && npx next typegen && npx tsc --noEmit && npx eslint tests/ e2e/ e2e-prod/ vitest.config.ts

fmt: fmt-be fmt-fe

fmt-be:
	cd server && uv run ruff check --fix tests/ && uv run ruff format tests/

# Expect a large diff. app/ is formatted on save by the editor, and a bulk rewrite
# buries the standing lint debt in it.
fmt-be-app:
	cd server && uv run ruff check --fix app/ && uv run ruff format app/

fmt-fe:
	cd client && npx eslint --fix src/ tests/ e2e/ e2e-prod/

# --------------------------------------------------------------- build, other

build-fe:
	cd client && npm run build

docker-build:
	docker build -t illume-server:local server/

# Mirrors each generation call shape against a real provider, so a wire-format
# mismatch surfaces here rather than as silently empty artefacts. Imports no app
# configuration, so it runs from a bare shell.
probe-ai:
	cd server && uv run python scripts/probe_ai_provider.py

# Build and test artefacts only. It never touches the database -- that is db-truncate.
clean:
	rm -rf client/.next client/coverage client/playwright-report client/test-results
	rm -f server/coverage.json
	find server client -type d -name __pycache__ -prune -exec rm -rf {} +
	find server client -type d -name .pytest_cache -prune -exec rm -rf {} +
	find server client -type d -name .ruff_cache -prune -exec rm -rf {} +
	find server client -type d -name .vitest -prune -exec rm -rf {} +
