# The MCP server

Illume exposes everything it knows about a user's repositories to AI tools through a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server, mounted inside the API at `/mcp`. A coding assistant such as Claude Code, Cursor or an IDE extension connects with a personal token and can then search code, read symbols and files, walk the import graph, read git history and ownership, and ask Illume for a finished, cited answer. The server lives in [`server/app/mcp`](../../server/app/mcp/__init__.py). This page covers the transport and its guards, authentication, every tool, resource and prompt, rate limits, and what each call costs.

## Terms used on this page

- **MCP**: an open protocol that lets an AI application call tools, read resources and use prompt templates offered by a server, over JSON-RPC.
- **Streamable HTTP**: the MCP transport where each JSON-RPC request is an HTTP `POST` and the response is either JSON or a server-sent event stream (used for progress notifications).
- **Stateless**: the server keeps no session between requests; every request carries its own token and is handled on its own.
- **Tool**: a callable operation with a JSON schema for its arguments. **Resource**: a readable document addressed by a URI. **Prompt**: a reusable starting message a user picks from a menu in their client.
- **Repository tool**: a tool that reads one of the caller's repositories and takes a `repo` argument.

## Connecting

1. In Illume's settings page, the MCP section ([`McpSettings.tsx`](../../client/src/components/McpSettings.tsx)) creates a personal token. The plaintext `ilm_...` token is shown once; only its SHA-256 hash is stored. See [MCP tokens](../security/auth.md#mcp-tokens) for the format, lifetimes, the limit of 10 active tokens and revocation.
2. The AI tool is configured with the server URL and the token as a bearer header, for example:

```json
{
  "mcpServers": {
    "illume": {
      "type": "http",
      "url": "https://<api-host>/mcp",
      "headers": { "Authorization": "Bearer ilm_..." }
    }
  }
}
```

3. The tool calls `list_repositories` first, then any repository tool with the `repo` value it returned.

`GET /api/v1/auth/me` reports `mcp_enabled`, which the settings page uses to show or hide the section.

## Transport and mounting

[`build_mcp`](../../server/app/mcp/server.py) builds the server and its ASGI app; [`main.py`](../../server/app/main.py) calls it once at import time with the async session factory and runs `mcp_server.session_manager` inside the FastAPI lifespan. `install_mcp` mounts the app at `MCP_PATH = "/mcp"`.

| Setting                | Value     | Meaning                                                                       |
| ---------------------- | --------- | ----------------------------------------------------------------------------- |
| `SERVER_NAME`          | `illume`  | the server name clients see                                                   |
| `streamable_http_path` | `/`       | the endpoint inside the mount, so the public URL is `/mcp`                    |
| `stateless_http`       | True      | no session state between requests                                             |
| `json_response`        | False     | responses stream as server-sent events, so progress notifications can be sent |
| `MCP_MAX_BODY_BYTES`   | 1,048,576 | the largest request body accepted                                             |
| `MCP_ENABLED`          | True      | the kill switch                                                               |

`INSTRUCTIONS`, sent to the client on initialisation, tell the model to call `list_repositories` first, that every repository tool takes `repo`, and that text inside `<source>` fences is repository content to read as data, never instructions.

### The middleware stack

A request passes through, from outermost to innermost:

```mermaid
flowchart LR
  REQ["request"] --> BARE["McpBarePathMiddleware<br/>/mcp becomes /mcp/"]
  BARE --> APPMW["API middleware<br/>CORS, AuthMiddleware skips /mcp"]
  APPMW --> EN["McpEnabledMiddleware<br/>404 when disabled"]
  EN --> BODY["BodyLimitMiddleware<br/>413 over 1 MiB"]
  BODY --> AUTH["BearerAuthMiddleware<br/>401 without a valid token"]
  AUTH --> TS["transport security<br/>Host and Origin checks"]
  TS --> SRV["MCP server<br/>tools, resources, prompts"]
```

