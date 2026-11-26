# Repository layout

This page is a map of the repository: what each top-level folder is, how the backend and the web client are organised inside, and where to look for a given concern. Illume is one repository holding five things that ship separately: the backend, the web client, the mobile app, a small MCP launcher, and the evaluation harness, which lives inside the backend.

## Terms used on this page

- **Service**: a module in `server/app/services/` holding the logic for one concern, with no HTTP or Celery code of its own.
- **Router**: a module in `server/app/api/v1/` holding one group of HTTP routes.
- **Task**: a Celery task in `server/app/tasks/`, run by the worker.
- **App Router**: Next.js's file-system routing, where each folder under `client/src/app/` is a URL segment.

## Top level

```text
illume/
├── server/                   FastAPI + Celery backend, Python 3.14, managed with uv
├── client/                   Next.js 16 web client, React 19, Tailwind 4
├── mobile/                   React Native / Expo app
├── mcp-local/                stdio launcher that proxies to the hosted MCP server
├── docs/                     this documentation, also served at /docs on the site
├── showcase/                 demo videos
├── .github/workflows/        ci.yml, deploy.yml, prod-smoke.yml
├── docker-compose.test.yml   Postgres + Redis for the test suites (5433 / 6380)
├── docker-compose.eval.yml   Postgres + Redis for the eval harness (5434 / 6381, persistent)
├── Makefile                  every day-to-day command
├── README.md                 the project's front page
└── CLAUDE.md                 guidance for AI coding assistants working in this repository
```

| Folder          | Deployed as                                            | Read                                         |
| --------------- | ------------------------------------------------------ | -------------------------------------------- |
| `server/`       | one Docker image, run as three containers on a droplet | [deployment](../operations/deployment.md)    |
| `client/`       | a Next.js site, deployed separately from the backend   | [frontend overview](../frontend/overview.md) |
| `mobile/`       | EAS builds of a development client and store builds    | [mobile app](../mobile/overview.md)          |
| `mcp-local/`    | a Python package users install and run locally         | [MCP server](../mcp/server.md)               |
| `server/evals/` | not deployed; run by hand against its own database     | [eval harness](../evals/harness.md)          |

## The backend

```text
server/
├── app/
│   ├── main.py               FastAPI app: middleware, routers, /healthz, the /mcp mount
│   ├── api/
│   │   ├── deps.py           get_current_user, get_repo_for_user
│   │   ├── validation.py     shared input types (NoControlCharacters, GitHubRepoUrl, ...)
│   │   └── v1/               one router per subject (16 routers)
│   ├── core/                 config, database engines, celery app, redis, crypto, security, health
│   ├── middleware/auth.py    AuthMiddleware: JWT cookie or bearer -> request.state.user_id
│   ├── models/               SQLAlchemy models, one table per module
│   ├── services/             the logic; see below
│   ├── tasks/                Celery tasks: ingest, sync, autoupdate, agent_retention, _parallel
│   ├── mcp/                  the MCP server: transport, auth, tools, resources, prompts, limits
│   └── scripts/clean.py      truncates every table (destructive)
├── alembic/                  migrations; env.py must import every model module
├── evals/                    the evaluation harness (python -m evals)
├── scripts/                  seed_e2e.py, openai_stub_server.py, probe_ai_provider.py, mcp_dev.py
├── tests/                    unit, integration, security, migrations, evals
├── Dockerfile                two-stage image used by the deploy
└── pyproject.toml            dependencies and the dev group
```

### Services by concern

| Concern                  | Modules in `server/app/services/`                                                                                                                                                                    |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| orchestration            | `pipeline.py` (`run_full_analysis`), `_stages.py`, `_stage_timer.py`, `_publish.py`, `_concurrency.py`                                                                                               |
| clone and cache          | `cloner.py`, `repo_cache.py`                                                                                                                                                                         |
| parsing and dependencies | `scanner.py`, `parser.py`, `docstrings.py`, `import_resolver.py`, `dependency_resolver.py`, `stack_detector.py`, `test_files.py`                                                                     |
| git history              | `git_analyzer.py`, `pr_fetcher.py`, `cochange.py`, `criticality.py`                                                                                                                                  |
| generation               | `glossary_builder.py`, `onboarding.py`, `onboarding_guide.py`, `architecture_brief.py`, `llm_config.py`, `llm_providers.py`, `tool_support.py`                                                       |
| index and chat           | `embedder.py`, `rag.py`, `retrieval/` (channels, fusion, rerankers, diversity), `agent/` (the tool-calling agent), `decisions/` (narrow yes/no and choice calls), `conversations.py`, `staleness.py` |
| graph                    | `graph_builder.py`, `file_graph.py`                                                                                                                                                                  |
| export                   | `illume_exporter.py`                                                                                                                                                                                 |
| accounts and billing     | `entitlements.py`, `mcp_tokens.py`, `push.py`, `mailer.py`                                                                                                                                           |
| GitHub                   | `github_http.py`, `github_files.py`                                                                                                                                                                  |
| observability            | `tracing.py`                                                                                                                                                                                         |

