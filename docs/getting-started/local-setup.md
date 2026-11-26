# Local setup

This page takes a fresh clone to a running copy of Illume on your own machine: the API, the background worker, the scheduler and the web client, talking to a local Postgres and Redis. It lists what to install, every value the environment files need, and the problems people hit most often. Once everything is running, [your first ingest](first-ingest.md) shows what happens when you add a repository.

## Terms used on this page

- **API**: the FastAPI application in [`server/`](../../server/), served on port 8000.
- **Worker**: the Celery process that runs ingests and background syncs. Celery is a Python task queue; Redis carries its messages.
- **Beat**: Celery's scheduler, a separate process that queues the auto-update sweep every 10 minutes.
- **pgvector**: a Postgres extension that stores embedding vectors and searches them by similarity.
- **uv**: the Python package and project manager the backend uses.

## What you need

| Tool              | Version                                                                                       | Why                                                                                          |
| ----------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Python            | 3.14 (`requires-python = ">=3.14"` in [`server/pyproject.toml`](../../server/pyproject.toml)) | the backend                                                                                  |
| uv                | recent                                                                                        | installs the backend and runs every backend command                                          |
| Node.js and npm   | a current LTS release                                                                         | the Next.js 16 web client                                                                    |
| Docker            | any recent                                                                                    | Postgres with pgvector, and Redis                                                            |
| git               | any                                                                                           | the worker shells out to `git` to clone repositories                                         |
| GNU make and bash | any                                                                                           | the [`Makefile`](../../Makefile) uses `SHELL := /bin/bash`; on Windows, run it from Git Bash |

You also need an **OpenAI API key**, because embeddings always use the operator's OpenAI key, and **a key for a text-generation model**, either as the server's free-tier key or as your own key added in Settings after you sign in. GitHub OAuth credentials are optional for local work: public repositories clone without them.

## The processes you will run

```mermaid
flowchart LR
    W["Web client<br/>Next.js :3000"] -->|"HTTP and WebSocket"| A["API<br/>FastAPI :8000"]
    A --> P[("Postgres + pgvector<br/>:5432")]
    A --> R[("Redis<br/>:6379")]
    K["Worker<br/>Celery"] --> P
    K --> R
    B["Beat<br/>Celery scheduler"] --> R
    K -->|"git clone"| G["GitHub"]
    K -->|"embeddings and generation"| O["Model providers"]
```

## Steps

### 1. Install dependencies

```bash
make install
```

This runs `uv sync` in `server/` and `npm install` in `client/`. `uv sync` also installs the development tools (pytest, ruff, mypy and the rest), because they are declared in the `dev` dependency group of `pyproject.toml`.

### 2. Start Postgres and Redis

There is no development compose file. `make dev-infra` starts two containers on the default ports:

```bash
make dev-infra
```

| Container         | Image                    | Port | Credentials                                         |
| ----------------- | ------------------------ | ---- | --------------------------------------------------- |
| `illume-postgres` | `pgvector/pgvector:pg16` | 5432 | user `illume`, password `illume`, database `illume` |
| `illume-redis`    | `redis:7`                | 6379 | none                                                |

The containers have no volume. `make dev-infra-down` **stops** them, so the data stays; `docker rm` would delete your development database. The first migration runs `CREATE EXTENSION IF NOT EXISTS vector`, so you do not need to enable pgvector by hand.

The test suites use a separate pair on ports 5433 and 6380 (`make test-infra`), so running tests never touches this database.

### 3. Create the environment files

```bash
make env
```

This copies `server/.env.example` to `server/.env` and `client/.env.example` to `client/.env`, and never overwrites an existing file. Fill them in:

| Variable                                                          | Local value                                                                                          |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`                                                    | `postgresql+asyncpg://illume:illume@localhost:5432/illume`                                           |
| `SYNC_DATABASE_URL`                                               | `postgresql://illume:illume@localhost:5432/illume`                                                   |
| `REDIS_URL`                                                       | `redis://localhost:6379/0`                                                                           |
| `OPENAI_API_KEY`                                                  | your OpenAI key, used for embeddings                                                                 |
| `AI_API_KEY`, `AI_MODEL`, `AI_BASE_URL`                           | the free-tier generation credential; leave `AI_API_KEY` empty to make every user bring their own key |
| `SECRET_KEY`                                                      | a long random string: `python -c "import secrets; print(secrets.token_urlsafe(48))"`                 |
| `CREDENTIAL_ENCRYPTION_KEY`                                       | another random string of at least 32 characters, generated the same way                              |
| `ACCESS_TOKEN_EXPIRE_MINUTES`                                     | for example `10080` (a week)                                                                         |
| `FRONTEND_URL`                                                    | `http://localhost:3000`                                                                              |
| `ENVIRONMENT`                                                     | `development`, so the session cookie is not marked `Secure`                                          |
| `DOMAIN`                                                          | `localhost`: a bare hostname, with no scheme or port                                                 |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_REDIRECT_URL` | from a GitHub OAuth app, or any placeholder if you will not sign in with GitHub                      |
| `RESEND_API_KEY`, `CONTACT_TO_EMAIL`, `CONTACT_FROM_EMAIL`        | leave empty; the contact form then answers 503                                                       |
| `OAUTH_REDIRECT_ALLOWLIST`                                        | `[]` unless you run the mobile app                                                                   |
| `MOBILE_TOKEN_EXPIRE_MINUTES`                                     | leave the example value                                                                              |
| `NEXT_PUBLIC_BACKEND_URL` (in `client/.env`)                      | `http://localhost:8000`                                                                              |

