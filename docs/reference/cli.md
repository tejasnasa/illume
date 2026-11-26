# Commands and scripts

Every command-line entry point in the repository: the root [`Makefile`](../../Makefile), the npm scripts of the web and mobile clients, the backend's standalone scripts, the developer tools under `server/tests/tools/`, and the eval CLI. Each entry says what it touches, because several of them reach production or spend real money when run from a configured checkout.

## Terms used on this page

- **Test stack**: Postgres on 5433 and Redis on 6380 from [`docker-compose.test.yml`](../../docker-compose.test.yml), offset from the development ports so a running dev stack is never touched.
- **Eval stack**: Postgres on 5434 and Redis on 6381 from `docker-compose.eval.yml`, with persistent volumes.
- **Configured checkout**: one with a `server/.env`. On the maintainer's machine that file points at the **production** database and holds real keys.

## Danger summary

| Command                                                          | Touches                                                            |
| ---------------------------------------------------------------- | ------------------------------------------------------------------ |
| `make migrate`, `uv run alembic upgrade head`                    | the database in `server/.env`: production in a configured checkout |
| `make downgrade`                                                 | the same, one revision back                                        |
| `make db-truncate`, `python -m app.scripts.clean`                | **empties every table** of the `server/.env` database              |
| `make test-e2e-prod`                                             | the deployed site: writes and deletes one chat turn                |
| `make probe-ai`, `tests.tools.agent_smoke`, `tests.tools.decide` | real provider calls on real keys                                   |
| `python -m evals run generate`, `run judge`, `gold check`        | real spend, capped by `--budget`                                   |

`make migrate-test`, `make test-*`, and every eval command touch only the test or eval stack.

## Makefile

Run `make` or `make help` for the list. Postgres (with pgvector) and Redis are yours to supply; there is no development compose file.

### Bootstrap and infrastructure

| Target                          | Runs                                                                                                                        |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `install`                       | `uv sync` in `server/`, `npm install` in `client/`                                                                          |
| `env`                           | copies `server/.env.example` and `client/.env.example` to `.env`, never overwriting one                                     |
| `setup`                         | `install`, `env`, `migrate`                                                                                                 |
| `dev-infra`                     | starts `illume-postgres` (`pgvector/pgvector:pg16`, 5432) and `illume-redis` (`redis:7`, 6379), reusing existing containers |
| `dev-infra-down`                | stops them; the data stays in the containers                                                                                |
| `test-infra`, `test-infra-down` | the test stack                                                                                                              |
| `eval-infra`, `eval-infra-down` | the eval stack                                                                                                              |

`make env` still prints that `DOMAIN` is missing from `server/.env.example`; the example now includes it, so the message is out of date.

### Database

| Target            | Runs                                                                      |
| ----------------- | ------------------------------------------------------------------------- |
| `migrate`         | `alembic upgrade head` against `SYNC_DATABASE_URL` from `server/.env`     |
| `migrate-test`    | the same against `postgresql://illume:test@localhost:5433/illume_test`    |
| `migration m="…"` | `alembic revision --autogenerate -m "…"`                                  |
| `downgrade`       | `alembic downgrade -1`                                                    |
| `db-truncate`     | `python -m app.scripts.clean`: truncates every table in foreign-key order |
| `seed-e2e`        | `scripts/seed_e2e.py` against a running API                               |
| `eval-migrate`    | `python -m evals db migrate`                                              |

### Dev servers

Each runs in the foreground; use one shell per process.

| Target   | Runs                                                                                                                        |
| -------- | --------------------------------------------------------------------------------------------------------------------------- |
| `api`    | `uv run fastapi dev`, port 8000, reloading                                                                                  |
| `worker` | `celery -A app.core.celery worker -Q celery,sync` with `--pool=solo` on Windows, `--pool=prefork --concurrency=1` elsewhere |
| `beat`   | `celery -A app.core.celery beat`                                                                                            |
| `web`    | `npm run dev`, port 3000                                                                                                    |
| `stub`   | `scripts/openai_stub_server.py`, port 8099                                                                                  |

Celery's default `prefork` pool does not work on Windows. On Linux, `--concurrency=1` matters: the default takes the container's reported CPU count, and two concurrent ingests can exhaust the box's memory. See [deployment](../operations/deployment.md).

### Tests, lint and build

