# Backend tests

The backend suite lives in `server/tests/` and runs under pytest against a real Postgres (with `pgvector`) and a real Redis on offset ports. Model APIs, GitHub and outbound email are faked; the database never is. This page covers the layout and markers, the environment bootstrap that keeps the suite off production, the fixtures and factories, the rollback session that isolates tests, the fakes, the recall check and golden files, the traps that have bitten the suite, and how to write a new test.

## Terms used on this page

- **Marker**: a pytest label (`@pytest.mark.integration`) used to select tests. This suite declares one per module with `pytestmark`.
- **xdist**: the `pytest-xdist` plugin, which runs tests in several worker processes (`-n auto`).
- **Savepoint**: a nested transaction inside a transaction. Committing it does not commit the outer transaction.
- **Eager task**: a Celery task run in the test process with `.apply()` instead of through a broker and worker.
- **Golden file**: a checked-in expected output that a test compares byte for byte.

## Layout and markers

```text
server/tests/
├── conftest.py            environment bootstrap and shared fixtures
├── factories.py           make_user, make_repo, make_ingested_repo and others
├── helpers.py             authenticate, make_two_users, random_uuid
├── fixtures/
│   ├── openai_stub.py     the prompt-aware OpenAI fake
│   ├── sample_repo.py     a small repository the ingest tests clone
│   ├── retrieval.py       RETRIEVAL_FIXTURE, a 30-file repository, and 14 questions
│   ├── agent_run.py       ScriptedModel, a replaying model for the chat agent
│   ├── agent_stream.py    helpers for the agent's streaming endpoint
│   ├── agent_tools.py     helpers for the agent's tools
│   └── golden/            illume_export.txt, agent_event_schema.json, agent_tool_schemas.json
├── smoke/                 marker smoke
├── unit/                  marker unit: core/, mcp/, services/
├── integration/           marker integration
│   ├── api/               one module or more per router
│   ├── mcp/               the MCP server over its real transport
│   ├── services/          retrieval channels, the agent, the embedder, entitlements
│   ├── tasks/             ingest, sync, sweep, retention, parallelism
│   └── ws/                the ingest WebSocket
├── security/              marker security
├── migrations/            marker migration
├── evals/                 the eval harness tests (run as their own CI job)
└── tools/                 runnable helpers, not tests
```

| Marker        | Declared meaning (`server/pyproject.toml`)                | What lives there                                                            |
| ------------- | --------------------------------------------------------- | --------------------------------------------------------------------------- |
| `smoke`       | boots the app and proves the critical paths respond       | infrastructure reachable, `vector` installed, app boots, `/healthz`         |
| `unit`        | a single function or class in isolation, externals mocked | parser, resolvers, scorers, retrieval pieces, the agent's parts, MCP limits |
| `integration` | real FastAPI app plus real Postgres and Redis             | routes, tasks, channels, the MCP server, the WebSocket                      |
| `security`    | auth bypass, IDOR, injection, token leakage               | cross-user access, cookies, bearer tokens, hostile input                    |
| `migration`   | Alembic upgrade and round-trip correctness                | the revision chain and model/schema drift                                   |
| `slow`        | excluded from the default PR run                          | registered, used by no test today                                           |

`addopts = "-ra --strict-markers"`, so a misspelt marker is an error, not a silent no-op, and `-ra` prints a reason line for every skip and expected failure.

## Running the suite

```bash
cd server
uv run pytest                                # everything, including tests/evals
uv run pytest -n auto                        # in parallel, as CI does
uv run pytest -m smoke                       # is the test stack up?
uv run pytest -m "integration or security"   # markers combine
uv run pytest tests/security/test_idor.py    # one file
uv run pytest -k "token and not refresh"     # a name pattern
uv run pytest -x --lf                        # stop at the first failure, rerun last failures
uv run pytest -p no:randomly                 # fixed order, for chasing an order dependency
uv run pytest --cov=app --cov-report=term-missing -n auto
AI_API_KEY= OPENROUTER_API_KEY= uv run pytest -n auto   # what CI sees
```

