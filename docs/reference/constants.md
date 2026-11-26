# Constants

Illume's tunables are module-level constants, not environment variables. Every `Settings` field is required and `.env` is gitignored, so a tunable in `Settings` would have to be set in every environment; a constant changes with a code change and a deploy, which is the intent. This page lists the constants that shape behaviour, grouped by area, with the file each lives in. Presentation strings and API base URLs are left out. Retrieval presets are configuration objects rather than constants and are listed on [retrieval arms](../retrieval/retrieval-arms.md#presets).

All paths are under [`server/app/`](../../server/app/) unless they say otherwise.

## Terms used on this page

- **Cap**: an upper bound that silently truncates or skips beyond it. The page says which.
- **Free tier**: requests that run on the operator's key; see [BYOK and encryption](../security/byok-and-encryption.md).

## Ingestion

| Constant                 | Value                        | File                              | Effect                                                                                               |
| ------------------------ | ---------------------------- | --------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `FILE_BATCH_SIZE`        | 500                          | `services/scanner.py`             | files inserted per flush during parse                                                                |
| `DEPENDENCY_BATCH_SIZE`  | 1000                         | `services/dependency_resolver.py` | edges inserted per batch                                                                             |
| `MAX_DOCSTRING_CHARS`    | 4000                         | `services/docstrings.py`          | docstrings are cut to this length                                                                    |
| `GIT_LOG_MAX_COMMITS`    | 500                          | `services/git_analyzer.py`        | only the newest 500 commits are analysed                                                             |
| `MAX_PRS`                | 200                          | `services/pr_fetcher.py`          | merged PRs fetched; `PER_PAGE` 100, `REQUEST_TIMEOUT` 20 s, `MAX_RETRIES` 3                          |
| `MAX_FILES_PER_COMMIT`   | 30                           | `services/cochange.py`            | larger commits are ignored for co-change (bulk renames, formatting)                                  |
| `MIN_TOGETHER`           | 2                            | `services/cochange.py`            | a pair must change together at least twice                                                           |
| `MAX_PARTNERS_PER_FILE`  | 50                           | `services/cochange.py`            | strongest partners kept per file                                                                     |
| `CRITICAL_PATH_PATTERNS` | list                         | `services/criticality.py`         | path patterns that raise criticality; see [criticality](../pipeline/git-intelligence.md#criticality) |
| `LLM_MAX_WORKERS`        | 4                            | `services/_concurrency.py`        | concurrent LLM calls inside one generation stage                                                     |
| parse progress interval  | `max(50, total // 20)` files | `services/scanner.py`             | how often `file_processed` frames are published                                                      |

## Generation

| Constant                | Value | File                             | Effect                                                                    |
| ----------------------- | ----- | -------------------------------- | ------------------------------------------------------------------------- |
| `BATCH_SIZE`            | 25    | `services/glossary_builder.py`   | symbols per glossary prompt                                               |
| `CANDIDATE_MULTIPLIER`  | 5     | `services/glossary_builder.py`   | ranked symbols fetched per entry, since same-named duplicates are trimmed |
| `MAX_GLOSSARY_ENTRIES`  | 200   | `services/glossary_builder.py`   | glossary size cap                                                         |
| `MAX_ANNOTATED_FILES`   | 100   | `services/onboarding.py`         | reading-order entries that get an LLM annotation                          |
| `ANNOTATION_BATCH_SIZE` | 10    | `services/onboarding.py`         | files per annotation prompt                                               |
| `TOP_KEY_MODULES`       | 10    | `services/architecture_brief.py` | key modules given to the brief                                            |
| `DATA_FLOW_HOPS`        | 2     | `services/architecture_brief.py` | depth of the dependency paths the brief describes                         |

## Embeddings and retrieval

| Constant                    | Value                    | File                                      | Effect                                                                                     |
| --------------------------- | ------------------------ | ----------------------------------------- | ------------------------------------------------------------------------------------------ |
| `MAX_CHUNK_TOKENS`          | 2048                     | `services/embedder.py`                    | larger chunks are **skipped**, not truncated (tokens estimated as characters ÷ 4)          |
| `BATCH_SIZE`                | 100                      | `services/embedder.py`                    | texts per embedding request                                                                |
| `EMBED_BUILD_BATCH_SIZE`    | 500                      | `services/embedder.py`                    | symbol chunks built per batch                                                              |
| `EMBEDDING_MODEL`           | `text-embedding-3-small` | `services/retrieval/embedding.py`         | changing it needs a migration (1536 dimensions)                                            |
| `TOP_K`                     | 10                       | `services/rag.py`                         | Classic chat's context size                                                                |
| `NO_CONTEXT_ANSWER`         | fixed text               | `services/retrieval/single_shot.py`       | returned without calling the model when nothing is retrieved                               |
| `MAX_OUTPUT_TOKENS`         | 8000                     | `services/retrieval/single_shot.py`       | single-shot answer length                                                                  |
| `DEFAULT_CONTEXT_WINDOW`    | 250,000                  | `services/retrieval/config.py`            | when the user has not set one; bounded by `MIN_` 32,000 and `MAX_CONTEXT_WINDOW` 1,000,000 |
| `MAX_QUERY_TOKENS`          | 64                       | `services/retrieval/channels/lexical.py`  | words kept from the question for keyword search                                            |
| `MAX_PATTERN_LENGTH`        | 200                      | `services/retrieval/channels/grep.py`     | regex length cap; `DEFAULT_MAX_RESULTS` 200, `DEFAULT_TIMEOUT_MS` 2000                     |
| `INTERNAL_RRF_K`            | 60                       | `services/retrieval/channels/history.py`  | fusion constant inside the history channel                                                 |
| `SEED_RANK_CONSTANT`        | 60                       | `services/retrieval/channels/_files.py`   | rank constant for file seeds                                                               |
| `MAX_HEADER_SYMBOLS`        | 15                       | `services/retrieval/channels/_files.py`   | symbol names in a file card's header                                                       |
| `MAX_RENDERED_CHARACTERS`   | 8192                     | `services/retrieval/channels/_symbols.py` | rendered symbol cap                                                                        |
| `WEIGHT_GAIN`               | 0.1                      | `services/retrieval/channels/graph.py`    | score multiplier `1 + 0.1 × ln(1 + weight)` for graph neighbours                           |
| `MAX_COUNT`                 | 1000                     | `services/retrieval/dates.py`             | upper bound on numbers in date phrases ("last N days")                                     |
| `MAX_VARIANT_CHARS`         | 2000                     | `services/retrieval/query.py`             | query rewrite length                                                                       |
| `CALL_TIMEOUT_SECONDS`      | 30                       | `services/retrieval/llm_json.py`          | JSON-mode LLM calls (rewrites, listwise rerank)                                            |
| `SHORT_HASH_LENGTH`         | 8                        | `services/retrieval/citations.py`         | commit hash length in citation keys                                                        |
| `COHERE_MODEL`              | `cohere/rerank-5-fast`   | `services/retrieval/rerank/cohere.py`     | via OpenRouter; `MAX_DOCUMENT_CHARS` 4000, timeout 30 s                                    |
| `MAX_PARALLEL_REQUESTS`     | 4                        | `services/retrieval/rerank/jev.py`        | concurrent Jev relevance calls                                                             |
| `WINDOW_SIZE`, `MERGE_POOL` | 20, 20                   | `services/retrieval/rerank/llm.py`        | listwise rerank windows; `PASSAGE_CHARS` 1500, 4 in parallel                               |

## Decisions and routing

| Constant                    | Value               | File                               | Effect                                             |
| --------------------------- | ------------------- | ---------------------------------- | -------------------------------------------------- |
| `JEV_MODEL`                 | `typesafe/jev-1.14` | `services/decisions/openrouter.py` | the decision model                                 |
| `MAX_REQUEST_BYTES`         | 32,000              | `services/decisions/openrouter.py` | request size cap; `REQUEST_TIMEOUT_SECONDS` 30     |
| `MAX_PARALLEL_REQUESTS`     | 4                   | `services/decisions/jev.py`        |                                                    |
| `MAX_STATE_CHARS`           | 40,000              | `services/decisions/llm.py`        | state cap for the LLM decider; 4 calls in parallel |
| `MAX_QUESTION_CHARS`        | 4000                | `services/decisions/points.py`     | question cap in decision states                    |
| `MAX_HISTORY_MESSAGE_CHARS` | 500                 | `services/decisions/points.py`     | previous question cap                              |
| `MAX_STATE_CHARS`           | 12,000              | `services/decisions/points.py`     | route state cap                                    |
| `MAX_PASSAGE_CHARS`         | 1500                | `services/decisions/points.py`     | passage cap for relevance decisions; question 1000 |
| `ROUTE_CONFIDENCE`          | 0.6                 | `services/decisions/points.py`     | the auto router's floor                            |
| `ROUTE_TIMEOUT_SECONDS`     | 4.0                 | `services/agent/auto.py`           | the route decision's timeout                       |
| `FALLBACK_PRESET`           | `structural`        | `services/agent/auto.py`           | what `auto` runs when it cannot route              |

## The agent

| Constant                                    | Value     | File                                | Effect                                                                                             |
| ------------------------------------------- | --------- | ----------------------------------- | -------------------------------------------------------------------------------------------------- |
| `AGENT_MAX_OUTPUT_TOKENS`                   | 16,000    | `services/agent/deps.py`            | per agent turn                                                                                     |
| `SYNTHESIS_MAX_OUTPUT_TOKENS`               | 8000      | `services/agent/deps.py`            | the final answer; `SYNTHESIS_EFFORT` `low`                                                         |
| `MAX_CONSECUTIVE_TOOL_ERRORS`               | 3         | `services/agent/deps.py`            | turns in a row of only failed tool calls or empty replies, after which the run stops investigating |
| `STEPS_PER_ITERATION`, `STEPS_OUTSIDE_LOOP` | 2, 16     | `services/agent/graph.py`           | LangGraph recursion limit = iterations × 2 + 16                                                    |
| `OVERFLOW_KEEP_RECENT_TURNS`                | 1         | `services/agent/nodes/agent.py`     | turns kept verbatim when the window overflows                                                      |
| `SHOWN_OUTPUT_CHARS`                        | 4000      | `services/agent/nodes/tools.py`     | tool output shown in events                                                                        |
| `MAX_RESULT_CHARS`                          | 12,000    | `services/agent/tools/output.py`    | tool output given to the model                                                                     |
| `MAX_LINES_PER_CALL`                        | 400       | `services/agent/tools/read_file.py` | lines per `read_file`                                                                              |
| `CHARS_PER_TOKEN`                           | 3.5       | `services/agent/window.py`          | token estimate; `MIN_COMPACTED_CHARS` 600                                                          |
| `PROMPT_VERSION`                            | `agent-4` | `services/agent/prompts.py`         | stored on every run; `SYNTHESIS_CONTEXT_CHARS` 60,000                                              |
| `FINAL_ANSWER_GRACE_SECONDS`                | 120       | `services/agent/runner.py`          | time allowed to write the answer after the hard timeout                                            |
| `CLASSIC_HISTORY_MESSAGES`                  | 5         | `services/agent/run_request.py`     | history for Classic; others `MAX_HISTORY_MESSAGES` 20                                              |
| `CLEANUP_TIMEOUT_SECONDS`                   | 15        | `services/agent/session.py`         | finishing a run after the client leaves                                                            |
| `MAX_CONCURRENT_RUNS`                       | 2         | `services/agent/slots.py`           | per user; `SLOT_TTL_SECONDS` 960                                                                   |
| `MAX_PAYLOAD_BYTES`                         | 64 KiB    | `services/agent/persistence.py`     | step payload cap                                                                                   |
| `MAX_STEPS`, `MAX_EVENTS`                   | 400, 1500 | `services/agent/persistence.py`     | per run                                                                                            |
| `STALE_RUN_SECONDS`                         | 300       | `services/agent/persistence.py`     | a `running` run silent for this long reads as interrupted                                          |
| `RETENTION_DAYS`                            | 30        | `services/agent/persistence.py`     | step rows older than this are pruned; runs are kept                                                |
| `DELTA_FLUSH_CHARS`, `DELTA_FLUSH_SECONDS`  | 160, 0.1  | `services/agent/persistence.py`     | answer-text events are batched to this                                                             |
| `MAX_CITATION_CHARS`                        | 4000      | `services/agent/persistence.py`     |                                                                                                    |
| `PRUNE_BATCH_SIZE`                          | 5000      | `tasks/agent_retention.py`          | rows deleted per prune batch                                                                       |
| `SSE_PING_SECONDS`                          | 15        | `api/v1/agent.py`                   | keep-alive comments on the event stream                                                            |

Full explanations: [the agent](../retrieval/agent.md).

## Auto-update and the clone cache

| Constant                        | Value   | File                     | Effect                                                                  |
| ------------------------------- | ------- | ------------------------ | ----------------------------------------------------------------------- |
| `AUTO_UPDATE_ENABLED`           | True    | `tasks/autoupdate.py`    | kill switch for the sweep                                               |
| `SWEEP_INTERVAL_MINUTES`        | 10      | `tasks/autoupdate.py`    | beat schedule for the sweep                                             |
| `SYNC_LEASE_MINUTES`            | 60      | `tasks/autoupdate.py`    | how long a sync owns its row                                            |
| `SWEEP_BATCH_LIMIT`             | 50      | `tasks/autoupdate.py`    | repositories claimed per sweep                                          |
| `SWEEP_OFFSET_JITTER_SECONDS`   | 60      | `tasks/autoupdate.py`    | spreads next-sync times                                                 |
| `SYNC_FULL_MAX_FILES`           | 500     | `tasks/autoupdate.py`    | more changed files than this, or                                        |
| `SYNC_FULL_MAX_RATIO`           | 0.5     | `tasks/autoupdate.py`    | more than this share of the repository, runs a full rebuild             |
| `SYNC_MAX_CONSECUTIVE_FAILURES` | 3       | `tasks/autoupdate.py`    | then the toggle switches itself off and the UI shows it paused          |
| `SYNC_BACKOFF_BASE_MINUTES`     | 5       | `tasks/autoupdate.py`    | exponential back-off base                                               |
| `CLONE_CACHE_MAX_BYTES`         | 2 GiB   | `services/repo_cache.py` | whole cache, evicted least recently used                                |
| `CLONE_CACHE_MAX_REPO_BYTES`    | 512 MiB | `services/repo_cache.py` | larger repositories are cloned ephemerally                              |
| `CLONE_CACHE_ENABLED`           | True    | `services/repo_cache.py` |                                                                         |
| `GIT_FETCH_TIMEOUT_SECONDS`     | 60      | `services/repo_cache.py` | also `GIT_LS_REMOTE_TIMEOUT_SECONDS` 20, `GIT_RESET_TIMEOUT_SECONDS` 30 |

The prune task is scheduled daily at 03:40 (`crontab(hour=3, minute=40)`) in the same beat schedule. Celery recycles worker processes after 10 tasks (`worker_max_tasks_per_child` in `core/celery.py`). See [sync](../pipeline/sync.md) and [the clone cache](../pipeline/clone-cache.md).

## API limits and validation

| Constant                               | Value   | File                        | Effect                                                       |
| -------------------------------------- | ------- | --------------------------- | ------------------------------------------------------------ |
| `MAX_PAGE_SIZE`                        | 200     | `api/validation.py`         | pagination cap                                               |
| `MAX_QUESTION_CHARS`                   | 4000    | `api/validation.py`         | chat question length                                         |
| `MAX_HISTORY_ITEMS`                    | 40      | `api/validation.py`         | history entries accepted                                     |
| `MAX_HISTORY_CONTENT_CHARS`            | 20,000  | `api/validation.py`         | per history entry                                            |
| `MAX_TITLE_CHARS`                      | 120     | `api/v1/conversations.py`   | renamed conversation titles                                  |
| `TITLE_LIMIT`                          | 60      | `services/conversations.py` | automatic titles; `DEFAULT_TITLE` "New chat"                 |
| `MAX_CHANGE_COMMITS`                   | 20      | `api/v1/chat.py`            | commits listed when explaining a stale answer                |
| `THUMBNAIL_MAX_FILES`                  | 120     | `api/v1/graph.py`           | repository card graph                                        |
| `SEARCH_PAGE_SIZE`, `SEARCH_MAX_PAGES` | 100, 10 | `api/v1/github_proxy.py`    | the repository picker's search, timeout 15 s                 |
| `MAX_FILE_BYTES`                       | 2 MiB   | `services/github_files.py`  | file contents fetched from GitHub; `BINARY_SNIFF_BYTES` 8192 |
| `DEFAULT_RETRY_AFTER_SECONDS`          | 60      | `services/github_http.py`   | assumed when GitHub rate-limits without a header             |
| `PROBE_TIMEOUT_SECONDS`                | 1.5     | `core/health.py`            | per dependency in the health check                           |

## Free tier, tokens and MCP

| Constant                      | Value      | File                       | Effect                                                                                      |
| ----------------------------- | ---------- | -------------------------- | ------------------------------------------------------------------------------------------- |
| `FREE_INGESTIONS`             | 3          | `services/entitlements.py` | ingestions on the operator's key per user                                                   |
| `FREE_CHAT_MESSAGES`          | 10         | `services/entitlements.py` | answered questions on the operator's key                                                    |
| `ENVELOPE_PREFIX`             | `illume1.` | `core/crypto.py`           | marks an encrypted value                                                                    |
| `MIN_KEY_LENGTH`              | 32         | `core/crypto.py`           | for `CREDENTIAL_ENCRYPTION_KEY`                                                             |
| `TOKEN_PREFIX`                | `ilm_`     | `services/mcp_tokens.py`   | MCP token prefix; `DISPLAY_PREFIX_LENGTH` 8                                                 |
| `MAX_TOKENS_PER_USER`         | 10         | `services/mcp_tokens.py`   | active MCP tokens                                                                           |
| `MCP_PATH`                    | `/mcp`     | `mcp/server.py`            | mount point; `MCP_ENABLED` True                                                             |
| `MCP_MAX_BODY_BYTES`          | 1 MiB      | `mcp/server.py`            | request body cap                                                                            |
| `MCP_CALLS_PER_MINUTE`        | 60         | `mcp/limits.py`            | all tool calls                                                                              |
| `MCP_MODEL_CALLS_PER_MINUTE`  | 20         | `mcp/limits.py`            | calls that reach a model                                                                    |
| `MCP_FREE_CALLS_PER_DAY`      | 300        | `mcp/limits.py`            | free-tier daily cap                                                                         |
| `MCP_ASK_PER_HOUR`            | 20         | `mcp/limits.py`            | `ask_illume` calls                                                                          |
| `SINGLE_SHOT_TIMEOUT_SECONDS` | 120        | `mcp/ask.py`               | quick and auto answers; agents get their own timeout plus `AGENT_TIMEOUT_MARGIN_SECONDS` 15 |
| `ANSWER_PROGRESS_SECONDS`     | 5          | `mcp/ask.py`               | progress notification interval                                                              |
| `PUSH_TIMEOUT_SECONDS`        | 10         | `services/push.py`         | Expo push delivery                                                                          |

`server/.env.example` says the free tier covers "their first five chat questions"; the constant is 10.

## Design trade-offs and limits

- **A deploy per change.** Nothing here can be tuned per environment without editing code.
- **Duplicated names.** `BATCH_SIZE`, `MAX_STATE_CHARS`, `MAX_QUESTION_CHARS` and `MAX_PARALLEL_REQUESTS` each exist in more than one module with different meanings; import them by module.
- **Literals not listed here.** Some caps are inline literals rather than named constants, for example the `.illume` export's caps (see [the export](../interfaces/illume-export.md#caps)).

## Related documentation

- [Environment variables](environment.md): what is configurable per environment.
- [Retrieval arms](../retrieval/retrieval-arms.md#presets): the preset configurations.
- [The agent](../retrieval/agent.md#token-budgets): budgets and limits in context.