| Target                    | Runs                                                                                                                             |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `test`                    | `test-be` and `test-fe`                                                                                                          |
| `test-be`                 | `pytest -m "not slow"`                                                                                                           |
| `test-be-all`             | `pytest`, including slow tests                                                                                                   |
| `test-be-one f=…`         | one path or test id                                                                                                              |
| `test-fe`, `test-fe-ui`   | `vitest run`, or the watch UI                                                                                                    |
| `test-e2e`                | Playwright with `e2e/playwright.config.ts`; starts the API, the stub and a Next production build itself, needs only `test-infra` |
| `test-e2e-prod`           | Playwright with `e2e-prod/playwright.config.ts` against the deployed site, reading `client/.env.smoke`                           |
| `test-e2e-report`         | opens the last Playwright report                                                                                                 |
| `cov`, `cov-be`, `cov-fe` | coverage; the backend runs with `-n auto`                                                                                        |
| `eval-selftest`           | `python -m evals selftest`, no database                                                                                          |
| `eval-ci`                 | `AI_API_KEY= OPENROUTER_API_KEY= pytest tests/evals`                                                                             |
| `lint`                    | `lint-be` and `lint-fe`, the scope CI blocks on                                                                                  |
| `lint-be`                 | `ruff check`, `ruff format --check` and `mypy` over `server/tests/`                                                              |
| `lint-be-app`             | `ruff` and `mypy` over `server/app/`, report only                                                                                |
| `lint-fe`                 | `next typegen`, `tsc --noEmit`, `eslint` over `tests/`, `e2e/`, `e2e-prod/` and `vitest.config.ts`                               |
| `fmt`, `fmt-be`, `fmt-fe` | autofix the blocking trees                                                                                                       |
| `fmt-be-app`              | ruff over `server/app/`; a large diff                                                                                            |
| `build-fe`                | `npm run build`                                                                                                                  |
| `docker-build`            | `docker build -t illume-server:local server/`                                                                                    |
| `probe-ai`                | `scripts/probe_ai_provider.py`                                                                                                   |
| `clean`                   | removes build and test artefacts and caches; never touches a database                                                            |

`next typegen` comes first because `next-env.d.ts` is gitignored; without it `tsc` cannot resolve asset imports.

## Web client scripts

From [`client/package.json`](../../client/package.json):

| Script                                         | Command                                                           |
| ---------------------------------------------- | ----------------------------------------------------------------- |
| `dev`                                          | `next dev`                                                        |
| `build`, `start`                               | `next build`, `next start`                                        |
| `lint`                                         | `eslint` (over `src/` by default)                                 |
| `typecheck`                                    | `tsc --noEmit` (run `npx next typegen` first on a fresh checkout) |
| `test`, `test:run`, `test:ui`, `test:coverage` | Vitest                                                            |
| `test:e2e`                                     | Playwright, local stack                                           |
| `test:e2e:prod`                                | Playwright, deployed site                                         |
| `test:e2e:report`                              | the HTML report                                                   |

## Mobile app scripts

From [`mobile/package.json`](../../mobile/package.json):

| Script               | Command                                                      |
| -------------------- | ------------------------------------------------------------ |
| `start`              | `expo start --dev-client` (a development build, not Expo Go) |
| `android`, `ios`     | `expo run:android`, `expo run:ios`                           |
| `test`, `test:watch` | Jest                                                         |
| `typecheck`          | `tsc --noEmit`                                               |

See [the mobile app](../mobile/overview.md).

## Backend services

Run from `server/`:

```bash
uv sync
uv run fastapi dev
uv run celery -A app.core.celery worker --loglevel=info --pool=solo -Q celery,sync
uv run celery -A app.core.celery beat
uv run alembic revision --autogenerate -m "describe the change"
```

The worker must consume both queues: `celery` for initial ingests and `sync` for background updates. Beat is a separate process; production passes `-s /var/illume/celerybeat-schedule` so its last-run times survive a redeploy.

## Standalone scripts