Every `Settings` field without a default is required, so a missing line stops the API, the worker and Alembic at import with a pydantic `ValidationError` naming the field. [Environment variables](../reference/environment.md) describes every variable, including optional ones such as `OPENROUTER_API_KEY` (rerankers and the auto router) and the LangSmith tracing variables.

### 4. Apply the migrations

```bash
make migrate
```

> **Check `SYNC_DATABASE_URL` first.** Alembic migrates whatever database `server/.env` names. On a machine whose `.env` points at a shared or production database, this command migrates that database. Use `make migrate-test` for the test stack; see [changing the schema](../guides/change-the-schema.md#read-this-first-which-database-alembic-touches).

### 5. Start the four processes

Each runs in the foreground, so use four terminals:

```bash
make api       # FastAPI on :8000, reloading on change
make worker    # Celery worker on both queues
make beat      # Celery beat, the auto-update scheduler
make web       # Next.js on :3000
```

| Process | Command it runs                                                                                                                                      |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| api     | `uv run fastapi dev`                                                                                                                                 |
| worker  | `uv run celery -A app.core.celery worker --loglevel=info -Q celery,sync` plus `--pool=solo` on Windows or `--pool=prefork --concurrency=1` elsewhere |
| beat    | `uv run celery -A app.core.celery beat --loglevel=info`                                                                                              |
| web     | `npm run dev`                                                                                                                                        |

Beat is only needed for auto-update. Without it, ingests and chat still work, but no repository updates itself.

### 6. Check that it works

- `curl localhost:8000/healthz` returns `{"status":"ok","checks":{"redis":"ok"}}`.
- `http://localhost:8000/openapi.json` returns the OpenAPI schema. FastAPI's `/docs` page is behind the session cookie, so it answers 401 until you sign in on the same host.
- `http://localhost:3000` shows the landing page. Sign up from `/login`; there is no `/signup` route.
- The worker terminal prints `celery@<host> ready`.

Then follow [your first ingest](first-ingest.md).

## Common problems

| Symptom                                           | Cause and fix                                                                                                              |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `ValidationError` listing field names at start-up | a required variable is missing from `server/.env`                                                                          |
| sign-in succeeds but the next page is signed out  | `DOMAIN` has a scheme or port, or `ENVIRONMENT=production` without HTTPS, so the browser drops the cookie                  |
| the browser console shows CORS errors             | `FRONTEND_URL` does not match the origin you opened, for example `127.0.0.1` against `localhost`                           |
| the worker crashes on Windows with a pool error   | the default `prefork` pool does not work on Windows; `make worker` passes `--pool=solo`; if you run Celery by hand, add it |
| an ingest stays on its first stage                | the worker is not running, or it is not consuming the `celery` queue                                                       |
| the ingest fails at embedding                     | `OPENAI_API_KEY` is missing or has no credit                                                                               |
| chat and ingest answer 402                        | there is no generation key: set `AI_API_KEY` or add your own key in Settings                                               |
| `TS2307` for image imports when running `tsc`     | run `npx next typegen` in `client/` first; `next-env.d.ts` is gitignored                                                   |
| port 5432 or 6379 is already taken                | another Postgres or Redis is running; stop it, or change the ports and URLs together                                       |

## Design trade-offs and limits

- **No one-command stack.** There is no development compose file, so the four processes and two containers are started separately. The Makefile keeps each one to a single command.
- **Real providers in development.** A local stack calls OpenAI and your generation provider for real and spends real money. Only the test suites fake them.
- **Ephemeral containers.** The development containers have no volumes; removing them deletes the data.
- **Windows runs a different worker pool.** `--pool=solo` ignores `--concurrency` and `--max-tasks-per-child`, so memory recycling behaves differently from production.

## Related documentation

- [Your first ingest](first-ingest.md): what happens after you add a repository.
- [Repository layout](repository-layout.md): where everything lives.
- [Environment variables](../reference/environment.md): every variable in detail.
- [CLI reference](../reference/cli.md): every Makefile target and script.
- [Testing overview](../testing/overview.md): running the three suites.