`make test-be` runs `pytest -m "not slow"`, `make test-be-all` runs everything and `make test-be-one f=<path>` runs one path. None of the make targets blank the server keys; see [running the suite the way CI does](overview.md#running-the-backend-suite-the-way-ci-does).

CI runs `uv run pytest --cov=app --cov-report=json:coverage.json -n auto`, then `uv run pytest ../mcp-local/tests` on its own (the launcher tests start a real API and commit rows, so they never share a run with the main suite), then the coverage ratchet. The eval tests run in a separate job with `-n 2`.

## The environment bootstrap

`app/core/config.py` builds `settings` at import time, `app/core/database.py` creates both engines at module scope, and `app/core/celery.py` creates the Celery app on import. The first `import app.…` therefore fixes the database URLs for the whole process, and a fixture is too late to change them.

So [`tests/conftest.py`](../../server/tests/conftest.py) sets the environment at the very top of the module, before its first `app` import, which is why every import below that block carries `# noqa: E402`:

| Variable                                  | Test value                                                          |
| ----------------------------------------- | ------------------------------------------------------------------- |
| `DATABASE_URL`                            | `postgresql+asyncpg://illume:test@localhost:5433/illume_test`       |
| `SYNC_DATABASE_URL`                       | `postgresql://illume:test@localhost:5433/illume_test`               |
| `REDIS_URL`                               | `redis://localhost:6380/0`                                          |
| `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY` | fixed `test-…-not-for-production` strings                           |
| `OPENAI_API_KEY`, `AI_MODEL`              | `test-openai-key`, `gpt-4o-mini`                                    |
| `DOMAIN`                                  | `localhost`, a bare hostname because it becomes the cookie `Domain` |
| `RESEND_API_KEY`                          | a placeholder; the outbound call is intercepted                     |
| `DEEPEVAL_DISABLE_DOTENV`                 | `1`, so DeepEval does not load a developer's `.env` on import       |
| `LANGSMITH_TRACING`                       | `false`, so tracing does not wrap the fakes and upload runs         |

`pytest_configure` then asserts that every database and Redis URL contains `5433` or `6380`. An override that points elsewhere fails before a single test runs. Fields not listed here, such as `AI_API_KEY`, still come from `server/.env` when it exists, which is the one way a local run differs from CI.

The full list is in [the environment reference](../reference/environment.md#backend-tests).

> **`alembic upgrade head` from a shell is not the same thing.** `alembic/env.py` reads `SYNC_DATABASE_URL` from `server/.env`, which on a configured machine is production. Use `make migrate-test`, or just run pytest: the `migrated_db` fixture migrates the test database itself.

## Fixtures

| Fixture          | Scope   | Provides                                                             |
| ---------------- | ------- | -------------------------------------------------------------------- |
| `alembic_config` | session | an Alembic `Config` rooted at `server/`, targeting the test database |
| `migrated_db`    | session | the test database at head; runs once per xdist worker                |
| `engine`         | session | an async engine with `NullPool`                                      |
| `db_session`     | test    | an `AsyncSession` whose work is always rolled back                   |
| `app`            | test    | the FastAPI app with `get_async_db` overridden to yield `db_session` |
| `client`         | test    | an `httpx.AsyncClient` over `ASGITransport`, so no server is started |
| `redis_client`   | test    | an async client on the test Redis, for pub/sub assertions            |
| `update_golden`  | session | `True` when `--update-golden` was passed                             |

The MCP tests have their own in [`tests/integration/mcp/conftest.py`](../../server/tests/integration/mcp/conftest.py) (`mcp_app`, `mcp_client`, `mcp_token`, `mcp_user` and others), and the security suite imports them. They exist because the app-level `client` cannot drive `/mcp`: `ASGITransport` never runs the app's lifespan, so the global MCP session manager is not running, and the global server opens sessions from the real engine, outside the test transaction. Each test therefore builds its own server with `build_mcp`, bound to the test's connection and served behind the real `AuthMiddleware`.

### Why `NullPool`

pytest-asyncio gives each test its own event loop. A pooled asyncpg connection belongs to the loop that opened it and raises when another loop reuses it, so the engine does not pool.

### Why the migration fixture tolerates failure

Under xdist every worker runs `migrated_db`, and they race to migrate the same empty database. The loser's `upgrade` raises; the fixture then compares the current revision with the head and only re-raises if they differ. A brand-new database can still produce a scatter of unrelated errors on the very first run, which vanish on the next. CI avoids it by running `alembic upgrade head` as its own step first.

The fixture also patches `logging.config.fileConfig` for the duration of the upgrade. `alembic/env.py` calls `fileConfig`, whose default `disable_existing_loggers=True` disables every logger the session has already created, and every later `caplog` assertion then silently captures nothing.

## The rollback session

`db_session` is what lets the suite run in any order:

```mermaid
sequenceDiagram
  participant T as Test
  participant S as AsyncSession
  participant C as Connection
  T->>C: connect, BEGIN outer transaction
  T->>S: bind with create_savepoint
  T->>S: application code calls commit
  S->>C: RELEASE SAVEPOINT only
  T->>T: assertions see the rows
  T->>C: teardown ROLLBACK outer transaction
  Note over C: nothing the test wrote survives
```

The session is bound to a connection whose outer transaction is never committed, with `join_transaction_mode="create_savepoint"`. Application code may call `commit()` freely; that only releases a savepoint, and teardown rolls everything back. Combined with `pytest-randomly`, which reorders tests on every run, a test that leans on another's rows fails quickly rather than one day.

Tests that start a separate process (the eager ingest task opens its own sync session, the launcher tests start a real API) commit for real. They no longer need to coordinate `repo_number` values across workers, because the column is a database identity.

## Factories and helpers

[`tests/factories.py`](../../server/tests/factories.py) builds rows and fills in every field a test does not care about:

| Factory                                                | Builds                                                      |
| ------------------------------------------------------ | ----------------------------------------------------------- |
| `make_user`                                            | a user                                                      |
| `make_repo`                                            | a repository; pass `status="ready"` for routes gated on it  |
| `make_file`, `make_symbol`                             | a file, a symbol                                            |
| `make_dependency`                                      | a `Dependency` edge                                         |
| `make_glossary_entry`, `make_guide`, `make_code_owner` | generated and git-derived artefacts                         |
| `make_conversation`, `make_chat_message`               | chat history                                                |
| `make_embedding`                                       | an `Embedding` row                                          |
| `make_ingested_repo`                                   | a ready repository with files                               |
| `make_fully_ingested_repo`                             | a ready repository with files, symbols, edges and artefacts |

[`tests/helpers.py`](../../server/tests/helpers.py) holds plain functions, not fixtures, so a test can call them twice:

- `authenticate(client, user)` writes a valid `access_token` cookie for `user` onto the client. It deliberately does not go through `/login`, so no other suite depends on the login route the auth tests exist to check.
- `make_two_users(db)` returns two unrelated accounts for cross-user checks.
- `random_uuid()` returns an id that matches nothing.

```python
pytestmark = pytest.mark.integration


async def test_lists_only_the_callers_repositories(client, db_session):
    mine, theirs = await make_two_users(db_session)
    await make_repo(db_session, mine, name="mine", status="ready")
    await make_repo(db_session, theirs, name="theirs", status="ready")
    await authenticate(client, mine)

    response = await client.get("/api/v1/repository")

    assert response.status_code == 200
    assert [r["name"] for r in response.json()] == ["mine"]
```

## Fakes

### OpenAI and other model APIs

[`tests/fixtures/openai_stub.py`](../../server/tests/fixtures/openai_stub.py) defines `FakeOpenAI`, installed over the `OpenAI` class with `install(monkeypatch)`. It implements `responses.create` and `embeddings.create` and **reads the prompt**: a glossary prompt is answered with definitions for the symbols named in it, a reading-order prompt with annotations for the files in it. It also records how many calls are in flight at once, which is how [the parallelism tests](../../server/tests/integration/tasks/test_parallelism.py) prove the overlapped stages really overlap.

`deterministic_vector(text)` derives each embedding from its text, so the same chunk always embeds to the same point and ordering assertions are stable.

For the chat agent, [`tests/fixtures/agent_run.py`](../../server/tests/fixtures/agent_run.py) defines `ScriptedModel`, which replays fixed Responses API outputs one per model call and records every request verbatim. It streams the way the real client does (text deltas, then a final event built from the SDK's own `Response` type), so a test can assert both what the agent did and exactly what it sent.

### GitHub, Resend and other HTTP

`respx` intercepts at the HTTP transport, so no test reaches the network. The contact tests use it to stand in for Resend; the GitHub proxy and PR fetcher tests use it for the GitHub API.

### Redis

`fakeredis` where only storage matters (the MCP fixtures, rate limits), and the real instance on 6380 where pub/sub delivery is the point, as in [the WebSocket tests](../../server/tests/integration/ws/test_ingest_ws.py).

### Git

The ingest and sync tests use real `git`. [`tests/fixtures/sample_repo.py`](../../server/tests/fixtures/sample_repo.py) builds a small repository on disk, and the sync tests push to a real bare origin so `git ls-remote`, fetch and rewritten history behave exactly as in production.

## What each area covers

### Smoke

`tests/smoke/` checks that Postgres answers with the `vector` extension, that Redis answers, that the app boots and that `/healthz` responds. When the stack is down these fail with the command to start it rather than a connection traceback.

### Unit

Grouped under `unit/core/` (password hashing, JWTs, credential encryption), `unit/mcp/` (limits, tool definitions, transport security) and `unit/services/`, which covers, among others:

| Area                   | Modules                                                                                                                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Parsing and resolution | `test_parser.py`, `test_docstrings.py`, `test_import_resolver.py`, `test_dependency_resolver.py`, `test_test_files.py`                                                                      |
| Scoring and history    | `test_criticality.py`, `test_git_analyzer.py`, `test_dates.py`                                                                                                                              |
| Generation             | `test_onboarding.py`, `test_architecture_narrative.py`, `test_llm_config.py`, `test_llm_providers.py`, `test_generation_reasoning_kwargs.py`                                                |
| Retrieval              | `test_fusion.py`, `test_diversify.py`, `test_channel_registry.py`, `test_lexical_query.py`, `test_identifiers.py`, `test_query_variants.py`, `test_retrieval_config.py`, `test_rerank_*.py` |
| Decisions and routing  | `test_decider_*.py`, `test_decision_points.py`, `test_decisions_openrouter.py`                                                                                                              |
| The chat agent         | `test_agent_*.py`, `test_tool_registry.py`, `test_citations.py`, `test_citation_split.py`, `test_context_assembly.py`                                                                       |
| Plumbing               | `test_publish.py`, `test_stage_timer.py`, `test_stages.py`, `test_concurrency.py`, `test_repo_cache.py`, `test_tracing.py`, `test_credential_redaction.py`                                  |

`test_stages.py` is worth knowing: it parses every `stage(...)` call out of `app/` and asserts the set equals the `Stage` enum, so the stage-timer log and the WebSocket frames cannot drift apart. See [the WebSocket stages](../interfaces/websockets.md).

### Integration

- **`integration/api/`**: every router, asserting status codes, shapes, ordering, caps and per-user isolation, including the agent's streaming endpoint (`test_agent_stream_*.py`), free-tier limits, account deletion and the mobile GitHub callback.
- **`integration/tasks/`**: `test_ingest_task.py` runs `ingest_repository.apply(...)` eagerly over the sample repository and asserts what was persisted; `test_sync_task.py` covers sync against a real bare origin (equivalence with a fresh ingest, escalation on rewritten history or a large diff, failure isolation, the watermark split, reingest guards); `test_sweep_task.py` the due/not-due matrix and lease predicates; `test_sync_llm.py` that a no-change sync makes zero model calls; `test_byok_credential_threading.py` that a user's key reaches every overlapped thread.
- **`integration/services/`**: each retrieval channel against real tables (`test_channel_*.py`), the pipeline and rerankers, the embedder, the agent planner and tools, entitlements and encrypted credentials.
- **`integration/mcp/`**: the MCP server over its real Streamable HTTP transport: auth, mounting, the body limit and switch, every tool, resources and prompts.
- **`integration/ws/`**: the ingest WebSocket's handshake, relay, refusals and close.

### Security

A suite of its own so the security posture can be reviewed as a whole:

| Module                                | Checks                                                                                                                            |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `test_idor.py`                        | every repository-scoped route, called by a user who does not own the repository, table-driven                                     |
| `test_every_repo_route_is_covered.py` | walks the app's route table and fails if a repository route is missing from the IDOR table                                        |
| `test_middleware_auth.py`             | the public-path prefix surface, missing and malformed tokens                                                                      |
| `test_bearer_header.py`               | the `Authorization: Bearer` JWT path the mobile app uses                                                                          |
| `test_cookie_security.py`             | cookie attributes, and that secrets never serialise to the browser                                                                |
| `test_input_hardening.py`             | hostile free-text and pagination parameters                                                                                       |
| `test_github_proxy_abuse.py`          | the GitHub proxy as an open relay or timeout amplifier                                                                            |
| `test_contact_abuse.py`               | the contact form's limits                                                                                                         |
| `test_agent_stream_security.py`       | the agent endpoint's access rules                                                                                                 |
| `test_mcp_tokens_security.py`         | MCP token scoping, revocation and storage                                                                                         |
| `test_mcp_tool_inventory.py`          | every MCP tool either takes a required `repo` string or is on an allow-list, and the registered tools equal what the server lists |

A new repository-scoped route must be added to the IDOR table; the coverage test fails until it is.

### Migrations

[`tests/migrations/test_migrate.py`](../../server/tests/migrations/test_migrate.py) asserts the chain has exactly one head, is linear, reaches every revision from the head, has no empty revision, that `upgrade head` is idempotent, and that **the models match the migrated schema** (with a second test proving the drift check really inspects something). Further modules check individual data migrations, such as credential encryption and the conversations backfill. See [changing the schema](../guides/change-the-schema.md).

## The retrieval recall check

[`tests/integration/services/test_retrieval_recall.py`](../../server/tests/integration/services/test_retrieval_recall.py) seeds `RETRIEVAL_FIXTURE` from [`tests/fixtures/retrieval.py`](../../server/tests/fixtures/retrieval.py), a 30-file web API with a barrel file, co-change pairs, a bulk commit that must be ignored, a function too long to embed and a camelCase name, then runs 14 known-answer questions through the real pipeline with no API key. It asserts recall@10 per preset against floors that only move up:

| Preset       | Floor | Measured when set                                       |
| ------------ | ----- | ------------------------------------------------------- |
| `classic`    | 0.00  | 0/14; dense search is noise here                        |
| `hybrid`     | 0.60  | 9/14 = 0.643                                            |
| `structural` | 0.90  | 13/14 = 0.929; misses one question that needs a stemmer |

Dense retrieval is noise because the fake vectors are hashes of the text, which never land within the 0.7 distance cut. The check therefore guards the lexical, symbol, grep, graph and co-change channels and their fusion, not embedding quality. Query rewrites and the `jev` reranker need keys, so both degrade as they do in production without one. The fixture uses sparse vectors and fixed row ids: dense random vectors make each HNSW insert cost about 50 ms, and random ids make tie-breaking vary between runs.

To see which channel found what for one question (test database only):

```bash
cd server
uv run python -m tests.tools.retrieval_trace --list
uv run python -m tests.tools.retrieval_trace graph-direct --preset hybrid
```

The presets and channels are explained in [retrieval arms](../retrieval/retrieval-arms.md#presets).

## Golden files

`tests/fixtures/golden/` holds expected output compared byte for byte by `assert_matches_golden`, which raises with a unified diff on mismatch:

| File                      | Guards                                |
| ------------------------- | ------------------------------------- |
| `illume_export.txt`       | the `.illume` export format           |
| `agent_event_schema.json` | the agent's streamed event schema     |
| `agent_tool_schemas.json` | the JSON schemas of the agent's tools |

```bash
cd server
uv run pytest tests/integration/api/test_repository_api.py --update-golden
git diff tests/fixtures/golden/        # review before committing
```

Volatile values (the export's `generated=` date) are normalised first. Golden files suit output whose exact shape is the contract, where a reordered field is a real change.

## Traps

- **`AfterValidator` on a query parameter is dropped unless it sits in the same `Annotated` as the `Query(...)`.** A validator carried by a type alias next to a separate `Query` default silently never runs. [`app/api/validation.py`](../../server/app/api/validation.py) explains this, and a test asserts control characters are rejected because the failure is otherwise invisible.
- **tree-sitter is error-tolerant.** A file of invalid syntax still parses partially, so it does not exercise the unparseable-file path. `parse_file` returns `None` only for an unsupported extension, an unreadable file or a notebook whose JSON will not load, which is why the ingest fixture uses a corrupt `.ipynb`.
- **Criticality ordering is untestable at unit level.** The unit tests inject `git_last_modified` and `has_tests` directly, so they pass whether scoring runs before or after the git analyzer. Only the eager ingest test catches the order. See [criticality](../pipeline/git-intelligence.md#criticality).
- **Eager tasks commit.** A test that runs `ingest_repository.apply` writes real rows through its own sync session, outside the rollback session, and must clean up or use unique names.
- **A pooled connection from another loop raises.** Never cache an async engine or session across tests.

## Writing a test

1. Pick the directory by layer (see [which suite a change belongs in](overview.md#which-suite-a-change-belongs-in)) and add `pytestmark = pytest.mark.<marker>` at the top.
2. Build data with the factories and sign in with `await authenticate(client, user)`.
3. Assert the specific thing: the status code **and** the body, and the database where persistence is the point.
4. For a repository-scoped route, add it to the IDOR table.
5. For a model call, install `FakeOpenAI` or use `ScriptedModel`; never let a test reach a real provider.
6. Run `uv run ruff check tests/ && uv run ruff format --check tests/ && uv run mypy tests/ --follow-imports=silent`; CI blocks on all three.

## Design trade-offs and limits

- **Real infrastructure.** Docker is required, and the first run against an empty database can race.
- **Local runs differ from CI** while `server/.env` supplies server keys; blank them for a faithful run.
- **`slow` is unused.** `make test-be` and `make test-be-all` therefore run the same tests today.
- **The recall check cannot see dense retrieval.** Embedding regressions are found by the eval harness, not here.
- **The stub is hand-written.** A real provider behaving differently (a new field, a different error) is invisible until production.

## Related documentation

- [Testing overview](overview.md): every suite and when to use it.
- [Frontend and end-to-end tests](frontend-and-e2e.md): the browser-side suites.
- [The data model](../reference/data-model.md#migrations): the revisions the migration tests walk.
- [Retrieval arms](../retrieval/retrieval-arms.md): what the recall check guards.
- [Environment variables](../reference/environment.md#backend-tests): the full test environment.
