# Testing

Illume has three test suites: **backend** (pytest), **frontend** (Vitest), and **end-to-end**
(Playwright). This document covers what each one is for, how to run them, how they are configured,
and the conventions to follow when adding tests.

## Contents

- [Quick start](#quick-start)
- [Prerequisites](#prerequisites)
- [Test suites](#test-suites)
- [Running tests](#running-tests)
- [Backend suite](#backend-suite)
- [Frontend suite](#frontend-suite)
- [End-to-end suite](#end-to-end-suite)
- [Coverage](#coverage)
- [Continuous integration](#continuous-integration)
- [Known unfixed defects](#known-unfixed-defects)
- [Writing tests](#writing-tests)
- [Troubleshooting](#troubleshooting)

## Quick start

```bash
make test-infra    # start Postgres (5433) and Redis (6380) for the test stack
make test          # backend + frontend suites
```

The end-to-end suite needs the same infrastructure and takes about seven minutes, so it is a
separate target: `make test-e2e`.

[Running tests](#running-tests) lists every target, along with how to run an individual suite,
file, or test.

## Prerequisites

### Docker

The backend and end-to-end suites run against a real PostgreSQL (with the `pgvector` extension) and
a real Redis. `docker-compose.test.yml` at the repo root provides both:

```bash
docker compose -f docker-compose.test.yml up -d
docker compose -f docker-compose.test.yml down
```

Both services listen on ports offset from the development defaults — Postgres on **5433** instead of
5432, Redis on **6380** instead of 6379. This lets the test stack and a development stack run at the
same time without either being mistaken for the other, and it means a test run cannot write to your
development database.

Postgres stores its data in `tmpfs`, so it is recreated from migrations on each run. That is what
keeps the migration tests meaningful: they have to build the schema from nothing.

### pgvector

The first migration runs `CREATE EXTENSION IF NOT EXISTS vector`, and the `Embedding` model declares
a `Vector(1536)` column. Against a plain Postgres image the migration chain stops at revision
`ec40440330c3`. The compose file uses `pgvector/pgvector:pg16`, and CI uses the same image.

### Checking that infrastructure is up

```bash
cd server && uv run pytest -m smoke
```

The smoke tests check that Postgres answers, that the `vector` extension is installed, that Redis
answers, and that the app boots. When the stack is down they fail with the command to start it
rather than a connection traceback.

### Environment bootstrap and import order

`app/core/config.py` instantiates `settings` at import time, `app/core/database.py` builds both
database engines at module scope from those settings, and `app/core/celery.py` constructs the Celery
app on import. Importing anything under `app` therefore binds the database URLs for the rest of the
process, and a fixture is too late to change them.

`server/tests/conftest.py` sets every environment variable at the top of the module, before its
first `app.*` import, and that ordering matters — it is the reason for the `# noqa: E402` comments
on the imports below it. Moving those imports changes which database the suite talks to, and the
change is silent rather than loud.

`pytest_configure` asserts that the configured URLs point at ports 5433 and 6380, so an accidental
override produces a clear assertion.

`server/.env.test.example` documents the same contract. It is not needed for a normal run, since
`conftest.py` sets everything programmatically, but it is useful when running a one-off script
against the test stack.

## Test suites

| Suite | Location | Runner | Docker | Tests | Duration |
|---|---|---|---|---|---|
| Backend | `server/tests/` | pytest | Yes | 818 passing, 7 expected failures | 1–2 min |
| Frontend | `client/tests/`, `client/src/**/__tests__/` | Vitest | No | 522 | ~30 s |
| End-to-end | `client/e2e/` | Playwright | Yes | 45 | ~7 min |

Timings are from a full parallel run and vary with machine load.

A rough guide to which suite a change belongs in:

- A pure function — a parser, a formatter, a validator — is covered by a **backend or frontend unit
  test**.
- A route's behaviour, status code, or query is covered by a **backend integration test**.
- How a component renders or behaves on interaction is covered by a **frontend component test**.
- Routing, authentication, or anything that only breaks in a real browser is covered by an
  **end-to-end test**.

Covering the same change at more than one layer is normal. The layers complement each other rather
than replace each other.

## Running tests

### Make

From the repo root:

```bash
make help              # list every target
make test-infra        # start Postgres + Redis on the test ports
make test-infra-down   # stop them
make test              # backend + frontend suites
make test-be           # backend only
make test-fe           # frontend only
make test-e2e          # Playwright, against a real stack
make lint              # lint and typecheck both projects
make lint-be           # backend only
make lint-fe           # frontend only
```

`make test` does not include the end-to-end suite, which needs Docker and takes several minutes.

### Backend

```bash
cd server

uv run pytest                              # everything
uv run pytest -m smoke                     # boot and infrastructure check
uv run pytest -m "not slow"                # what the PR path runs
uv run pytest -m integration               # one marker
uv run pytest -m "integration or security" # markers combine
uv run pytest tests/security/              # one directory
uv run pytest tests/security/test_idor.py  # one file
uv run pytest -k "token and not refresh"   # one name pattern
uv run pytest -x                           # stop at the first failure
uv run pytest --lf                         # re-run only what failed last time
uv run pytest -v                           # one line per test
uv run pytest --cov=app --cov-report=term-missing -n auto   # with coverage
```

Available markers: `smoke`, `unit`, `integration`, `security`, `migration`, `slow`.

Two of these are registered but not currently used by any test. `slow` exists so that a slow test
can be added later without changing the default command everywhere, and `xfail_leak` was declared
for a credential-leak test that was ultimately fixed outright rather than left failing. Since
`addopts` includes `--strict-markers`, an unknown marker name is an error rather than a silent
no-op, so neither can be mistyped into existence.

### Frontend

```bash
cd client

npm test                    # watch mode: re-runs on save
npm run test:run            # single pass, what CI runs
npm run test:coverage       # single pass with a coverage report
npm run test:ui             # browser UI for browsing and debugging results

npx vitest run tests/unit/hooks/useChat.test.ts    # one file
npx vitest run -t "clears history"                 # one test by name
npx vitest run --project dom                       # one project
```

`npm test` watches and `npm run test:run` exits, so `test:run` is the safer choice in scripts and
CI.

### End-to-end

```bash
# Infrastructure first.
docker compose -f docker-compose.test.yml up -d

cd client
npm run test:e2e                                  # the whole suite
npm run test:e2e:report                           # open the HTML report afterwards
npx playwright test --config=e2e/playwright.config.ts e2e/specs/chat.spec.ts
npx playwright test --config=e2e/playwright.config.ts --headed      # watch it run
npx playwright test --config=e2e/playwright.config.ts --ui          # interactive runner
npx playwright test --config=e2e/playwright.config.ts --project=seed  # one project
```

`--headed` opens a real browser window so you can watch the test drive the app. For a test that only
fails in a full run, `--ui` gives you a timeline and a live DOM snapshot for each step.

### Linting

Test code is held to the same standard as application code, and in CI it is held to a stricter one —
see [Continuous integration](#continuous-integration). `make lint` runs both projects; the
individual commands are:

```bash
cd server && uv run ruff check tests/ && uv run ruff format --check tests/ && uv run mypy tests/ --follow-imports=silent
cd client && npx next typegen && npx tsc --noEmit && npx eslint tests/ e2e/ vitest.config.ts
```

`next typegen` runs first on the client because `next-env.d.ts` is gitignored. It carries
the `next/image-types/global` reference that declares the module types for asset imports,
so on a fresh checkout `tsc` reports `TS2307` for every `import x from "./y.png"` until it
has been generated.

Python is formatted with **ruff** at a line length of 100; TypeScript follows the **Prettier**
settings in `.zed/settings.json`. Matching the surrounding style is preferable to introducing a new
formatter.

## Backend suite

`server/tests/`, run by pytest.

### Layout

Directories map to markers, so the layout doubles as the test taxonomy:

```
tests/
├── conftest.py                    # environment bootstrap, shared fixtures
├── factories.py                   # helpers that build rows (users, repos, files)
├── helpers.py                     # pure functions: authenticate(), xfail markers
├── fixtures/
│   ├── sample_repo.py             # an in-memory repo used by the ingest tests
│   ├── openai_stub.py             # the deterministic OpenAI fake
│   └── golden/                    # golden files and their comparison helper
├── smoke/                         # marker: smoke
├── unit/                          # marker: unit
│   ├── core/                      # security primitives (password hashing, JWTs)
│   └── services/                  # parser, import resolver, criticality, git analyzer
├── integration/                   # marker: integration
│   ├── api/                       # one module per router
│   ├── tasks/                     # the Celery ingestion pipeline
│   └── ws/                        # the ingest WebSocket
├── security/                      # marker: security
└── migrations/                    # marker: migration
```

Each test module declares its marker at the top:

```python
pytestmark = pytest.mark.integration
```

### What each layer covers

**Smoke** confirms the world is ready to be tested: Postgres reachable, `pgvector` installed, Redis
reachable, `/healthz` responding, the app booting. It makes no claims about behaviour. When
something is wrong at a fundamental level, this suite says so in seconds rather than through a long
list of confusing failures.

**Unit** covers services in isolation, with their dependencies faked:

- `test_parser.py` — tree-sitter AST parsing to symbols, including the symbol kinds that go missing
  if the parse is wrong.
- `test_import_resolver.py` — turning an import specifier into a repo-relative path stem.
- `test_dependency_resolver.py` — matching imports to files and inserting edges.
- `test_criticality.py` — the critical/caution/safe scoring.
- `test_git_analyzer.py` — `git log --numstat` parsing and ownership aggregation.
- `test_security.py` — bcrypt-over-SHA-256 password hashing, JWT creation and decoding.
- `test_publish.py` — the best-effort Redis log publisher.

**Integration** runs a real FastAPI app against a real database, with external HTTP faked:

- `integration/api/` — one module per router: auth, chat, github proxy, glossary, graph, guide,
  ownership, repository, stats. These assert status codes, response shapes, ordering, caps, and
  per-user isolation.
- `integration/tasks/test_ingest_task.py` — the whole ingestion pipeline, run eagerly rather than
  through a worker so a test can assert what the pipeline persisted.
- `integration/ws/test_ingest_ws.py` — the ingest WebSocket: the handshake, what it relays, what it
  refuses, and when it closes.

**Security** is a suite of its own rather than assertions spread through the others, so the security
posture can be reviewed as a whole:

- `test_idor.py` — every repository-scoped route, called by a user who does not own the repository.
  It is table-driven over a list of routes, so a new route added without an entry is a visible
  omission rather than a silent gap.
- `test_every_repo_route_is_covered.py` — keeps that table complete by walking the app's own route
  table and comparing it against the list.
- `test_middleware_auth.py` — the public-path bypass surface, unauthenticated access, and how the
  middleware handles malformed tokens.
- `test_cookie_security.py` — the session cookie's attributes, and that secrets are not serialised
  to the browser.
- `test_input_hardening.py` — hostile input to free-text and paginated parameters.
- `test_github_proxy_abuse.py` — the GitHub proxy used as an open relay or a timeout amplifier, and
  the upstream failures it should map rather than propagate.

**Migration** covers the Alembic chain: that it builds the schema it claims to, and that a
downgrade/upgrade round trip is clean. These run against the real database, which is why the test
database is disposable.

### Fixtures

Defined in `conftest.py` unless noted.

| Fixture | Provides |
|---|---|
| `client` | An HTTP client talking to the app in-process. No server is started. |
| `app` | The FastAPI application with its database dependency pointed at the test session. |
| `db_session` | An async database session whose work is rolled back. |
| `engine` | The async engine, for tests that need to bypass the session. |
| `redis_client` | An async Redis client on the test instance. |
| `migrated_db` | Session-scoped; brings the test database to head before anything runs. |

And from `helpers.py`, used as plain functions rather than fixtures:

| Helper | Purpose |
|---|---|
| `authenticate(client, user)` | Writes a valid session cookie for `user` onto the client. |
| `random_uuid()` | A UUID guaranteed not to match anything a test created. |

`authenticate` writes the cookie directly rather than going through `/login`. That keeps every other
suite from depending on the login route, which is what the auth tests exist to check.

### The rollback session

`db_session` is what makes the backend suite safe to run in any order. It opens a connection,
begins a transaction, and binds a session to it with `join_transaction_mode="create_savepoint"`.
Application code can call `commit()` freely, but that only releases a savepoint — the outer
transaction is never committed and the fixture rolls it back on teardown.

The practical effect is that tests cannot see each other's rows: a test can insert a user, commit,
assert, and leave, and the next test starts with no trace of it. Combined with `pytest-randomly`,
which shuffles test order on every run, this surfaces tests that have come to depend on what ran
before them.

A few tests genuinely need rows that outlive their own session — the ones that shell out to a
separate process. Those commit for real, and they are why `helpers.py` provides
`committed_repo_number_base`: committing tests share the database across processes, so each xdist
worker takes its own band of values to avoid a `UniqueViolation` that would otherwise appear only
when two workers happened to be scheduled at the same moment.

### Factories

`tests/factories.py` builds rows: `make_user`, `make_repo`, `make_ingested_repo`, and others. They
fill in the fields a test does not care about so the test only states what it is actually about.

```python
user = await make_user(db_session)
repo, files = await make_ingested_repo(db_session, user, name="findme")
await authenticate(client, user)

response = await client.get(f"/api/v1/repository/{repo.repo_number}")
```

`make_repo` takes a `status` argument. Repository routes are gated on `status == "ready"`, so a test
that omits it will get a 409 from a route it expected to succeed.

### Mocking

**OpenAI** — `tests/fixtures/openai_stub.py` is a deterministic in-process fake, patched over the
`OpenAI` class. It reads the prompt and answers accordingly: the glossary gets definitions for the
symbols actually present, and the reading order gets annotations for the files actually in the
order. A stub returning a fixed list would let a wiring bug pass, because the persistence code would
still have something to store.

Its embedding vectors are derived from the input text rather than random, so the same chunk always
embeds to the same point. That determinism is what lets a retrieval test assert anything about
ordering.

**GitHub and other HTTP** — intercepted with `respx`, which patches at the transport layer, so no
test makes a real network call.

**Redis** — `fakeredis` where the real thing is unnecessary, and the real instance on 6380 where
pub/sub delivery is what is being asserted.

**The database is not mocked.** This is deliberate: a mocked database cannot report that a query is
wrong, that a constraint fires, or that a migration and a model disagree, and those are the kinds of
problems this suite is meant to catch.

### Golden files

`tests/fixtures/golden/` holds checked-in expected output, compared byte for byte by
`assert_matches_golden`, which raises an `AssertionError` containing a `difflib` unified diff on a
mismatch.

```python
assert_matches_golden("illume_export.txt", response.text, update_golden)
```

To regenerate after an intentional change:

```bash
cd server
uv run pytest tests/integration/api/test_repository_api.py --update-golden
git diff tests/fixtures/golden/          # review before committing
```

Volatile values are normalised before comparison — the exporter's `generated=` date becomes a fixed
placeholder — so the file does not change daily. Golden files suit output whose shape is the
feature, such as a report a user downloads and reads, where a reordered header is a real change and
ought to show up as a diff.

### Expected failures

`pytest.xfail(strict=True)` marks a test as expected to fail, and two properties make it useful
here:

1. The test asserts the **desired** behaviour rather than the current one, so it reads as a written
   record of a bug: this should work, and it does not.
2. `strict=True` makes it report as a failure when the bug is fixed. An unexpectedly passing test
   shows as `XPASS(strict)`, which cannot quietly turn into a passing test that no longer means
   anything — fixing the bug means removing the marker.

Shared markers live in `helpers.py` so that every test blocked by the same defect carries the same
explanation. The marker names describe the cause — see
[Known unfixed defects](#known-unfixed-defects).

### Two traps worth knowing

**`AfterValidator` is dropped on query parameters unless it sits in the same annotation.** In
`app/api/validation.py`, a validator carried by a type alias used alongside a separate `Query(...)`
default is silently ignored: no error, no warning, the validation simply does not run. Keeping the
validator and the `Query(...)` inside one `Annotated` avoids this. The module docstring explains it,
and there is a test asserting that control characters are rejected, because the failure mode is
otherwise invisible.

**tree-sitter is error-tolerant.** A file full of invalid syntax still produces a partial parse, so
a syntax-error fixture does not exercise the code path that handles an unparseable file. `parse_file`
returns `None` only for an unsupported extension, an unreadable file, or a notebook whose JSON will
not load — which is why the ingest fixture uses a corrupt `.ipynb`.

## Frontend suite

`client/tests/` (unit) and `client/src/**/__tests__/` (components), run by Vitest.

### Two projects, split by environment

`vitest.config.ts` defines two projects, split by environment rather than by directory:

| Project | Environment | Covers |
|---|---|---|
| `node` | `node` | API clients, `utils/`, `types/` validators, the auth middleware (`proxy.ts`) |
| `dom` | `happy-dom` | Hooks, `lib/use-toast`, and every component test |

The DOM environment is noticeably slower, and most of the suite does not need it. The split has one
consequence worth remembering: importing a component under the `node` environment fails with a
`document is not defined` error rather than a clear message. Colocating a new component test under
`src/**/__tests__/` puts it in the `dom` project automatically, since that path is in the project's
include list.

### What is covered

- `tests/unit/api/` — the server-side API clients: URL, method, `credentials: "include"`, typed
  mapping of the response, and the error mapping for 401/404/500 and for a 204 with an empty body.
- `tests/unit/hooks/` — `useChat`, `useGitGraph`, `useGlossarySearch`, `useLoginForm`, `useLogout`,
  `useRepoForm`, `useSignupForm`.
- `tests/unit/types/validators.test.ts` — the form schemas.
- `tests/unit/proxy.test.ts` — the middleware auth gate.
- `tests/unit/utils/timeAgo.test.ts` and `tests/unit/lib/use-toast.test.ts`.
- `src/components/__tests__/` and `src/components/ui/__tests__/` — components, plus two mount tests
  (`graph-client-mount`, `background-graph-mount`) confirming the WebGL components can initialise at
  all. Those mock `react-force-graph-3d`, since there is no WebGL context under `happy-dom`.

### Network mocking

MSW (`tests/msw/`) intercepts at the network layer, so the code under test makes an ordinary `fetch`
and does not know it is being faked.

It runs with **`onUnhandledRequest: "error"`**, which means a request no handler covers is a failure
rather than a pass-through to the real network. Without it, a test that forgot a handler would make
a real request to `localhost:8000` and the resulting error would be about a connection rather than a
missing mock. One consequence is that adding a new API call to a component will break existing tests
until a handler is registered, which is the intended trade.

### Test setup

`tests/setup.ts` runs before every test in both projects. Five things it does are worth knowing
about:

1. **Raises `waitFor`'s timeout to 3000 ms.** A full-suite run executes files in parallel, and tests
   waiting for an `IntersectionObserver` callback and then an MSW round trip were observed missing
   the 1 s default by around 85 ms under that load — passing alone and failing in the full run. It
   stays below Vitest's 5 s `testTimeout`, since a wait longer than the test's own budget cannot
   report which assertion was unsatisfied.

2. **Patches `Animation.prototype.cancel`.** `cancel()` rejects the animation's `finished` promise
   with an `AbortError`, and framer-motion cancels animations during unmount without attaching a
   handler, so each motion-bearing component that unmounts leaves an unhandled rejection behind.
   Vitest reports those at the end of a run, and a genuine unhandled rejection in product code would
   look the same. Keeping the suppression in one place avoids repeating it in each test.

3. **Sets `NEXT_PUBLIC_BACKEND_URL`.** Vitest loads `.env` into `import.meta.env` but exposes only
   `VITE_`-prefixed names there and leaves `process.env` alone, so a `NEXT_PUBLIC_*` variable is
   undefined in tests even though it is set for `next dev` and `next build`. Without this, clients
   build requests to `undefined/api/v1/...`.

4. **Mocks `next/image`.** It cannot render outside a Next.js build, since it calls `getImgProps`,
   which throws under a plain Vite transform.

5. **Runs `cleanup()` after every test in both projects**, unconditionally. Guarding it behind a
   check for `document` would quietly stop unmounting if the environment were ever misconfigured.

### Optimistic UI

Several client actions — send, delete, clear — update local state before the request and do not roll
back on failure. Tests for those assert the optimistic update and the post-failure state separately,
since "the UI updated" and "the request succeeded" are different claims, and only one of them is
about the server.

## End-to-end suite

`client/e2e/`, run by Playwright. It is the only layer that uses a real browser.

### What it runs against

The suites above prove a unit or a route in isolation. This one catches a broken server component, a
route that 404s, a cookie that does not survive a redirect, or WebGL failing to initialise in a
container without a GPU.

It therefore runs against a real stack: migrated Postgres, real Redis, the actual FastAPI app, and a
production Next build (`next build && next start` rather than `next dev`). The only thing faked is
OpenAI.

### The three web servers

Playwright starts these itself and waits for each to answer before continuing. Their `cwd` is
resolved from the config file's directory rather than your shell's.

| Port | Service |
|---|---|
| 8099 | `server/scripts/openai_stub_server.py` — a real HTTP server speaking the OpenAI wire format |
| 8000 | The FastAPI app, against the **test** database (5433) and Redis (6380) |
| 3000 | The Next.js client, served from a production build |

There is deliberately no Celery worker. Nothing in these specs waits for an ingestion to complete;
the seeded repository is inserted directly by the seed script, and the pipeline itself is covered by
the backend's eager Celery tests.

The OpenAI seam is the `OPENAI_BASE_URL` environment variable, which the SDK reads — pointing it at
the stub redirects every LLM call the API makes, with no code change, so an end-to-end run never
makes a billed call.

The stub returns one shared constant vector for every embedding. Retrieval filters candidates on
`cosine_distance < 0.7`, and two unrelated 1536-dimension vectors are near-orthogonal, so a
text-derived query vector would sit at distance ~1.0 from every seeded chunk — nothing would survive
the filter, `answer_question` would return its canned "no relevant code" answer without calling the
model, and the chat path would be unreachable. One shared value gives distance 0.

### Project dependencies

Three Playwright projects, chained:

```
seed  →  auth  →  chromium
```

- **`seed`** runs `server/scripts/seed_e2e.py` against the listening API. It is a test rather than a
  `globalSetup` because it needs the API to be up, and Playwright guarantees a dependency project
  runs after every web server is healthy. It registers a user, inserts two ingested repositories,
  and writes `.auth/seed.json`.
- **`auth`** signs in once through the real login form and writes the cookie state to
  `.auth/user.json`.
- **`chromium`** holds the specs, all reusing that stored session.

### Seeded repositories

| Name | Contract |
|---|---|
| `seed-repo` | The repository every browsing spec reads. Nothing mutates it. |
| `reingest-me` | The repository the re-ingest spec is allowed to destroy. |

Specs read their identifiers from the seed artifact through `readSeed()` and `repoNamed()` rather
than hardcoding them, since `repo_number` is assigned by a counter and would otherwise need keeping
in sync by hand in two languages.

Reading the seed inside `test.beforeEach` rather than at module scope matters. Playwright loads
every spec file to build the test list *before* any project runs, so a module-scope read of
`.auth/seed.json` happens before the `seed` project has created it and fails on a clean checkout —
while appearing to work locally, where the artifact survives from a previous run. Three specs in
this suite previously had that shape.

```ts
let repo: SeededRepo;
let home: string;

test.beforeEach(() => {
  repo = repoNamed(readSeed(), REINGEST_REPO_NAME);
  home = `/repo/${repo.repo_num}`;
});
```

### Configuration

Set in `e2e/playwright.config.ts` and `e2e/env.ts`.

- **`workers: 1`, `fullyParallel: false`.** The seeded database is shared and `reingest.spec.ts`
  mutates a repository, so the specs cannot run concurrently. Re-ingest targets a repository of its
  own, so correctness does not depend on file order, but running serially keeps a failure easier to
  read.
- **`retries: 2`**, unconditionally rather than only in CI. A test that fails and then passes on
  retry is reported as flaky, which is worth noticing rather than ignoring.
- **`timeout: 60_000`** per test and **`expect: { timeout: 10_000 }`** per assertion.
- **Ports are overridable** with `E2E_CLIENT_PORT`, `E2E_API_PORT`, and `E2E_STUB_PORT`, so a run can
  coexist with a development stack on the default ports.
- **`API_URL` uses `localhost` rather than `127.0.0.1`.** The API sets its session cookie with
  `Domain=localhost`, so a browser request to `127.0.0.1` would be a different host and the cookie
  would not be sent. The spelling has to match across the browser, the CORS allow-list, and the
  cookie domain; when it does not, the symptom is a login that silently does not persist.
- **SwiftShader launch flags** (`--use-gl=angle --use-angle=swiftshader
  --enable-unsafe-swiftshader --disable-gpu-sandbox`) give headless Chromium a software WebGL
  rasteriser, without which the 3D graph tests fail in a container without a GPU.

### Artifacts

Two artifact directories, and they resolve by different rules:

| Artifact | Location | Resolved relative to |
|---|---|---|
| HTML report | `client/playwright-report/` | the shell's working directory |
| Traces, screenshots, videos | `client/e2e/test-results/` | the config file |

Neither is a typo. The config sets `outputDir: "test-results"`, which Playwright resolves against
the config file at `e2e/playwright.config.ts`, giving `e2e/test-results`. The HTML reporter's
`outputFolder` defaults to `playwright-report` and resolves against the directory Playwright was
invoked from — `client/`, since that is where `npm run test:e2e` runs.

So the report is opened from `client/`:

```bash
cd client
npm run test:e2e:report
# or explicitly:
npx playwright show-report playwright-report
```

Run from the repo root, `npx` will look for a second copy of Playwright in the registry and then
report that no report exists. Both symptoms come from the same cause.

Traces open directly:

```bash
npx playwright show-trace e2e/test-results/<test-name>/trace.zip
```

### Video, screenshots, and traces

By default, artifacts are recorded only for tests that fail:

```ts
use: {
  trace: "retain-on-failure",
  screenshot: "only-on-failure",
  video: "retain-on-failure",
},
```

After a green run there is therefore nothing to look at, and the report will contain no attachments.
This is the intended behaviour rather than a broken report: keeping video for 45 passing tests would
mean storing seven minutes of footage per CI run.

To capture artifacts anyway, override on the command line, where flags take precedence over the
config:

```bash
# Trace: a scrubbable timeline with DOM snapshots per step, network calls, console
# output, and the locator each action resolved to.
npx playwright test --config=e2e/playwright.config.ts e2e/specs/chat.spec.ts --trace=on

# Video and screenshots, for when the pixels are what matters.
npx playwright test --config=e2e/playwright.config.ts e2e/specs/chat.spec.ts --video=on --screenshot=on
```

The accepted values for all three options:

| Value | Behaviour |
|---|---|
| `off` | Never record. |
| `on` | Always record, pass or fail. |
| `retain-on-failure` | Record always, delete on success. (Traces and video.) |
| `only-on-failure` | Record only when the test fails. (Screenshots.) |
| `on-first-retry` | Record only when a test is being retried. A useful middle ground for CI. |

When debugging, `--trace=on` tends to be more informative than `--video=on`: video shows that
something went wrong, while a trace shows which locator resolved to what, the DOM at that moment,
and the request that came back.

Applying an artifact flag to the whole suite is expensive, so filtering to one spec first is worth
doing. A file filter still runs the `seed` and `auth` dependencies, so the single spec runs against
a properly seeded database.

### Specs

| Spec | Covers |
|---|---|
| `smoke.spec.ts` | The app loads, key routes respond, no console errors on boot. |
| `auth.spec.ts` | Login, logout, the middleware redirect gate, protected routes. |
| `seeded-browse.spec.ts` | Browsing the seeded repository: dashboard, file tree, glossary, graph, ownership, reading order. |
| `chat.spec.ts` | The RAG chat path end to end, including citations. |
| `reingest.spec.ts` | Re-ingesting a repository, and that the UI reflects it. |

## Coverage

Both suites measure coverage and enforce a committed floor.

| Suite | Floor file | Floor | Measured |
|---|---|---|---|
| Backend | `server/.coverage-floor` | 80 | 81.61 |
| Frontend | `client/.coverage-floor` | 62 | — (lines) |

CI fails if measured coverage drops below the floor. When a change raises coverage meaningfully,
raising the floor in the same commit lets a reviewer see the change as deliberate.

There is no absolute target. The floor only moves up, and it moves once someone has earned the right
to move it — coverage measures which lines ran, not whether the behaviour was actually checked, so
raising it through tests that assert little is not usually worth the effort.

The backend measures statement coverage over `app/`, excluding `alembic/`. The frontend measures
line coverage over `src/**/*.{ts,tsx}`, excluding type declarations, the test files themselves, and
the route-level `loading.tsx` and `error.tsx` files, which hold no logic.

```bash
cd server && uv run pytest --cov=app --cov-report=term-missing -n auto
cd client && npm run test:coverage
```

`--cov-report=term-missing` prints uncovered line numbers, which is often more useful than the
percentage on its own.

## Continuous integration

`.github/workflows/ci.yml` defines five jobs.

| Job | Runs on | Blocks a merge |
|---|---|---|
| `backend-lint` | every PR and push | Partly — see below |
| `frontend-lint` | every PR and push | Partly |
| `backend-tests` | every PR and push | Yes |
| `frontend-tests` | every PR and push | Yes |
| `e2e-nightly` | nightly at 03:17 UTC, and on push to `main` | No |

### Lint is split

The long-standing application code does not currently pass ruff or mypy cleanly, while the test code
does. Rather than switching the checks off, they are split:

- `tests/` is **blocking**, so new test code cannot introduce a problem.
- `app/` and `src/` are **report-only** (`continue-on-error: true`), so the existing debt stays
  visible in the log without failing the build.

A change that adds a lint error to `app/` can therefore still merge, but one that adds an error to
`tests/` cannot. The report-only job doubles as a list of what is outstanding for anyone touching
application code.

### End-to-end runs nightly

It needs a full Next production build, a migrated database, and a Chromium download, which is
several minutes of work for a signal that a PR review rarely turns on. It is gated on
`github.event_name == 'schedule' || (github.event_name == 'push' && github.ref == 'refs/heads/main')`;
the explicit `event_name` check is there because `on: push` fires for every branch, and this should
stay off the PR path.

When it fails, the report and traces are uploaded as artifacts — on failure only, for the same
reason the config records nothing on success.

CI's Postgres and Redis are GitHub service containers published on the same offset ports (5433,
6380) that `docker-compose.test.yml` uses locally, so a machine that can run the suite locally can
run it in CI with no second set of credentials.

## Known unfixed defects

There is currently one known unfixed defect, recorded in the suite rather than in a separate
document so it cannot be forgotten.

### `repo_number` is never provisioned

Creating a repository is the first thing every user does, and it fails against any database built
from this repository's migrations.

The model declares `repo_number` as a database-generated identity
(`server/app/models/repository.py`):

```python
repo_number: Mapped[int] = mapped_column(Integer, Identity(), unique=True, nullable=False)
```

Because `Identity()` tells SQLAlchemy the database will supply the value, the ORM omits the column
from its INSERT. The database, however, has no identity and no default on that column: it is
`NOT NULL` with nothing to fill it. The migration that was meant to make that conversion,
`server/alembic/versions/1bae111890c6_modify_repo_number.py`, is empty — `pass` in both `upgrade()`
and `downgrade()`, with no `op.` calls.

Every INSERT that omits the column therefore fails:

```
IntegrityError: null value in column "repo_number" of relation "repositories"
                violates not-null constraint
```

So `POST /api/v1/repository` returns 500, and `PUT /{repo_id}/reingest` fails the same way, since it
re-inserts the row carrying a `repo_number` that is only ever `NULL`.

Two other revisions (`95fdf3002015`, `1882dcee3456`) are empty no-ops in the same way.

**How the suite accommodates it.** `make_repo` supplies `repo_number` explicitly, so the read,
update, and delete routes stay fully testable. Creation is different: six tests in
`tests/integration/api/test_repository_api.py` carry the `BLOCKED_BY_MISSING_REPO_NUMBER_IDENTITY`
marker, and one test in `tests/migrations/test_migrate.py` carries `EMPTY_MIGRATIONS`. All seven are
`xfail(strict=True)`.

**Fixing it** means a migration converting `repo_number` into a real identity, with a backfill for
any table where the column is already populated. Once that lands, those seven tests report
`XPASS(strict)`, which is a failure by design — the suite is indicating that the markers can now be
removed and the tests allowed to assert normally.

```bash
cd server
uv run pytest -rxX    # show the reasons for expected failures
```

### Why defects are recorded as tests

Recording a defect as a failing test rather than as a comment has three effects worth knowing about:

- The tests exercise the route's real behaviour, so when the schema is corrected they already cover
  it. Nothing needs writing afterwards.
- The defect cannot be forgotten, because it is visible in every run.
- Fixing the defect without updating the tests is not possible, since `strict=True` turns the fix
  into a failure until the markers are removed.

## Writing tests

### Backend unit test

1. Place it in `tests/unit/services/`, or `tests/unit/core/` for security primitives.
2. Add `pytestmark = pytest.mark.unit` at the top of the module.
3. Fake every external dependency. A unit test that needs Postgres is better placed as an
   integration test.

### Backend integration test

1. Place it in `tests/integration/api/`, in the module for the router under test.
2. Add `pytestmark = pytest.mark.integration`.
3. Build data with `tests/factories.py` and sign in with `await authenticate(client, user)`.
4. Assert on the response, and on the database where persistence is the point.

```python
pytestmark = pytest.mark.integration


async def test_lists_only_the_callers_repositories(self, client, db_session):
    mine = await make_user(db_session)
    theirs = await make_user(db_session)
    await make_repo(db_session, mine, name="mine")
    await make_repo(db_session, theirs, name="theirs")
    await authenticate(client, mine)

    response = await client.get(COLLECTION)

    assert response.status_code == 200
    assert [r["name"] for r in response.json()] == ["mine"]
```

A new repository-scoped route belongs in both the `test_idor.py` route table and the list in
`test_every_repo_route_is_covered.py`. The second test exists to fail when the first is forgotten.

### Frontend unit or component test

1. Pure logic goes in `tests/unit/`; check that the `node` project's include list covers it.
2. A component or hook is colocated in `src/**/__tests__/`, which puts it in the `dom` project.
3. Register MSW handlers for every request the test makes, since an unregistered request fails
   rather than passing through.
4. Use `findBy*` or `waitFor` for anything asynchronous rather than asserting immediately after an
   interaction that triggers a request.

### End-to-end spec

1. Add `e2e/specs/<name>.spec.ts`.
2. Read the seed inside `test.beforeEach`, not at module scope.
3. Use `seed-repo` for anything read-only. A spec that mutates a repository should use `reingest-me`
   or add a new seeded repository in `seed_e2e.py`.
4. Prefer role-based locators (`getByRole("button", { name: "Repository settings" })`) over CSS
   selectors or test IDs. They fail when the accessible name changes, which is usually a real
   regression, whereas a CSS selector fails when a class name changes, which usually is not.

### Conventions this suite follows

**Assert the specific thing.** `assert response.status_code == 200` together with
`assert response.text` establishes only that something was returned. Where the shape of the output
is the feature, a golden file captures it precisely.

**Make the negative case unable to pass vacuously.** A test asserting that two files land in the
same tier would also pass if neither file had any resolved imports, so it asserts the precondition
too (`fan_in >= 1`), and cannot go green for the wrong reason.

**Test names state the claim.** `test_cannot_delete_another_users_repository` rather than
`test_delete_2`, so a failure in CI is readable without opening the file.

**Prefer a table to a loop of near-identical tests.** `test_idor.py` is table-driven over every
repository-scoped route, with a companion test that fails if the table falls out of sync with the
app's route list. That is what keeps the coverage from quietly rotting.

**Treat a flaky test as a real problem.** Adding a retry or a sleep to make it pass tends to hide the
cause rather than fix it. The usual causes in this repo have been a race with a component's own
teardown and a test that depended on a value another test happened to leave behind.

## Troubleshooting

**`Test infrastructure is not reachable`**
Docker is not running, or the test stack is not up.

```bash
docker compose -f docker-compose.test.yml up -d
```

**Backend tests hang, or fail with a database error about a missing extension**
Something is not the `pgvector` image. Confirm with:

```bash
docker compose -f docker-compose.test.yml ps
```

**`another worker migrated it first` on the first run**
This is handled. Under xdist, `migrated_db` runs once per worker and several can race to migrate the
same database; losing that race is not a failure and the fixture treats "already at head" as
success. The run is still fine.

**A frontend test passes alone and fails in the full suite**
Usually a timeout under parallel load, or an MSW handler that another test's `resetHandlers` removed.
Check whether the failing assertion is a `waitFor`; the suite already raises the async timeout to
3000 ms for this reason, and raising it further is usually a less good fix than removing the wait.

**An end-to-end spec fails at collection on a clean checkout**
Something is reading `.auth/seed.json` at module scope. Moving it into `test.beforeEach` resolves it.
Playwright loads specs to build the test list before any project runs.

**`npx playwright show-report` reports that no report exists**
It is being run from the wrong directory. The report is at `client/playwright-report` and is opened
from `client/`. See [Artifacts](#artifacts).

**A green end-to-end run produced no video, screenshots, or traces**
This is expected: all three record only on failure. Pass `--trace=on` to override.

**WebGL errors in headless Chromium**
The SwiftShader flags in the config handle this. If the launch options have been changed, restoring
them resolves it.

**`document is not defined` in a frontend test**
The test imports a component but is running in the `node` project. Colocating it under
`src/**/__tests__/` puts it in the `dom` project.

**Coverage dropped below the floor**
Either add tests, or — where the drop genuinely follows from deleting code — lower the floor file in
the same commit and explain why. Lowering it quietly to make a build pass defeats the purpose of
having it.