| Script                                                                        | Purpose                                                                                                                                                                                                                |
| ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`app/scripts/clean.py`](../../server/app/scripts/clean.py)                   | truncates every table in foreign-key order; run as `python -m app.scripts.clean`                                                                                                                                       |
| [`scripts/seed_e2e.py`](../../server/scripts/seed_e2e.py)                     | registers the E2E user through the real endpoint, then inserts two fully ingested repositories with the test factories; safe to re-run                                                                                 |
| [`scripts/openai_stub_server.py`](../../server/scripts/openai_stub_server.py) | an OpenAI-compatible stub on 8099; the E2E API points `OPENAI_BASE_URL` and `AI_BASE_URL` at it. Imports no app configuration                                                                                          |
| [`scripts/probe_ai_provider.py`](../../server/scripts/probe_ai_provider.py)   | sends each generation call shape, byte for byte, to a real provider, so a wire-format mismatch shows up here rather than as empty artefacts. Flags `--provider`, `--model`, `--base-url`; imports no app configuration |
| [`scripts/mcp_dev.py`](../../server/scripts/mcp_dev.py)                       | migrates and seeds the test stack, then serves the API on 8010 for trying the MCP endpoint by hand; `--cleanup` deletes the seeded user. Sets every `Settings` field so nothing falls through to `server/.env`         |

## Developer tools

Run from `server/` as modules. All use the 30-file retrieval fixture repository.

| Tool                          | Spends credit     | Purpose                                                                                                              |
| ----------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------- |
| `tests.tools.call_tool`       | no                | calls any agent tool by name with JSON arguments and prints what the model would see; `--list`, `--json`, `--schema` |
| `tests.tools.retrieval_trace` | depends on preset | shows which retrieval channels found which files for a question; `--preset`, `--with-grep`, `--list`                 |
| `tests.tools.agent_smoke`     | **yes**           | runs the agent on three fixture questions; key from `AGENT_SMOKE_API_KEY` only                                       |
| `tests.tools.decide`          | **yes**           | runs the decision points once each against Jev, or `--decider llm`                                                   |

```bash
uv run python -m tests.tools.call_tool grep_code '{"pattern": "bcrypt"}'
uv run python -m tests.tools.retrieval_trace "What relies on RateLimiter?"
```

## The eval CLI

`uv run python -m evals <command>` from `server/`. Importing it pins every setting to the eval stack, so it cannot touch the development or production database. The full guide is on [the eval harness](../evals/harness.md).

| Command    | Actions or key flags                                                                                                                                                                                |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `db`       | `migrate`, `status`                                                                                                                                                                                 |
| `corpus`   | `ingest`, `snapshot`, `restore`, `report`; `--repo`, `--corpus`, `--name`                                                                                                                           |
| `mine`     | clone a corpus repository and cache its PRs; `--repo`, `--refresh`                                                                                                                                  |
| `gold`     | `build`, `phrase`, `check`, `verify`, `split`; `--include-anchor`, `--include-rationale`, `--include-structural`, `--include-unanswerable`, `--tuning-test-split`, `--annotator`, `--checker-model` |
| `run`      | `generate`, `judge`, `judge-label`, `judge-agreement`; `--slice`, `--arms`, `--run`, `--subset ARM=N`, `--repeats`, `--off-peak-only`, `--judge-model`, `--sample-only`, `--wait`                   |
| `report`   | `--run` (required), `--mode simple\|full\|pilot`, `--out`, `--judge-slug`                                                                                                                           |
| `selftest` | the metric self-tests                                                                                                                                                                               |
| `budget`   | spend so far; `--project` with `--items`, `--arms`, `--repeats` to estimate a planned run                                                                                                           |

`gold`, `run` and `budget` take `--budget` and `--stop` in US dollars, defaulting to `STARTER_BUDGET_USD = 10.0` and `STARTER_STOP_USD = 9.50` in [`evals/settings.py`](../../server/evals/settings.py). The budget is cumulative across a run's resumptions.

## Design trade-offs and limits

- **One Makefile, two platforms.** Recipes use bash (`SHELL := /bin/bash`); on Windows they need Git Bash or WSL.
- **Production one typo away.** `migrate`, `downgrade` and `db-truncate` follow `server/.env`. The test-stack variants exist precisely because of this.
- **No dev compose file.** `dev-infra` uses bare `docker run` containers without volumes, so `docker rm` loses the data.

## Related documentation

- [Local setup](../getting-started/local-setup.md): the order to run these in.
- [Testing overview](../testing/overview.md): what each suite covers.
- [Environment variables](environment.md): what each process needs.
- [The eval harness](../evals/harness.md): the eval CLI in depth.
