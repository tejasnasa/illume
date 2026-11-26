# API reference

This page lists every HTTP route, the WebSocket and the MCP endpoint the backend serves, with what each one does, how it identifies the repository, and the error codes it can return. The routes are defined in the sixteen routers in [`server/app/api/v1/`](../server/app/api/v1/), registered in [`server/app/main.py`](../server/app/main.py). The interactive OpenAPI page FastAPI generates at `/docs` lists the request and response models; this page explains the behaviour around them.

## Terms used on this page

- **`{repo_id}`**: a repository's UUID. Most repository routes use it.
- **`{repo_num}`**: a repository's integer `repo_number`. Exactly one route uses it: `GET /api/v1/repository/{repo_num}`, which the web routes call to turn `/repo/3` into a repository.
- **Session**: the JWT that identifies the caller. Browsers send it as the httponly `access_token` cookie; the mobile app sends it as `Authorization: Bearer`. See [authentication](security/auth.md).
- **Ready**: a repository whose `status` is `ready`. Several routes refuse anything else.
- **SSE**: server-sent events, a one-way stream of `event:` and `data:` lines over a normal HTTP response.

## Conventions

| Convention     | Rule                                                                                                                                                  |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| base path      | every route is under `/api/v1`, except `/healthz`, `/openapi.json`, `/docs` and `/mcp`                                                                |
| authentication | every route needs a session except the public paths below; a missing or invalid session gets **401** from `AuthMiddleware` before any handler runs    |
| ownership      | another user's repository returns **404**, never 403, so a caller cannot learn that it exists                                                         |
| validation     | a body or query that fails its Pydantic model gets **422** with FastAPI's standard error body                                                         |
| errors         | `{"detail": "..."}` with a readable message; the web client shows `detail` where it makes sense                                                       |
| caching        | none: responses carry no cache headers, and clients fetch with `cache: "no-store"`                                                                    |
| pagination     | `page` (from 1, capped by `PageNumber` in [`app/api/validation.py`](../server/app/api/validation.py)) and `page_size`, with a `total` in the response |
| versioning     | only `/v1`; a breaking change to a response breaks the web client, mobile app and MCP clients together                                                |

