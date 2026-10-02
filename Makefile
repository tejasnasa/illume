# Developer entry points for running the test suites.
#
# The backend suite needs real Postgres (with pgvector) and Redis. `make test-infra`
# starts them on the offset test ports (5433 / 6380) so a running dev stack is never
# touched. See docker-compose.test.yml.

SHELL := /bin/bash

.PHONY: help test-infra test-infra-down test test-be test-fe test-e2e test-e2e-prod lint lint-be lint-fe

COMPOSE := docker compose -f docker-compose.test.yml

help:
	@echo "make test-infra       start the Postgres + Redis test stack"
	@echo "make test-infra-down  stop the test stack"
	@echo "make test             run both suites"
	@echo "make test-be          backend tests (needs test-infra)"
	@echo "make test-fe          frontend tests"
	@echo "make test-e2e         Playwright against a real stack (needs test-infra)"
	@echo "make test-e2e-prod    Playwright against the deployed site (needs client/.env.smoke)"
	@echo "make lint             lint and typecheck both projects"

test-infra:
	$(COMPOSE) up -d --wait

test-infra-down:
	$(COMPOSE) down

test: test-be test-fe

test-be:
	cd server && uv run pytest -m "not slow"

test-fe:
	cd client && npm run test:run

# Starts three servers of its own (the API, an OpenAI stub, and a Next production build)
# and seeds its own database. `test-infra` must already be up.
test-e2e:
	cd client && npm run test:e2e

# Runs against the deployed site, so it starts nothing and needs no infrastructure -- only
# `client/.env.smoke` with the smoke account's credentials. It writes one chat turn to
# production and deletes it again.
test-e2e-prod:
	cd client && npm run test:e2e:prod

lint: lint-be lint-fe

lint-be:
	cd server && uv run ruff check tests/ && uv run ruff format --check tests/ && uv run mypy tests/ --follow-imports=silent

# `next typegen` first: `next-env.d.ts` is gitignored, so on a fresh checkout `tsc` has
# none of the Next.js global types and fails on every asset import. CI does the same.
lint-fe:
	cd client && npx next typegen && npx tsc --noEmit && npx eslint tests/ e2e/ e2e-prod/ vitest.config.ts