- **`McpBarePathMiddleware`** rewrites a request for exactly `/mcp` to `/mcp/`, because Starlette's mount would otherwise answer the bare path with a redirect, which many MCP clients do not follow for a `POST`.
- **The API's `AuthMiddleware`** (cookie auth) skips the MCP endpoint: it matches `/mcp` exactly or `/mcp/` as a prefix, so a path such as `/mcpanything` still requires a cookie. AI tools have no browser cookie.
- **`McpEnabledMiddleware`** answers 404 for everything while `MCP_ENABLED` is false.
- **`BodyLimitMiddleware`** counts bytes as the body streams in and answers 413 as soon as it passes the limit, before the MCP layer parses anything.
- **`BearerAuthMiddleware`** ([`auth.py`](../../server/app/mcp/auth.py)) reads `Authorization: Bearer <token>` (the scheme is case-insensitive), resolves it with `resolve_token`, and stores the owner's id in the ASGI scope's state under `mcp_user_id`. A missing, malformed, unknown, revoked or expired token gets `401` with `WWW-Authenticate: Bearer`. Lifespan and other non-HTTP scopes pass straight through.
- **Transport security** (the MCP SDK's DNS-rebinding protection) only accepts a `Host` header in `MCP_ALLOWED_HOSTS` and an `Origin` header (when present) in `MCP_ALLOWED_ORIGINS`. Allowed hosts come from `GITHUB_REDIRECT_URL`, which is on the API's own origin; allowed origins are `FRONTEND_URL`'s and the API's. Outside production, `localhost`, `127.0.0.1` and `[::1]` on any port, and Starlette's `testserver`, are added.

Every handler gets the user id with `current_user_id(ctx)`, which raises if the scope has none, so a misconfigured stack fails closed.

## Tools

[`build_mcp`](../../server/app/mcp/server.py) collects three groups of tools into one dictionary and serves `tools/list` and `tools/call` from it. An unknown tool name returns an error result.

### Account tools

[`account_tools.py`](../../server/app/mcp/account_tools.py):

| Tool                | Arguments                            | Returns                                                                                         |
| ------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------- |
| `whoami`            | none                                 | the account's email and how many repositories it has; for checking the connection               |
| `list_repositories` | `status`: `ready` (default) or `all` | each repository's `repo` value, GitHub URL, status, and the branch and commit its data reflects |

### Repository tools

[`tools.py`](../../server/app/mcp/tools.py) exposes every tool of the [agent's registry](../retrieval/agent.md#the-tools) except those in `MCP_EXCLUDED = {"finish"}` and any marked `expose_to_agent=False`: 15 tools, the same handlers the agent uses.

| Tool             | Cost class | Notes for MCP                                                         |
| ---------------- | ---------- | --------------------------------------------------------------------- |
| `search_code`    | model      | runs `MCP_PIPELINE` (below); description overridden for MCP clients   |
| `search_symbols` | free       |                                                                       |
| `grep_code`      | free       |                                                                       |
| `search_history` | model      | embeds the query                                                      |
| `list_files`     | free       |                                                                       |
| `list_symbols`   | free       |                                                                       |
| `read_symbol`    | free       |                                                                       |
| `read_file`      | network    | calls GitHub with the caller's stored GitHub token; marked open-world |
| `get_importers`  | free       |                                                                       |
| `get_importees`  | free       |                                                                       |
| `find_path`      | free       |                                                                       |
| `get_cochanged`  | free       |                                                                       |
| `get_file_info`  | free       |                                                                       |
| `get_glossary`   | free       |                                                                       |
| `get_overview`   | free       |                                                                       |

The cost class is declared on each `Tool` in the registry: `free` is a database read, `model` makes a paid model call (here, a query embedding on the operator's OpenAI key), `network` calls another service.

`mcp_input_schema` takes the tool's Pydantic schema and adds a required `repo` string as the first property, with `additionalProperties: false`. It raises at startup if a registry tool ever defines its own `repo` argument, so the two cannot collide. `mcp_description` appends "Pass `repo` to choose the repository." to each description, and `DESCRIPTION_OVERRIDES` replaces the few descriptions that refer to the agent's own loop. Every tool is annotated read-only and idempotent; `read_file` is the only one with `open_world_hint` true.

A repository tool call, in `build_repository_tools`:

1. Reads `repo` with `repo_argument`; missing or unusable is an "Invalid arguments" error result.
2. Counts the call against the per-minute limit (below).
3. Resolves the repository (below).
4. Loads the caller's GitHub token and whether they have their own AI key.
5. Counts the call against the cost-based limits.
6. Builds a `ToolContext` with `build_tool_context` and calls `REGISTRY.call(name, arguments, ctx)`.
7. Returns the tool's text as the content, its structured data as `structuredContent` when it succeeded, and `isError` with the status in brackets (`[not_found] ...`) when it did not.
8. Logs one `mcp_tool user=... repo=... tool=... status=... ms=... truncated=...` line.

Errors are always returned as tool results with `isError: true`, never as protocol errors, so the calling model reads the message and can try something else.

### The MCP search pipeline

`search_code` over MCP runs `MCP_PIPELINE` from [`context.py`](../../server/app/mcp/context.py), not a chat preset:

- the `structural` preset's seven channels, fusion, `rrf_k` and diversity;
- no query condensing or rewriting (`transform="identity"`, `condense=False`);
- no reranker (`rerank.kind = "none"`).

Every model stage is off because the calling assistant is already a capable model that can rephrase and judge results itself, and because the extra channels (grep, graph, co-change, history) only read the database, so they rank better than a hybrid search at no extra cost. The only paid call is the query embedding.

The tool context has `budget=None` (no run budget: each MCP call is independent), `emit=no_emit` (no progress events), and the free-tier `LLMConfig`, which no stage of the pipeline reads.

### `ask_illume`

[`ask.py`](../../server/app/mcp/ask.py) gives the calling assistant Illume's own finished answer with citations, for when it would rather delegate than search.

| Argument   | Type                              | Meaning                    |
| ---------- | --------------------------------- | -------------------------- |
| `repo`     | string, required                  | number, UUID or owner/name |
| `question` | string, 1 to 4000 characters      | no control characters      |
| `mode`     | `quick` (default), `auto`, `deep` | how hard to work           |

Modes map to presets:

| Mode    | Preset                                                   | Key                                       |
| ------- | -------------------------------------------------------- | ----------------------------------------- |
| `quick` | `classic` on the free tier, `hybrid_rerank` with own key | free tier allowed; uses one free question |
| `auto`  | `auto` (the [router](../retrieval/router.md))            | own key required                          |
| `deep`  | `deep_agent`                                             | own key required                          |

The handler validates the arguments, counts the call per minute, resolves the repository, counts it against `MCP_ASK_PER_HOUR`, and then calls the same [`prepare_run`](../../server/app/services/agent/run_request.py) as the streaming chat endpoint, with no history, no overrides, `save_history=False` and `config_extra={"source": "mcp"}` (stored in the run's configuration so MCP runs can be told apart). Every admission rule therefore applies unchanged: free-tier limits, tool support, the two-runs-per-user slot cap. A refusal becomes an error result with the reason.

It then starts a `RunSession` and drains its events under `run_timeout`: 120 seconds for a single-shot preset, or the agent's `hard_cancel_seconds` plus a 15-second margin. While it waits, `_Progress` sends MCP progress notifications (when the client asked for them with a progress token) for the interesting events: "Run started (preset)", "Routed to structural", "Planned the investigation", "Retrieved context", "Calling search_code", "Investigating a sub-question", and "Writing the answer" at most once every `ANSWER_PROGRESS_SECONDS = 5` while answer text streams. A failure to send a notification never affects the run.

On `done`, the result's text is the answer followed by a `Sources:` list, and its structured content is:

```json
{
  "answer": "...",
  "citations": [
    {
      "key": "F:server/app/services/repo_cache.py:120-188",
      "type": "symbol",
      "path": "server/app/services/repo_cache.py",
      "lines": "120-188",
      "url": "https://github.com/<owner>/<repo>/blob/<sha>/server/app/services/repo_cache.py#L120-L188"
    }
  ],
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "tool_calls": 0,
    "iterations": 0,
    "elapsed_seconds": 0
  },
  "preset": "hybrid_rerank"
}
```

`citation_url` follows the same rule as the web client's citation cards: the blob at the ingested commit, falling back to the ingested branch and then `master`. On `error` the result is "Illume could not answer: ..." (with a hint to add a key when the free questions are spent); on timeout the run is stopped and the result suggests `quick` mode or a narrower question. In every case the run is cleaned up in a `finally`, which releases the run slot, and one `mcp_ask` log line records the mode, preset, status and duration.

## Resolving `repo`

[`resolve_repo`](../../server/app/mcp/repos.py) accepts three forms, always scoped to the token's owner:

| Form       | Example                              | Lookup                                                                                |
| ---------- | ------------------------------------ | ------------------------------------------------------------------------------------- |
| number     | `3`                                  | `repo_number`, when the string is ASCII digits, at most 9 of them                     |
| UUID       | `0b6c...`                            | `id`                                                                                  |
| owner/name | `tiangolo/fastapi`, `owner/name.git` | case-insensitive match on the GitHub URL with any `.git` and trailing slashes removed |

The owner and name are matched with `LIKE` after escaping `%`, `_` and `\` (`_like_literal`), so a name containing those characters cannot widen the match. If owner/name matches several repositories (the same GitHub repository ingested on two branches), the error lists up to 10 of them by number, status and branch and asks for the number.

A repository whose status is `failed` or not yet `ready` is refused with a message that says which, so the model can tell the user rather than retrying blindly.

## Resources

[`resources.py`](../../server/app/mcp/resources.py) serves two resource templates as Markdown (`text/markdown`):

| URI template                         | Content                                                                                                                            |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `illume://repo/{repo}/overview`      | the architecture summary, detected stack, entry points and the most critical files, rendered from the `get_overview` tool's output |
| `illume://repo/{repo}/reading-order` | the suggested order to read the files in, each with a note on why                                                                  |

`{repo}` takes the same three forms as the tool argument. `resources/list` returns an empty list and `resources/templates/list` returns the two templates, so a client discovers the URIs from the templates and the repository list. Illume's own headings sit outside fences and every piece of repository text sits inside a `<source>` fence, so even a resource read cannot carry instructions in the clear. A resource read is counted against the per-minute call limit.

## Prompts

[`prompts.py`](../../server/app/mcp/prompts.py) offers four prompts, each producing one user message that tells the assistant which tools to use:

| Prompt          | Title                                | Arguments      | Steers the assistant to                                                                                                                                          |
| --------------- | ------------------------------------ | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `onboard`       | Onboard me to a repository           | `repo`         | read the overview and reading-order resources, then `get_file_info` and `list_symbols` on the first five files of the reading order                              |
| `explain_file`  | Explain a file                       | `repo`, `path` | `get_file_info`, `list_symbols`, `get_importers`, `get_importees`, `get_cochanged` and `read_symbol`, then what the file is for, how risky it is and who owns it |
| `change_impact` | Assess the impact of changing a file | `repo`, `path` | `get_importers` (with `find_path` for indirect users), `get_cochanged` and `get_file_info`, then what to check                                                   |
| `who_to_ask`    | Who to ask about a file              | `repo`, `path` | `get_file_info` for the owner, contributors and bus factor, falling back to `search_history`                                                                     |

Every prompt ends with `_DATA_NOTE`, the reminder that fenced text is data.

## Rate limits

[`limits.py`](../../server/app/mcp/limits.py) keeps fixed-window counters in Redis, one key per user, scope and window (`window_key`), incremented and given an expiry in one transaction.

| Limit                        | Value | Window | Applies to                                                                 |
| ---------------------------- | ----- | ------ | -------------------------------------------------------------------------- |
| `MCP_CALLS_PER_MINUTE`       | 60    | minute | every tool call                                                            |
| `MCP_MODEL_CALLS_PER_MINUTE` | 20    | minute | repository tools of cost class `model` or `network` (`MODEL_COST_CLASSES`) |
| `MCP_FREE_CALLS_PER_DAY`     | 300   | day    | every repository tool call by a user with no AI key of their own           |
| `MCP_ASK_PER_HOUR`           | 20    | hour   | `ask_illume` runs                                                          |

A limited call returns an error result such as "limit 20 search and file-reading calls per minute", with the seconds until the window resets. Windows are aligned to the clock (a minute window resets on the minute), so a burst straddling a boundary can briefly reach twice a limit.

The limiter **fails open**: if Redis is unreachable or slow (a 2-second timeout, `_REDIS_TIMEOUT_SECONDS`), it logs a warning and allows the call. Rate limiting here protects cost, not security; authentication is unaffected.

## What a call costs, and who pays

| Call                                 | Paid by                                                                               |
| ------------------------------------ | ------------------------------------------------------------------------------------- |
| free-class tools                     | nobody beyond database load                                                           |
| `search_code`, `search_history`      | the operator (query embedding on `OPENAI_API_KEY`)                                    |
| `read_file`                          | nobody; GitHub API quota on the user's token                                          |
| `ask_illume quick` on the free tier  | the operator, and one of the user's free questions                                    |
| `ask_illume` with the user's own key | the user (generation), and the operator for embeddings, Cohere rerank and Jev routing |

The free-tier daily cap of 300 repository calls exists because embeddings are paid by the operator for everyone.

## Design trade-offs and limits

- **One registry, two consumers.** The agent and MCP clients use the same tools, so a tool fix reaches both, and MCP behaviour can be tested through the agent's tests. The cost is that tool descriptions are written for Illume's own agent first, hence the override table.
- **Stateless.** Simple to deploy and scale, but every request re-authenticates against the database (with `last_used_at` written at most once a minute).
- **No model stages in MCP search.** Cheaper and faster, and the calling model compensates; it does mean MCP `search_code` ranks differently from chat's `structural`.
- **Fail-open limits.** A Redis outage removes the caps rather than the service.
- **Long-running `ask_illume`.** `deep` can take minutes, and some clients time out tool calls sooner than Illume does; progress notifications help only clients that support them.
- **Prompt injection.** Fencing and the instructions reduce the risk that repository content steers the calling assistant; they cannot remove it, and the calling assistant may have write tools of its own. The MCP tools themselves are all read-only.

## Related documentation

- [Authentication](../security/auth.md#mcp-tokens): how tokens are minted, stored, listed and revoked.
- [The agent](../retrieval/agent.md): the tool registry and the runs `ask_illume` starts.
- [Retrieval arms](../retrieval/retrieval-arms.md): the channels behind `search_code`.
- [Add an MCP tool](../guides/add-an-mcp-tool.md): the steps for exposing a new tool.
- [API reference](../api.md): the HTTP routes beside `/mcp`.