**Public paths** (from `public_paths` in [`app/middleware/auth.py`](../server/app/middleware/auth.py), matched with `startswith`): `/healthz`, `/api/v1/auth/login`, `/api/v1/auth/register`, `/api/v1/auth/logout`, `/api/v1/auth/github`, `/api/v1/auth/github/callback`, `/api/v1/contact`, `/api/v1/ws`, `/openapi.json`. `/mcp` bypasses the cookie check because it does its own bearer-token authentication. Prefix matching means any path that begins with a public prefix is also public; this is a [known issue](security/auth.md#known-security-issues).

## Repositories

Router [`repository.py`](../server/app/api/v1/repository.py), prefix `/api/v1/repository`.

| Method and path                                  | Does                                                                                                                                            | Success                           | Errors                                                                                                                                                                                                             |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `POST /api/v1/repository`                        | creates a repository from `github_url` (exactly `https://github.com/<owner>/<repo>`), optional `branch` and `commit_sha`, and queues the ingest | 202 with `repo_id` and `repo_num` | 402 when a keyless user has spent the three free ingestions; 422 for a URL on any other host                                                                                                                       |
| `GET /api/v1/repository`                         | lists the caller's repositories, newest first, with truncated summaries                                                                         | 200                               |                                                                                                                                                                                                                    |
| `GET /api/v1/repository/{repo_num}`              | one repository by its number                                                                                                                    | 200                               | 404                                                                                                                                                                                                                |
| `PUT /api/v1/repository/{repo_id}/reingest`      | deletes the row and every child row, recreates it with the same id and number, and queues a full ingest                                         | 202                               | 400 unless the status is `ready` or `failed`; 402 when the caller has no key of their own (re-ingest, sync and turning on auto-update are never free)                                                              |
| `PATCH /api/v1/repository/{repo_id}/auto-update` | turns auto-update on or off and sets `interval_hours`                                                                                           | 200                               | 422 unless the interval is 1, 3, 6, 12 or 24; 402 when turning it on without a key of the owner's own                                                                                                              |
| `POST /api/v1/repository/{repo_id}/sync`         | queues a sync now                                                                                                                               | 202                               | 402 without a key of the owner's own; 409 when auto-update is disabled by the deployment, when there is no ingested commit to compare with, or when a sync is already running; 503 if the task could not be queued |
| `DELETE /api/v1/repository/{repo_id}`            | deletes the repository and everything under it                                                                                                  | 204                               |                                                                                                                                                                                                                    |
| `GET /api/v1/repository/{repo_id}/export/illume` | the `.illume` text export, as a download                                                                                                        | 200 `text/plain`                  | 400 unless ready                                                                                                                                                                                                   |

See [ingestion](pipeline/ingestion.md#where-an-ingestion-starts), [auto-update](pipeline/sync.md) and [the export format](interfaces/illume-export.md).

## Repository data

All `GET`, all under `/api/v1/repository`, all read-only, all 404 for another user's repository.

| Path                               | Router                                                  | Returns                                                                                                                    | Notes                                                     |
| ---------------------------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `/{repo_id}/graph?level=file`      | [`graph.py`](../server/app/api/v1/graph.py)             | the file- or symbol-level dependency graph (`level=file` or `symbol`)                                                      | **409 unless ready**; 500 if the build fails; no node cap |
| `/{repo_id}/graph/thumbnail`       | `graph.py`                                              | a condensed file graph for a repository card's picture                                                                     |                                                           |
| `/{repo_id}/guide`                 | [`guide.py`](../server/app/api/v1/guide.py)             | the reading order (`position`, `file_path`, `annotation`, `fan_in`; the tier is dropped) and the architecture brief        | 404 when no guide exists yet                              |
| `/{repo_id}/stats`                 | [`stats.py`](../server/app/api/v1/stats.py)             | file, language, ownership and dependency totals                                                                            |                                                           |
| `/{repo_id}/activity?limit=6`      | [`activity.py`](../server/app/api/v1/activity.py)       | the latest merged pull requests and commits, newest first (`limit` 1 to 30)                                                |                                                           |
| `/{repo_id}/file?path=…&commits=3` | [`file_detail.py`](../server/app/api/v1/file_detail.py) | one file's symbols and its most recent commits (`commits` 0 to 20)                                                         | 404 for an unknown path                                   |
| `/{repo_id}/ownership`             | [`ownership.py`](../server/app/api/v1/ownership.py)     | per-file owners, contributors and bus factor, paginated, with an optional exact `file_path` filter (`page_size` up to 200) |                                                           |
| `/{repo_id}/ownership/silos`       | `ownership.py`                                          | files whose bus factor is one                                                                                              |                                                           |
| `/{repo_id}/glossary`              | [`glossary.py`](../server/app/api/v1/glossary.py)       | glossary entries, paginated (`page_size` up to 100), filterable by file path and by first letter (`#` for non-letters)     |                                                           |
| `/{repo_id}/glossary/search`       | `glossary.py`                                           | glossary entries matching a query (`page_size` up to 100)                                                                  |                                                           |

See [the dependency graph](graph/dependency-graph.md) and [git intelligence](pipeline/git-intelligence.md).

## Chat and conversations

| Method and path                                                             | Router                                                      | Does                                                                                   | Errors                                                                                                                                                                                                                                      |
| --------------------------------------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /api/v1/repository/{repo_id}/chat/stream`                             | [`agent.py`](../server/app/api/v1/agent.py)                 | answers with any preset, or `auto`, and streams the run as SSE; the web client's chat  | 400 when an agent preset's model cannot call tools; 402 without a usable key or free allowance (agent presets and `auto` need the caller's own key); 422 for overrides that do not fit the preset; 429 when the caller has no free run slot |
| `GET /api/v1/repository/{repo_id}/agent-runs?limit=20`                      | `agent.py`                                                  | the caller's runs on the repository, newest first (`limit` up to 100)                  |                                                                                                                                                                                                                                             |
| `POST /api/v1/repository/{repo_id}/chat`                                    | [`chat.py`](../server/app/api/v1/chat.py)                   | answers with the Classic pipeline and returns one JSON response; the mobile app's chat | 400 unless ready; 402 without a key or free allowance; 502 when the provider fails                                                                                                                                                          |
| `GET /api/v1/repository/{repo_id}/chat/history?conversation_id=…`           | `chat.py`                                                   | turns in chronological order, with their sources                                       |                                                                                                                                                                                                                                             |
| `GET /api/v1/repository/{repo_id}/chat/{message_id}/changes`                | `chat.py`                                                   | what changed in the repository since a stale answer was written                        | 404                                                                                                                                                                                                                                         |
| `DELETE /api/v1/repository/{repo_id}/chat/{message_id}`                     | `chat.py`                                                   | deletes one turn                                                                       | 404                                                                                                                                                                                                                                         |
| `DELETE /api/v1/repository/{repo_id}/chat`                                  | `chat.py`                                                   | deletes every conversation the caller has on the repository                            |                                                                                                                                                                                                                                             |
| `GET /api/v1/repository/{repo_id}/conversations`                            | [`conversations.py`](../server/app/api/v1/conversations.py) | the caller's conversations, most recently active first                                 |                                                                                                                                                                                                                                             |
| `POST /api/v1/repository/{repo_id}/conversations`                           | `conversations.py`                                          | creates an empty conversation                                                          | 201                                                                                                                                                                                                                                         |
| `PATCH /api/v1/repository/{repo_id}/conversations/{conversation_id}`        | `conversations.py`                                          | renames it                                                                             | 404                                                                                                                                                                                                                                         |
| `DELETE /api/v1/repository/{repo_id}/conversations/{conversation_id}`       | `conversations.py`                                          | deletes it and its turns                                                               | 404                                                                                                                                                                                                                                         |
| `GET /api/v1/repository/{repo_id}/conversations/{conversation_id}/messages` | `conversations.py`                                          | its turns in order                                                                     | 404                                                                                                                                                                                                                                         |

The stream's event names and payloads are in [the chat agent's events](retrieval/agent.md#events), and the request body (question, preset, conversation, overrides) in [chat](retrieval/chat.md). Questions are capped by `QuestionText` and replayed history by `HistoryContentText` in `validation.py`.

## Account

Router [`auth.py`](../server/app/api/v1/auth.py), prefix `/api/v1/auth`.

| Method and path                    | Does                                                                                            | Errors                                                                         |
| ---------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `POST /register`                   | creates an account and sets the session cookie                                                  | 201; 400 if the email is taken                                                 |
| `POST /login`                      | checks the password and sets the session cookie                                                 | 401                                                                            |
| `POST /logout`                     | clears the cookie                                                                               |                                                                                |
| `GET /me`                          | the signed-in user, free-tier counters and limits, whether a key is saved, and `mcp_enabled`    | 401                                                                            |
| `DELETE /me`                       | deletes the account and everything it owns; the body must repeat the account's email            | 204; 400 when the email does not match                                         |
| `GET /github`                      | redirects to GitHub's OAuth page                                                                | 302                                                                            |
| `GET /github/callback`             | finishes OAuth, signs in or links the GitHub account, stores the token encrypted, and redirects | 400 when GitHub refuses or returns no verified email                           |
| `GET /me/ai-credentials`           | the saved provider and model, never the key                                                     |                                                                                |
| `PUT /me/ai-credentials`           | saves a provider key after a live probe of the provider                                         | 422 for an unknown provider; 400 with the provider's name when the probe fails |
| `DELETE /me/ai-credentials`        | removes the saved key                                                                           |                                                                                |
| `GET /me/agent-settings`           | the default preset and agent options                                                            |                                                                                |
| `PUT /me/agent-settings`           | saves them                                                                                      | 422                                                                            |
| `GET /me/mcp-tokens`               | the caller's MCP tokens, without their secrets                                                  |                                                                                |
| `POST /me/mcp-tokens`              | creates a token and returns its plaintext once                                                  | 201; 409 at the limit of active tokens                                         |
| `DELETE /me/mcp-tokens/{token_id}` | revokes a token                                                                                 | 204                                                                            |

The GitHub callback, called with `X-Illume-Client: mobile` or an allow-listed deep-link `state`, returns the JWT in JSON or in the redirect instead of a cookie, with the 90-day mobile lifetime. See [authentication](security/auth.md) and [BYOK and encryption](security/byok-and-encryption.md).

## GitHub proxy

Router [`github_proxy.py`](../server/app/api/v1/github_proxy.py), prefix `/api/v1/github`. These call the GitHub REST API with the caller's stored token, so the browser never holds it. They feed the repository picker and its branch timeline.

| Method and path                                       | Does                                                             |
| ----------------------------------------------------- | ---------------------------------------------------------------- |
| `GET /repos?per_page=30&q=…`                          | the caller's GitHub repositories, newest first, filtered by name |
| `GET /repos/{owner}/{repo}/branches`                  | branches, with the default flagged                               |
| `GET /repos/{owner}/{repo}/commits?sha=…&per_page=40` | commits on a branch or from a SHA                                |
| `GET /repos/{owner}/{repo}/commits-multibranch`       | recent commits merged across up to five branches, newest first   |

Errors: 403 when no GitHub account is linked, 401 when the stored GitHub token has expired, 404 for a repository GitHub does not show the caller, 502 for an unexpected GitHub response and 504 on a timeout.

## Push notifications and contact

| Method and path             | Router                                          | Does                                                                                                                                            |
| --------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /api/v1/push/token`   | [`push.py`](../server/app/api/v1/push.py)       | registers or refreshes the calling device's Expo push token                                                                                     |
| `GET /api/v1/push/token`    | `push.py`                                       | whether a token is registered                                                                                                                   |
| `DELETE /api/v1/push/token` | `push.py`                                       | removes it                                                                                                                                      |
| `POST /api/v1/contact`      | [`contact.py`](../server/app/api/v1/contact.py) | emails a contact-form submission to the operator through Resend. Public. 503 when the contact variables are empty, 502 or 504 when Resend fails |

## The ingest WebSocket

`WS /api/v1/ws/ingest/{repo_id}` in [`ws.py`](../server/app/api/v1/ws.py) relays the ingest's progress frames. It accepts the socket first, then authenticates from the cookie or the `?token=` query parameter, and closes with code 1008 and a reason when the caller is not the owner. Frames are JSON with `event`, `message`, `stage` and `phase`. [WebSockets](interfaces/websockets.md) documents every frame.

## Health and schema

| Path                | Does                                                                                                                                                                                                         |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET /healthz`      | `{"status": "ok", "checks": {"redis": "ok"}}` with 200, or `"degraded"` with 503 naming the failing check. It does not probe Postgres ([why](testing/frontend-and-e2e.md#why-healthz-has-no-database-probe)) |
| `GET /openapi.json` | FastAPI's OpenAPI schema. Public                                                                                                                                                                             |
| `GET /docs`         | FastAPI's interactive page. Not a public path, so it needs a session cookie on the API's host                                                                                                                |

## The MCP endpoint

`/mcp` is a streamable-HTTP MCP server mounted inside the API. Clients authenticate with `Authorization: Bearer ilm_…`, a personal token created in Settings. It answers 401 with `WWW-Authenticate: Bearer` for a bad token, 404 everywhere when the `MCP_ENABLED` switch is off, and 413 for a body over 1 MiB. It also checks `Host` and `Origin`. It serves:

- **Account tools**: `whoami` and `list_repositories`.
- **Repository tools**: every agent tool except `finish`, each taking a `repo` argument.
- **`ask_illume`**: a full chat answer with citations.
- **Resources and prompts.**

[The MCP server](mcp/server.md) documents each one, the rate limits and who pays.

## Design trade-offs and limits

- **Mixed identifiers.** One route keys on `repo_num` and every other repository route on `repo_id`, so a client needs both.
- **No rate limiting on most routes.** Only the MCP endpoint, the agent's run slots and the free-tier counters limit request volume; login and register are unthrottled.
- **Prefix-matched public paths.** A new route under a public prefix is public by accident.
- **No pagination on the graph.** `GET /graph` returns every node and edge, so a very large repository produces a very large response.
- **Two chat endpoints.** `POST /chat` (Classic only, one JSON response) and `POST /chat/stream` (every preset, streamed) differ in what they can do; the mobile app uses the first.
- **Status codes are not uniform.** Re-ingesting a busy repository answers 400, while syncing a busy one answers 409.

## Related documentation

- [Authentication](security/auth.md): sessions, bearer tokens, MCP tokens.
- [WebSockets](interfaces/websockets.md): the ingest progress stream.
- [Chat](retrieval/chat.md): the two chat endpoints in depth.
- [The MCP server](mcp/server.md): the `/mcp` endpoint.
- [Add an endpoint](guides/add-an-endpoint.md): adding a route.
- [Data model](reference/data-model.md): the tables behind these responses.