The async/sync split follows the caller: FastAPI routes use the async engine, Celery tasks and Alembic the sync one. Some services therefore exist in both flavours; `file_graph.py` exports `query_file_edges` and `query_file_edges_async`. [Architecture](../architecture.md#async-and-sync-split-by-caller) explains why.

### The evaluation harness

```text
server/evals/
├── __main__.py               the CLI entry point (python -m evals)
├── cli/                      corpus, mine, gold, run and judge command groups
├── corpus/                   the pinned repositories and their base commits
├── mining/                   questions mined from history
├── gold/                     gold answers, checks, the leak guard and the slice split
├── arms.py                   every arm and assert_arm_diffs
├── run/                      generation, judging, metering, pricing and budgets
├── metrics/                  answer, citations, cost, files list, retrieval, routing, trajectory
├── report/                   statistics, comparisons, wording rules, rendering
├── prereg/                   the design files written before each run
└── settings.py               the harness's own settings, isolated from the app's
```

## The web client

```text
client/
├── src/
│   ├── app/                  App Router routes: /, /login, /dashboard, /settings, /contact,
│   │                         /docs, /mobile (the Android download page), /dev/pipeline
│   │                         (a replay of the progress board), and /repo/[id] with
│   │                         chat, explorer, glossary, graph and settings
│   ├── api/                  "use server" reads that forward the session cookie
│   ├── actions/              "use server" mutations
│   ├── components/           pages' building blocks; chat/, docs/, ingest/, landing/, ui/
│   ├── hooks/                client hooks: useIngestStream, useAgentStream, useConversation, ...
│   ├── lib/                  docs.ts (the docs site), agent/ (presets), apiError, github
│   ├── utils/                pure helpers, such as ingestFlow.ts for the progress board
│   ├── types/                response types shared by fetchers and components
│   └── proxy.ts              the Next.js middleware auth gate, not a network proxy
├── tests/                    Vitest unit tests and MSW handlers
├── e2e/                      Playwright end-to-end suite
├── e2e-prod/                 Playwright smoke suite against the deployed site
└── next.config.ts
```

Three components with similar names do different things: `GraphClient.tsx` is the interactive 3D dependency graph, `GitGraph.tsx` is a 2D branch timeline for choosing a commit, and `BackgroundGraph.tsx` is decorative. [Frontend overview](../frontend/overview.md) covers them.

## The mobile app

```text
mobile/
├── src/
│   ├── app/                  Expo Router routes: (app)/, auth/, login, onboarding
│   ├── api/                  typed client using an Authorization: Bearer header
│   ├── components/, hooks/, lib/, theme/, types/, ui/
├── __tests__/                Jest tests
├── e2e/                      Maestro device flows (YAML)
├── app.json, eas.json        Expo and EAS build configuration
└── package.json
```

The mobile app shares no code with the web client by design. [Mobile app](../mobile/overview.md) explains the decision.

## Where to look for

| You want to change  | Start at                                                                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------------- |
| what an ingest does | `server/app/services/pipeline.py`, then [add a pipeline stage](../guides/add-a-pipeline-stage.md)         |
| how chat finds code | `server/app/services/retrieval/`, then [add a retrieval channel or arm](../guides/add-a-retrieval-arm.md) |
| the agent's tools   | `server/app/services/agent/tools/`, then [add an agent or MCP tool](../guides/add-an-mcp-tool.md)         |
| an HTTP route       | `server/app/api/v1/`, then [add an endpoint](../guides/add-an-endpoint.md)                                |
| a table             | `server/app/models/` and `server/alembic/`, then [change the schema](../guides/change-the-schema.md)      |
| background updates  | `server/app/tasks/sync.py` and `autoupdate.py`                                                            |
| tunable numbers     | [constants](../reference/constants.md), which lists each one and its file                                 |
| the graph's look    | `client/src/components/GraphClient.tsx`                                                                   |
| the deploy          | `.github/workflows/deploy.yml`                                                                            |

## Design trade-offs and limits

- **One repository, separate deploys.** Pushing to `main` redeploys the backend even for a documentation-only change; the web client deploys on its own.
- **No shared code between web and mobile.** Types and fetchers are written twice, so an API change is two client changes.
- **The harness lives in `server/`.** It imports the app's retrieval code directly, which keeps arms faithful to the product but means the harness's dependencies are in the backend's lock file.

## Related documentation

- [Architecture](../architecture.md): how the parts fit together.
- [Local setup](local-setup.md): running everything.
- [CLI reference](../reference/cli.md): every command.
