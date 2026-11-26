# Chat and citations

Chat is how a user asks questions about an ingested repository. Two endpoints answer them: the original `POST /chat`, which runs the Classic pipeline and returns one JSON response, and `POST /chat/stream`, which runs any preset (including the tool-using agent) and streams its progress as server-sent events. The web client uses the streaming endpoint; the mobile app uses the original one. This page covers both request paths, the single-shot answer that most presets end in, how citations are written by the model and matched back to sources, conversations, stale answers, and the free-tier accounting around them.

## Terms used on this page

- **Preset**: a named retrieval and answering configuration such as `classic`, `hybrid` or `deep_agent`. Presets are defined in [`retrieval/config.py`](../../server/app/services/retrieval/config.py) and described in [retrieval arms](retrieval-arms.md#presets).
- **Single-shot**: a preset that retrieves once and calls the model once to write the answer. The opposite is an agent preset, where the model calls tools in a loop; see [the agent](agent.md).
- **Classic-shaped**: a configuration whose behaviour hash equals the Classic preset's. Classic-shaped runs keep the original prompt and citation format exactly, for compatibility with stored history and the evaluation baseline.
- **Citation key**: a short bracketed identifier such as `[F:server/app/main.py:12-40]` that the model writes in the answer to say which source supports a point.
- **Conversation**: a titled thread of questions and answers for one user and one repository.
- **Stale answer**: an answer that cited a file which has since changed on the repository's branch.

## Two endpoints

```mermaid
flowchart LR
  WEB["web client<br/>useConversation"] --> STREAM["POST /chat/stream<br/>any preset, SSE"]
  MOB["mobile app"] --> CHAT["POST /chat<br/>Classic, JSON"]
  MCP["MCP ask tool"] --> PREP["prepare_run<br/>save_history off"]
  STREAM --> PREP2["prepare_run"]
  PREP2 --> RS["RunSession"]
  PREP --> RS
  RS --> SS{"execution"}
  SS -- "single_shot" --> ANS["single_shot.answer"]
  SS -- "agent or planner" --> AG["run_agent"]
  CHAT --> RAG["rag.answer_question"]
  RAG --> ANS
```

| Endpoint                                        | Router                                         | Runs                    | Response                     | Used by        |
| ----------------------------------------------- | ---------------------------------------------- | ----------------------- | ---------------------------- | -------------- |
| `POST /api/v1/repository/{repo_id}/chat`        | [`chat.py`](../../server/app/api/v1/chat.py)   | the Classic preset only | one `ChatResponse` JSON body | the mobile app |
| `POST /api/v1/repository/{repo_id}/chat/stream` | [`agent.py`](../../server/app/api/v1/agent.py) | any preset, or `auto`   | a server-sent event stream   | the web client |

Both key on the repository's UUID `id`, not its user-scoped `repo_number`. Both refuse a repository whose `status` is not `ready`, so chat works throughout a background [sync](../pipeline/sync.md#why-a-sync-keeps-status-ready), which keeps `status='ready'`.

The MCP `ask` tool reaches the same `prepare_run` and `RunSession` as the streaming endpoint with `save_history=False`, so its answers never appear in the user's conversations; see [the MCP server](../mcp/server.md).

## The Classic endpoint

`POST /chat` takes a `ChatRequest`:

| Field             | Type                      | Limit                                                                                    |
| ----------------- | ------------------------- | ---------------------------------------------------------------------------------------- |
| `question`        | multi-line text           | `MAX_QUESTION_CHARS = 4000`                                                              |
| `conversation_id` | UUID, optional            | must belong to the caller and this repository; omitted means start a new conversation    |
| `history`         | list of `{role, content}` | at most `MAX_HISTORY_ITEMS = 40` items, each at most `MAX_HISTORY_CONTENT_CHARS = 20000` |

The limits live in [`api/validation.py`](../../server/app/api/validation.py). The handler then:

1. Loads the repository filtered by `id` and the caller's `user_id`. Missing or someone else's: **404**. Not `ready`: **400**.
2. Checks a supplied `conversation_id` with `owned_conversation`. Not the caller's: **404**.
3. Records `asked_at_sha = repo.ingested_commit_sha`, the commit the answer will be about.
4. Keeps the last five messages: `payload.history[-5:]`. That is five _messages_, about two and a half exchanges, not five turns.
5. Resolves the caller's generation credential with `llm_config_for`. None available: **402**, asking the user to add a key. On the free tier with `free_chat_messages_used >= FREE_CHAT_MESSAGES` (10, in [`entitlements.py`](../../server/app/services/entitlements.py)): **402**.
6. Calls `rag.answer_question` (below). Provider errors are mapped to **502** with the provider's message: `AuthenticationError` ("Provider rejected the API key"), `APIConnectionError` or `APITimeoutError` ("Could not reach the LLM provider"), and any other `APIStatusError` ("Provider returned an error"). Anything else is an unhandled 500.
7. On the free tier, claims one free message with `aclaim_free_chat_message`, but **only if `result.generated` is true**. An answer that found no context never called the model and costs nothing.
8. Creates the conversation if none was given (`ensure_conversation`, titled from the question), inserts the `ChatMessage` row with `answered_commit_sha` and `cited_paths`, bumps the conversation's `updated_at`, commits, and returns `{id, conversation_id, answer, sources}`.

Older documentation said a provider error became a 500. The 502 mapping above is current.

### `rag.answer_question`

[`rag.py`](../../server/app/services/rag.py) is now a thin wrapper. It builds an embedding function on the operator's `OPENAI_API_KEY`, wraps the generation client for tracing, and calls `single_shot.answer(CLASSIC, ...)`. It records trace metadata (arm `classic`, model, whether the key was the user's or the server's, the number of chunks and the dense distances) when [LangSmith tracing](../reference/environment.md) is on, and returns `RAGResponse {answer, sources, generated}`.

The module still exports `TOP_K = 10`, `TYPE_CAPS`, `_apply_diversity_caps` and `_vector_search`. Those are the original Classic retrieval; nothing in the application calls them, and [`test_rag_parity.py`](../../server/tests/integration/services/test_rag_parity.py) keeps a frozen copy of the old path and checks that the live one still retrieves the same rows and sends the model the same bytes. The live path goes through the shared pipeline in [`retrieval/pipeline.py`](../../server/app/services/retrieval/pipeline.py) with the Classic preset, which reproduces it: dense search only, cosine distance under 0.7, up to 50 nearest, then the soft diversity caps down to 10.

## The streaming endpoint

`POST /chat/stream` takes a `StreamRequest`, which has the same `question`, `conversation_id` and `history` fields plus:

| Field       | Default     | Meaning                                                                                                                       |
| ----------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `preset`    | `"classic"` | one of the presets, or `"auto"` to let the [router](router.md) pick; anything else is a 422                                   |
| `overrides` | none        | per-request adjustments to the preset, validated and capped by [`overrides.py`](../../server/app/services/agent/overrides.py) |

Unknown fields are rejected (`extra="forbid"`).

### Admission: `prepare_run`

All checks run before any event is sent, so a refusal is an ordinary HTTP error rather than an error frame. [`prepare_run`](../../server/app/services/agent/run_request.py) applies them in this order, raising `RunRefusal(status, detail)`:

| Order | Check                                                                                  | Status |
| ----- | -------------------------------------------------------------------------------------- | ------ |
| 1     | repository owned by the caller                                                         | 404    |
| 2     | repository `status == "ready"`                                                         | 400    |
| 3     | conversation owned by the caller and repository (when saving history and one is given) | 404    |
| 4     | overrides valid for this preset and key (skipped for `auto` until the route is known)  | 422    |
| 5     | a generation credential exists                                                         | 402    |
| 6     | `auto` requested on the free tier                                                      | 402    |
| 7     | an agent or planner preset requested on the free tier                                  | 402    |
| 8     | the model behind the user's key supports tool calling (agent presets)                  | 400    |
| 9     | free tier and the allowance is spent                                                   | 402    |
| 10    | a free run slot for this user (`MAX_CONCURRENT_RUNS = 2`)                              | 429    |

Tool support (check 8) is probed once per key and cached on the user row; see [BYOK and encryption](../security/byok-and-encryption.md#tool-support-and-its-cache). Run slots are a Redis sorted set; see [the agent](agent.md#run-slots).

After the slot is taken, `prepare_run` resolves `auto` to a concrete preset, applies the overrides again to that preset, bounds the history, and inserts an `AgentRun` row with status `running`. If anything in that stretch fails, the slot is released before the exception leaves.

The history bound is `CLASSIC_HISTORY_MESSAGES = 5` for a Classic-shaped configuration, matching `POST /chat`, and `MAX_HISTORY_MESSAGES = 20` for everything else. A single-shot preset then replays only its own `query.history_messages` (5 by default, 10 for the agent presets) into the answering call; the larger bound gives query condensing and the agent more to work with.

### The run

The route builds a `RunSession`, starts its driver task, and returns an `EventSourceResponse` over `run.frames()`, with `Cache-Control: no-cache`, `X-Accel-Buffering: no` (so a reverse proxy does not buffer the stream) and a ping every `SSE_PING_SECONDS = 15`. Cleanup is attached as a background task and also runs when the frame generator is closed, so a client that disconnects cancels the run.

`RunSession._execute` publishes `run_started` (and `route` for `auto`), then branches on `config.execution`: `single_shot` goes to `single_shot.answer` with `stream=True`, anything else to `run_agent`. When the run concludes with an answer, `_conclude` saves the turn (unless `save_history` is off), publishes `done` with the answer, citations, stop reason, usage and the new `chat_message_id`, closes the recorder and finalises the `AgentRun` row. The event types are listed in [the agent](agent.md#events).

### Free-tier charging on the stream

Only single-shot presets can run on the free tier. For those, `_single_shot` claims one free message **before** generating (`aclaim_free_chat_message`, a conditional `UPDATE` that fails when the counter is already at the limit) and refunds it with `arefund_free_chat_message` when:

- the retrieval found nothing and no model call was made (`generated` is false);
- the run raised before finishing;
- the client cancelled before the first answer token arrived.

A cancellation after text has started streaming is not refunded, since the model has already been paid for. If the claim itself raises (a database hiccup), the run proceeds uncharged rather than refusing the user; the warning is logged.

## The single-shot answer

[`single_shot.answer(config, question, ctx=..., history=..., llm=..., emit=..., stream=...)`](../../server/app/services/retrieval/single_shot.py) is shared by `POST /chat`, the streaming endpoint's single-shot presets and the evaluation harness.

```mermaid
sequenceDiagram
  participant C as caller
  participant A as single_shot.answer
  participant R as retrieve
  participant M as model
  C->>A: question, history, config
  A->>R: retrieve with config
  R-->>A: candidates and trace
  A-->>C: retrieval event
  alt no candidates
    A-->>C: NO_CONTEXT_ANSWER, generated false
  else classic-shaped
    A->>M: classic prompt and history
    M-->>A: answer text
    A-->>C: answer, every candidate as a source
  else citing prompt
    A->>M: source blocks and replayed history
    M-->>A: answer with bracketed keys
    A->>A: split_by_citations
    A-->>C: answer, cited sources, unresolved keys
  end
```

1. **Retrieve.** `retrieve(config, question, ...)` runs the configured pipeline (query transforms, channels, fusion, rerank, diversity) and returns the candidates plus a trace. See [retrieval arms](retrieval-arms.md).
2. **Announce.** A `retrieval` event carries the standalone question, the per-channel candidate counts, the candidate keys, the reranker, the query variants and the history date range, if one was resolved.
3. **No context.** With no candidates it returns `NO_CONTEXT_ANSWER` ("No relevant code was found in this repository for your question.") with `generated=False`, **without calling the model**.
4. **Choose the generation settings.** `_generation_settings` prefers the caller's `LLMConfig`. With none, a Classic-shaped run falls back to the operator's `OPENAI_API_KEY` with `settings.AI_MODEL`, the endpoint's long-standing behaviour; any other shape uses the free-tier credential from `LLMConfig.server_default()`. Every call asks for minimal reasoning effort and `max_output_tokens = MAX_OUTPUT_TOKENS = 8000`.
5. **Generate.** The messages are the system prompt, then the prior turns as real conversation turns, then the question. With `stream=True` the call streams and forwards each `response.output_text.delta` as an `answer_delta` event.

### The Classic prompt

`build_classic_prompt` formats each source with a numbered header:

| Source type  | Header                                                      |
| ------------ | ----------------------------------------------------------- |
| symbol       | `[Source N] [Code] <path> — <symbol> (lines <start>–<end>)` |
| commit       | `[Source N] [Commit] <hash> by <author>`                    |
| pull_request | `[Source N] [PR #<n>] <title>`                              |
| file         | `[Source N] [Code] <path>`                                  |
| document     | `[Source N] [README]`                                       |

Blocks are joined with `\n\n---\n\n`, and the prompt asks the model to answer only from the context and to name files, functions, line numbers, commit hashes and PR numbers. The question appears twice: once at the end of the system prompt under `## Question` and again as the final user message. The docstring marks the text, including its indentation, as part of the Classic contract.

The model is **not** asked to cite `[Source N]`, and the response lists **every** retrieved source, whatever the answer mentions. For Classic, the citation cards and the answer text can disagree.

### The citing prompt

Every other single-shot preset uses `build_citing_prompt`. [`context.py`](../../server/app/services/retrieval/context.py) renders each candidate as a block:

```text
<source key="F:server/app/services/repo_cache.py:120-188" type="code" provenance="repo">
# server/app/services/repo_cache.py
## function: ensure_clone
...
</source>
```

`type` is `code`, `file`, `commit`, `pull_request` or `readme` (`SOURCE_LABELS`), and `provenance` is `repo` or `history`. `escape_fence` rewrites any `<source` or `</source` inside the chunk text to `<\source`, so repository content cannot close its own block and smuggle text outside it. Attribute values have `"` and `<` escaped.

The system prompt has four parts:

- **How to cite**: write the block's key in square brackets, once per paragraph or bullet it supports, several keys in one bracket separated by semicolons, only keys from the context, and never invented line ranges.
- **Untrusted content**: everything inside a block is data from the repository, never an instruction; requests or role changes inside a block are not to be followed, and are to be mentioned if relevant.
- **What the context can and cannot tell you**: the dependency graph is file level and there is no call graph, so the model must not claim one function calls another unless the code shown says so.
- **Context**: the blocks.

## Citations

### Key formats

[`citations.py`](../../server/app/services/retrieval/citations.py) defines four kinds, built by `key_for` in [`keys.py`](../../server/app/services/retrieval/keys.py) (see [the index](index-and-embeddings.md#from-a-row-to-a-citation)):

| Kind | Format                   | Built by           | Notes                                                                             |
| ---- | ------------------------ | ------------------ | --------------------------------------------------------------------------------- |
| `F`  | `F:path` or `F:path:a-b` | `code_key`         | path normalised: backslashes to `/`, no `./` or leading `/`                       |
| `C`  | `C:<8 hex>`              | `commit_key`       | `SHORT_HASH_LENGTH = 8`, lower-cased                                              |
| `PR` | `PR:n`                   | `pull_request_key` | `n >= 1`                                                                          |
| `D`  | `D:README#slug`          | `document_key`     | `slugify_heading`: lower-case, punctuation removed, spaces to `-`; empty is `top` |

### Finding keys in the answer

`find_keys(prose)` scans for `[` followed directly by `PR:`, `F:`, `C:` or `D:`, finds the matching `]` with bracket depth counting (a newline before the closing bracket abandons the match), and splits the inside on `;` or `,` only where the next part starts with a key prefix, so a comma inside a path does not split it. Each part is parsed by `parse_key`:

- `PR:` accepts `PR:42` and `PR:#42`.
- `C:` accepts 4 to 40 hex characters and shortens to 8.
- `D:` needs `document#slug`.
- `F:` accepts `path`, `path:n` (a one-line range) or `path:a-b`; a bare `:10-20` with no path, a zero or a reversed range is rejected.

An unparseable key is kept as `(raw, None)` so it can be reported.

### Matching keys to sources

`split_by_citations(answer, candidates)` matches every found key with `match_citation`:

1. **Exact.** The rendered key equals a candidate's key.
2. **Code, fuzzy.** For `F:` keys, it collects the candidates in the same normalised file. With no line range it takes the first. With a range it takes the candidate whose lines overlap the cited range most; a whole-file candidate counts as overlapping the whole cited range.
3. **Commit, prefix.** For `C:` keys, a candidate matches when either hash is a prefix of the other.
4. Otherwise the key is **unresolved**.

The result has three lists: `cited` (matched candidates, de-duplicated, in the order the answer first cites them), `context` (every candidate the answer did not cite) and `unresolved` (raw keys that matched nothing, which usually means the model invented a key). For citing presets, the response's `sources` are the cited candidates only; the uncited ones go in `context`, and the evaluation harness scores `unresolved` as a faithfulness signal.

On the streaming endpoint, each citation carries its key, so the client can link a bracket in the text to its card. The agent's citations are built from its evidence map in the same format; see [the agent](agent.md#evidence-and-citations).

## Conversations

A conversation groups chat messages for one user and one repository. The routes are in [`conversations.py`](../../server/app/api/v1/conversations.py) under the same `/api/v1/repository` prefix:

| Method and path                                           | Does                                                                                         |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `GET /{repo_id}/conversations`                            | list the caller's conversations with a `message_count`, newest activity first                |
| `POST /{repo_id}/conversations`                           | create one, optionally with a title; 201                                                     |
| `PATCH /{repo_id}/conversations/{conversation_id}`        | rename; the title is 1 to `MAX_TITLE_CHARS = 120` characters, trimmed, no control characters |
| `DELETE /{repo_id}/conversations/{conversation_id}`       | delete it and, by cascade, its messages; 204                                                 |
| `GET /{repo_id}/conversations/{conversation_id}/messages` | its messages, oldest first                                                                   |

A conversation created by the first question of a new thread gets its title from [`title_from_question`](../../server/app/services/conversations.py): whitespace collapsed, and cut to `TITLE_LIMIT = 60` characters with an ellipsis. One created empty is titled `DEFAULT_TITLE = "New chat"`. `ensure_conversation` inserts with `ON CONFLICT DO NOTHING`, so two first questions racing on the same new id do not fail.

The chat router has four more message routes:

| Method and path                            | Does                                                                             |
| ------------------------------------------ | -------------------------------------------------------------------------------- |
| `GET /{repo_id}/chat/history`              | every message for the repository, or one conversation's with `?conversation_id=` |
| `GET /{repo_id}/chat/{message_id}/changes` | what changed since a stale answer (below)                                        |
| `DELETE /{repo_id}/chat/{message_id}`      | delete one message                                                               |
| `DELETE /{repo_id}/chat`                   | delete every conversation for the repository and, by cascade, every message      |

Every route filters by the caller's `user_id`; there is no ORM-level scoping. The web client's chat sidebar and history come from the conversation routes and `GET /agent-runs`, which lists recent runs so the client can show each turn's tool activity after a reload.

### What a stored message holds

`ChatMessage` ([`chat_message.py`](../../server/app/models/chat_message.py)) stores the question, the answer, `sources` as JSONB (so citations survive a reload), the `agent_run_id` that produced it (null for `POST /chat`), `answered_commit_sha`, `cited_paths` (the distinct file paths of its sources, from `cited_file_paths`) and three staleness columns.

## Stale answers

An answer is a statement about the code at one commit. When a background sync changes a file that an answer cited, the sync's `mark_stale_answers` sets the message's `stale_at`, `stale_paths` and `stale_commit_sha`. How it does that is in [git intelligence](../pipeline/git-intelligence.md#stale-answers).

The history responses include those fields, and the client's `StaleNotice` component shows a banner on the answer. Opening it calls `GET /chat/{message_id}/changes`, which returns:

- `stale_paths`;
- up to `MAX_CHANGE_COMMITS = 20` commits authored after the answer that touched any stale path, newest first, each with the touched files;
- a GitHub compare URL between `answered_commit_sha` and `stale_commit_sha`.

Two limits apply. The commit list compares `authored_at` with the answer's `created_at`, so a commit authored before the answer but pushed after it is missed. And because answers are only ever marked, never rewritten, a stale answer stays stale until it is deleted or asked again.

## The web client

The chat page is [`ChatPage.tsx`](../../client/src/components/chat/ChatPage.tsx) under `/repo/[id]/chat`. [`useConversation`](../../client/src/hooks/useConversation.ts) loads a conversation's messages and recent agent runs, and [`useAgentStream`](../../client/src/hooks/useAgentStream.ts) posts to `/chat/stream` with `fetch` and reads the event stream itself, because `EventSource` cannot send a request body. The stream is cancelled when the component unmounts. Other pieces: `PresetPicker` (preset choice, including `auto`), `AdvancedDrawer` (overrides), `ActivityBlock` (tool calls and retrieval), `LiveGraph` (a non-interactive full-viewport graph that lights the files the agent touches as it touches them), `AnswerView` (the answer with linked citation keys), `ConversationSidebar` and `StaleNotice`. See [the frontend overview](../frontend/overview.md).

The file [`client/src/api/chat.ts`](../../client/src/api/chat.ts) still exports `GetChat`, which issues `GET /chat`, a route that does not exist. Nothing imports it.

## Design trade-offs and limits

- **Two endpoints.** `POST /chat` is kept stable for the mobile app and as the evaluation baseline; new behaviour goes only into the streaming path. The mobile app therefore cannot use the other presets.
- **Classic cites everything.** Its sources are all retrieved chunks, not what the answer used, and its prompt does not ask for citations.
- **History is client-supplied.** The server trusts the `history` the client sends rather than reading the conversation from the database, so a client can replay turns that were never asked. It is bounded in count and length but not verified.
- **Charges follow generation.** A question that retrieves nothing is free, and a free-tier stream is refunded if it fails or is cancelled before the first token.
- **Prompt-injection defence is advisory.** Fencing and the untrusted-content rule make injection from repository content harder, not impossible. Classic has neither.
- **Staleness compares author dates.** Rebased or late-pushed commits can be missed in the change list.

## Related documentation

- [The index and embeddings](index-and-embeddings.md): what a chunk and a citation key are.
- [Retrieval arms](retrieval-arms.md): presets, channels, fusion and rerankers.
- [The agent](agent.md): the tool-using presets, events and run lifecycle.
- [The auto router](router.md): how `auto` picks a preset.
- [BYOK and encryption](../security/byok-and-encryption.md): credentials and the free tier.
- [API reference](../api.md): every route in one place.
