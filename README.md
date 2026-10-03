<div align="center">

# 🧠 Illume

**AI Powered Codebase Onboarding & Architecture Intelligence**

An enterprise-grade codebase intelligence and developer velocity platform. Illume parses multi-language syntax trees, builds relational dependency graphs, digests git history, and applies LLM reasoning to compile static repositories into living, interactive onboarding guides.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Python: 3.14+](https://img.shields.io/badge/Python-3.14%2B-blue.svg?logo=python&logoColor=white&style=flat-square)](https://www.python.org)
[![Next.js: 16+](https://img.shields.io/badge/Next.js-16%2B-black.svg?logo=nextdotjs&logoColor=white&style=flat-square)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135%2B-009688.svg?logo=fastapi&logoColor=white&style=flat-square)](https://fastapi.tiangolo.com)
[![Celery](https://img.shields.io/badge/Celery-5.6%2B-37814A.svg?logo=celery&logoColor=white&style=flat-square)](https://docs.celeryq.dev)

[![CI](https://github.com/tejasnasa/illume/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tejasnasa/illume/actions/workflows/ci.yml)
[![Backend coverage](https://img.shields.io/badge/backend%20coverage-80%25-brightgreen?style=flat-square)](#running-tests)
[![Frontend coverage](https://img.shields.io/badge/frontend%20coverage-62%25-brightgreen?style=flat-square)](#running-tests)

[Live Demo](https://illume.tejasnasa.me) · [Documentation](docs/README.md) · [Architecture](docs/architecture.md) · [Key Features](#-core-capabilities) · [Getting Started](#-installation--getting-started)

</div>

---

## 📖 Introduction & Philosophy

Codebases grow in complexity far faster than engineering teams can scale. When a new engineer joins a team, they face a massive cognitive load: thousands of lines of code, complex module connections, outdated wikis, and hidden tribal knowledge about who owns what. Traditional static documentation goes stale immediately, and senior engineers spend valuable hours manually walking new hires through the architecture.

**Illume** is built on the philosophy that **the codebase itself is the single source of truth**. By combining:

1. **Deterministic AST Parsing** (using Tree-sitter) to extract syntax models.
2. **Git intelligence mining** to attribute active contributions and capture knowledge silos.
3. **Graph-theoretic topological analysis** to calculate dependency tiers.
4. **Semantic LLM reasoning & vector search** (`pgvector`) to contextually explain modules.

Illume builds a fully indexable, interactive, 3D visual workspace that turns repository onboarding from a weeks-long struggle into a self-guided, afternoon task.

---

## ⚡ Core Capabilities

### 🗺️ Deterministic Topological Learning Paths

Rather than listing files alphabetically or leaving it to guesswork, Illume runs a **Topological Sorting Algorithm** on the codebase's internal import graph.

- **How it works**: Files are nodes, and directed edges are created when a file imports a symbol defined in another file.
- **Cycle Handling**: Codebases frequently contain cyclic dependencies. Illume identifies cycles, groups them cleanly, and falls back to sorting files within cycles by their architectural weight (**fan-in** count) before appending them to the reading guide.
- **AI Contextualization**: Each step in the path is sent in batches to the LLM to generate clear, 1-2 sentence descriptions detailing _why_ reading this file unlocks understanding of downstream components.

### 👥 Git Intelligence & Knowledge Silo Maps

Illume mines up to `500` historical git commits using `git log --numstat` parsing.

- **Contribution Attribution**: Calculates exactly what percentage of each file's changes were authored by which engineer.
- **Knowledge Silo Flags**: Flags files with a **Bus Factor of 1** (e.g., touched only by a single engineer) so teams can spot single points of human failure immediately.
- **Test Presence Safeguards**: Auto-generates template mappings (e.g., `test_{stem}.py`, `{stem}.spec.ts`) to cross-check file test coverage against git update frequency.

### 🔴 Architectural Criticality (Traffic-Light Prioritization)

Files are automatically grouped into three distinct priority levels based on mathematical thresholds:

Each file accumulates a score, and the score maps to a tier. The points are:

- **+3** if the file is imported by 10 or more files (high fan-in), or **+1** if 5–9 files import it.
- **+2** if the path matches a sensitive pattern such as `database.py`, `auth.py`, or `middleware/`.
- **+1** if the file has not been modified for more than 180 days.
- **+1** if the file has no test while the repository does have tests.

The tiers are:

- 🔴 **Critical** — a score of **4 or more**.
- 🟡 **Caution** — a score of **2 or 3**.
- 🟢 **Safe to Explore** — below 2. Low risk, decoupled modules, perfect for new hires to start writing PRs.

### 🌐 Interactive 3D WebGL Dependency Graph

Renders module imports dynamically inside the browser utilizing WebGL and `react-force-graph-3d` (powered by Three.js).

- **Visual Semantics**: Nodes represent files, sized by lines of code and colored according to their traffic-light criticality.
- **Two Levels**: Switch between the file graph and a symbol-level graph of functions and classes.
- **Reading-Order Tour**: Step through the generated reading path directly on the graph.
- **Search**: Matching nodes are highlighted with animated halo rings.

### 🔍 Unified Semantic RAG Chat & Glossary

- **Domain Glossary**: Tree-sitter extracts all classes, functions, and interfaces. The LLM translates these technical symbols into business-domain definitions, compiling a searchable, living glossary.
- **Multi-Source RAG**: Vector search combines code syntax blocks, commit messages, and PR summaries. Embedding vectors are generated using `text-embedding-3-small` (1536 dimensions) and indexed in `pgvector` for fast cosine-similarity search.

### 🔄 Background Auto-Update

A per-repository switch keeps an ingested analysis current without a manual `reingest`. A Celery beat process claims repos whose `next_sync_at` is due, probes the head SHA cheaply, and dispatches a worker that updates only the files that actually changed. The deterministic graph rebuild and the LLM/glossary/embed phase are both reused from the ingest path — work scales with the diff, not the repository size, while the graph stays live (`status='ready'`) the whole time.

Two commit watermarks let a partially failed update resume: deterministic data and LLM artefacts track the commit they reflect independently, so an LLM outage does not force a full re-parse on the next run. Repeated failures back off exponentially and eventually disable the switch rather than retrying forever.

### 🔑 Bring-Your-Own API Key (BYOK) & One-Ingestion Free Tier

A new user can ingest **one** repository and ask **five** chat questions on the operator's key before being asked to attach their own. Embeddings stay on the server because the index is provider-uniform; everything else (glossary, reading order, architecture brief, chat answers) runs on the user's chosen provider.

- **Presets** — OpenAI, Groq, OpenRouter, DeepSeek. Pick one in `/settings`, paste a key, save. The save handler probes with a 16-token Responses call, so an incompatible provider/model/reasoning combination fails at the form rather than as silently empty artefacts.
- **Embeddings** — Server key, `text-embedding-3-small`. The 1536 dimensions are baked into the schema; switching the embed provider is a migration, not a configuration.
- **The free tier** — without a stored key, the first ingest and the next five chat questions run on the operator's DeepSeek key. After that, reingest, auto-update and any further chat question need a stored key.
- **Stored key always wins** — once a user has a key, the gate is open regardless of counters. Removing the key does not restore the allowance.
- **Plaintext at rest** — keys are stored as plaintext to match `github_access_token`. A user's OpenAI key carries billing, so treat your account credentials accordingly; never share a session cookie, and rotate a key at the provider the moment it has been exposed.

### 📡 Live Analysis Progress

Ingestion streams its progress to the browser over a Redis pub/sub channel relayed by a WebSocket. Every frame carries a `stage` and a `phase`, so the UI renders the pipeline as a live diagram — which stage is running, which have finished, and how far through parsing and embedding the run is. Failed runs show the retry attempt count, since a failed ingest is retried up to three times.

### 📦 Portable Analysis Export

Any analysed repository can be downloaded as a single compact text document (`.illume`). It holds the repository's metadata, architecture summary, dependency edges, symbol listing, and criticality hotspots. It is sized to fit in an LLM context window, and ordered so the most structurally important files survive truncation.

---

## 🛠 Tech Stack

| Layer                  | Technology                    | Description                                                                  |
| ---------------------- | ----------------------------- | ---------------------------------------------------------------------------- |
| **Frontend Framework** | Next.js 16 (App Router)       | Dynamic React framework for production-grade web applications.               |
| **Backend Framework**  | FastAPI (Python 3.14, Async)  | High-performance web framework for APIs and WebSocket logic.                 |
| **Syntax Parsing**     | Tree-sitter                   | Deterministic multi-language Abstract Syntax Tree (AST) scanning.            |
| **Task Queue**         | Celery + Redis                | Distributed asynchronous queue pipeline for heavy clone and scan operations. |
| **Database & ORM**     | PostgreSQL + SQLAlchemy 2.0   | Scalable relational storage for file graphs, AST symbols, and git logs.      |
| **Vector Search**      | pgvector + OpenAI Embeddings  | Cosine-similarity searches over 1536-dimensional semantic chunk spaces.      |
| **Real-time Logs**     | WebSockets + Redis Pub/Sub    | Real-time progressive ingestion log streams from worker to browser.          |
| **3D Force Graphing**  | WebGL (react-force-graph-3d)  | Accelerated interactive 3D module import graph visualization.                |
| **UI & Animations**    | Tailwind CSS 4 + Motion       | Modern design tokens and fluid micro-animations for high-fidelity UX.        |

---

## 📂 Codebase Directory Structure

```
illume/
├── docs/                       # Full documentation — start at docs/README.md
│
├── client/                     # Next.js Frontend Application
│   ├── e2e/                    # Playwright end-to-end suite
│   ├── e2e-prod/               # Production smoke suite
│   ├── src/
│   │   ├── app/                # App Router routes
│   │   │   ├── dashboard/      # Repository workspace
│   │   │   ├── settings/       # BYOK credential management
│   │   │   ├── contact/        # Public contact form
│   │   │   └── repo/[id]/      # explorer · glossary · graph sub-routes
│   │   ├── actions/            # Server actions (mutations)
│   │   ├── api/                # Server-side API clients (cookie-forwarding)
│   │   ├── components/         # UI components (+ ui/ primitives)
│   │   ├── hooks/              # Client hooks (useChat, useIngestStream, …)
│   │   ├── types/              # Domain types and zod validators
│   │   └── proxy.ts            # Middleware auth gate
│   └── tests/                  # Vitest suite
│
└── server/                     # FastAPI Backend Application
    ├── app/
    │   ├── api/v1/             # 11 routers, mounted under /api/v1
    │   ├── core/               # Config, database engines, security, Celery, Redis
    │   ├── middleware/         # AuthMiddleware — the JWT cookie gate
    │   ├── models/             # 12 SQLAlchemy models
    │   ├── services/           # Domain logic (parser, graph, embedder, rag, …)
    │   └── tasks/              # Celery tasks: ingestion, sync, auto-update sweep
    ├── alembic/                # Database migrations
    ├── scripts/                # Standalone utilities
    ├── tests/                  # pytest suite
    └── Dockerfile              # Production image
```

---

## 🚀 Installation & Getting Started

### 📋 Prerequisites

- **Python 3.14+** (managed via [uv](https://github.com/astral-sh/uv))
- **Node.js 18+** & **npm**
- **PostgreSQL 16+ with the [`pgvector`](https://github.com/pgvector/pgvector) extension**
- **Redis**
- **OpenAI API Key** (for embeddings)
- **GitHub OAuth app credentials** (for private repositories)

> **There is no development `docker-compose.yml` in this repository.** `docker-compose.test.yml` is the only committed compose file, and it publishes its services on **5433** and **6380** — offset so the test stack never collides with a development stack. You need to supply Postgres (with pgvector) and Redis yourself — Step 1 below starts both.

---

### 📦 Step 1: Start PostgreSQL and Redis

Run a Postgres image with pgvector, for example:

```bash
docker run -d --name illume-postgres \
  -e POSTGRES_USER=illume -e POSTGRES_PASSWORD=illume -e POSTGRES_DB=illume \
  -p 5432:5432 pgvector/pgvector:pg16

docker run -d --name illume-redis -p 6379:6379 redis:7
```

The `vector` extension is created by the first migration, so no init script is needed.

---

### 🐍 Step 2: Configure the FastAPI Backend Server

```bash
cd server
cp .env.example .env
```

`server/.env.example` documents every variable inline. Fill in at least the database URLs, Redis URL, `SECRET_KEY`, `DOMAIN`, and your `OPENAI_API_KEY`.

```bash
uv sync                            # install dependencies
uv run alembic upgrade head        # apply migrations
uv run fastapi dev                 # API on :8000
```

> **`alembic upgrade head` targets whatever `SYNC_DATABASE_URL` points at**, which in a configured checkout may be production. See [data-model.md](docs/data-model.md#migrations).

---

### 🌾 Step 3: Run the Celery Worker

Celery handles long-running repository ingestion. The worker and the scheduler are **two separate processes**:

```bash
cd server
uv run celery -A app.core.celery worker --loglevel=info --pool=solo   # ingestion worker
uv run celery -A app.core.celery beat                                 # auto-update scheduler
```

On Windows, the `prefork` pool is unavailable — use `--pool=solo` or `-P threads`. On Linux, prefer `--pool=prefork --concurrency=1`, which is the production configuration: each ingestion peaks at several hundred MB, and the default pool sizes itself from the container's CPU count rather than the VM's.

---

### 💻 Step 4: Boot the Next.js Web Client

```bash
cd ../client
cp .env.example .env
npm install
npm run dev
```

The web interface is now at **`http://localhost:3000`**. Sign in with GitHub, submit any public or private repository, and watch the analysis run in real time.

---

## 🧪 Running Tests

> **📖 Full guide: [`docs/testing.md`](docs/testing.md).** It covers all three suites in depth — what each layer is for, every command and flag, how the fixtures and mocks work, the coverage gates, and how to write a new test. What follows here is the quick version.

The backend suite needs a real PostgreSQL (with `pgvector`) and Redis. A compose file is committed for exactly this, on ports **5433** and **6380** so it never collides with the dev stack on 5432 and 6379.

```bash
docker compose -f docker-compose.test.yml up -d      # test infra (or: make test-infra)
```

**Backend** (`server/`) — `uv`, `pytest`:

```bash
cd server
uv run pytest -m smoke                          # fast boot check, no infra assumptions
uv run pytest -m "not slow"                     # full PR suite
uv run pytest --cov=app --cov-report=term-missing -n auto
uv run ruff check tests/ && uv run mypy tests/
```

**Frontend** (`client/`) — `vitest`:

```bash
cd client
npm test                    # watch mode
npm run test:run            # single pass
npm run test:coverage       # with coverage
npm run lint && npx tsc --noEmit
```

**End-to-end** (`client/e2e/`, Playwright) — the same test infrastructure, plus a real browser against a real API and a production build:

```bash
docker compose -f docker-compose.test.yml up -d
cd client
npm run test:e2e            # or: npm run test:e2e -- --ui
```

The suite starts the API, a stub OpenAI server, and a Next production build itself, and seeds a user and two ingested repositories directly. It never calls GitHub or OpenAI, and it needs no Celery worker. `E2E_API_PORT` and `E2E_CLIENT_PORT` move it off the default ports when a dev stack is already running. It runs nightly and on `main` rather than on every PR — see `.github/workflows/ci.yml`.

**Production smoke** (`client/e2e-prod/`) — a black-box suite that runs nightly against the deployed instance, signing in and checking that the live site and its dependencies are healthy:

```bash
cd client
npm run test:e2e:prod
```

### Coverage ratchet

Both suites enforce a floor, recorded in a committed `.coverage-floor` file (`server/.coverage-floor`, `client/.coverage-floor`). CI fails if measured coverage drops below it. There is no absolute target: the floor only moves up, and a PR that raises coverage is expected to raise the file in the same commit so the reviewer sees the bump. The shields at the top of this file carry the floor values, not a last-measured number, so they stay true between runs — update them in the same commit that moves a floor.

`make test` runs both suites; `make lint` runs both linters. Test markers: `smoke`, `unit`, `integration`, `security`, `migration`, `slow`.

> **Note:** `tests/conftest.py` points the app at the test database by setting environment variables _before_ importing anything under `app`. Settings and both database engines are constructed at import time, so this ordering is required — see the module docstring before moving those imports.

---

## 🏗 Architecture at a Glance

Two applications in one repository, deployed separately:

- **`server/`** — a FastAPI API, a Celery worker, and a Celery beat scheduler. Ingestion clones a repository, parses it with tree-sitter, resolves imports into a dependency graph, mines git history, scores criticality, and runs the LLM phase.
- **`client/`** — a Next.js 16 App Router application. Server components fetch with the user's cookie forwarded; client components call the API directly.

Three design decisions shape most of the code, and each is explained in
[architecture.md](docs/architecture.md#design-decisions-and-trade-offs):

- **Async and sync are split by caller, not by layer** — routes use asyncpg, Celery and Alembic use psycopg2.
- **Overlapped pipeline stages share no database session** — every concurrent stage receives only scalars and opens its own connection.
- **Idempotency is enforced by database constraints**, not application locking, so concurrent work on the same repository inserts once rather than duplicating.

---

## 📚 Documentation

The full documentation lives in [`docs/`](docs/README.md). It is written to be read start to finish by someone who has never seen the repository.

| Document | Covers |
| --- | --- |
| [architecture.md](docs/architecture.md) | The system end to end, plus the design decisions and their trade-offs |
| [pipeline/ingestion.md](docs/pipeline/ingestion.md) | The analysis pipeline: stages, concurrency, ordering, retries |
| [pipeline/sync.md](docs/pipeline/sync.md) | Background auto-update: leases, watermarks, backoff, clone cache |
| [pipeline/generation.md](docs/pipeline/generation.md) | The LLM artefacts, provider abstraction, and BYOK credentials |
| [pipeline/retrieval.md](docs/pipeline/retrieval.md) | Embedding, vector search, and the RAG chat |
| [pipeline/graph.md](docs/pipeline/graph.md) | The dependency graph and its 3D rendering |
| [api.md](docs/api.md) · [websockets.md](docs/websockets.md) | The HTTP API and the live progress stream |
| [data-model.md](docs/data-model.md) · [auth.md](docs/auth.md) | Schema and migrations; authentication and authorisation |
| [pipeline/git-intelligence.md](docs/pipeline/git-intelligence.md) · [frontend.md](docs/frontend.md) | Ownership and criticality; the Next.js application |
| [deployment.md](docs/deployment.md) · [exports.md](docs/exports.md) | Containers, CI/CD and the production env file; the `.illume` text export |
| [testing.md](docs/testing.md) | All three test suites, in depth |

---

## 🛡 Security

If you discover a security vulnerability within Illume, please send an e-mail to tejasnasa1908@gmail.com. All security vulnerabilities will be promptly addressed.

Known limitations are documented rather than hidden — see the end of [api.md](docs/api.md#design-decisions-and-trade-offs) and [auth.md](docs/auth.md#the-threat-model).

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---

<div align="center">

**Built with ❤️ for teams everywhere by [Tejas Nasa](https://github.com/tejasnasa)**

[![Follow Tejas](https://img.shields.io/github/followers/tejasnasa?label=Follow&style=social)](https://github.com/tejasnasa)
[![Twitter Follow](https://img.shields.io/twitter/follow/tejasnasa?style=social)](https://twitter.com/tejasnasa)

</div>
