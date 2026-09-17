# Developer entry points for running the test suites.
#
# The backend suite needs real Postgres (with pgvector) and Redis. `make test-infra`
# starts them on the offset test ports (5433 / 6380) so a running dev stack is never
# touched. See docker-compose.test.yml.

SHELL := /bin/bash

.PHONY: help test-infra test-infra-down test test-be test-fe test-e2e lint lint-be lint-fe

COMPOSE := docker compose -f docker-compose.test.yml

help:
	@echo "make test-infra       start the Postgres + Redis test stack"
	@echo "make test-infra-down  stop the test stack"
	@echo "make test             run both suites"
	@echo "make test-be          backend tests (needs test-infra)"
	@echo "make test-fe          frontend tests"
	@echo "make test-e2e         Playwright against a real stack (needs test-infra)"
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

lint: lint-be lint-fe

lint-be:
	cd server && uv run ruff check tests/ && uv run ruff format --check tests/ && uv run mypy tests/ --follow-imports=silent

lint-fe:
	cd client && npx tsc --noEmit && npx eslint tests/ e2e/ vitest.config.ts
