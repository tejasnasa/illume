# The Data Model

Open any model module in `server/app/models/` and you will notice something missing. There is not a
single `relationship()` in the codebase — no `back_populates`, no lazy loading, no ORM traversal of
any kind. Every parent/child link is a plain foreign key with `ON DELETE CASCADE`, and every child is
loaded by an explicit query a service writes itself.

That one decision shapes the whole schema, and it is why this document can be short where an ORM-based
schema would need a diagram of object graphs: what exists here is one table, twelve rows of columns,
and a set of constraints that the pipeline depends on.

If you are reading for the first time,
[The shape of the schema](#the-shape-of-the-schema) is the map and
[Invariants worth preserving](#invariants-worth-preserving) is the part to remember. If you are about
to change the schema, read [Migrations](#migrations) before writing the revision.

## Contents

- [The shape of the schema](#the-shape-of-the-schema)
- [The tables](#the-tables)
  - [`users`](#users)
  - [`repositories`](#repositories)
  - [`files`](#files)
  - [`ast_symbols`](#ast_symbols)
  - [`dependencies`](#dependencies)
  - [`embeddings`](#embeddings)
  - [`commits`](#commits)
  - [`code_owners`](#code_owners)
  - [`pull_requests`](#pull_requests)
  - [`glossary_entries`](#glossary_entries)
  - [`onboarding_guides`](#onboarding_guides)
  - [`chat_messages`](#chat_messages)
- [Cross-cutting notes](#cross-cutting-notes)
- [Migrations](#migrations)
- [Invariants worth preserving](#invariants-worth-preserving)
- [Troubleshooting](#troubleshooting)
- [Design decisions and trade-offs](#design-decisions-and-trade-offs)
- [Related documentation](#related-documentation)

## The shape of the schema

Everything hangs off a `Repository`, which belongs to a `User`. Every other table is a direct child of
the repository, or a child of one of those children.

```mermaid
erDiagram
    users ||--o{ repositories : owns
    users ||--o{ chat_messages : writes
    repositories ||--o{ files : contains
    repositories ||--o{ commits : contains
    repositories ||--o{ pull_requests : contains
    repositories ||--o{ glossary_entries : contains
    repositories ||--o{ embeddings : contains
    repositories ||--o{ chat_messages : contains
    repositories ||--o| onboarding_guides : has
    files ||--o{ ast_symbols : contains
    files ||--o{ code_owners : has
    files ||--o{ embeddings : scopes
    ast_symbols ||--o{ dependencies : source
    ast_symbols ||--o{ dependencies : target
    ast_symbols ||--o{ glossary_entries : describes
```

Three rules in that diagram are load-bearing:

- **Everything cascades from `repositories`.** Deleting one row removes the entire analysis. There is
  no `SET NULL` and no `RESTRICT` anywhere in the schema.
- **`onboarding_guides` is one-to-*one*, not one-to-many.** Two concurrent writers depend on upserting
  a single row.
- **`dependencies` is a symbol-to-symbol edge, not a file-to-file one.** The file-level graph is
  collapsed at read time, never stored.

### No ORM relationships, and what follows

Two consequences, both deliberate:

1. **Deleting a `Repository` is a complete cleanup.** This is what makes re-ingest — delete and
   recreate under the same `id` and `repo_number` — correct without a hand-written teardown.
2. **Loading children is always an explicit query.** Nothing is lazily loaded, so there are no
   accidental N+1 queries hiding behind an attribute access. There is also no convenience traversal,
   and each service builds its own joins. That is why two parallel implementations of the same edge
   join exist — see [pipeline/graph.md](pipeline/graph.md#why-two-implementations-of-the-same-join).

## The tables

Types are SQLAlchemy column types. **"Server default"** means the database supplies a value on insert;
**"Python default"** means SQLAlchemy does, and a raw-SQL insert must supply it itself. That
distinction has bitten before — see [Columns with Python-side defaults only](#columns-with-python-side-defaults-only).

### `users`

| Column                    | Type         | Notes                                                       |
| ------------------------- | ------------ | ----------------------------------------------------------- |
| `id`                      | UUID         | PK, server default `gen_random_uuid()`                       |
| `name`                    | String       | NOT NULL                                                     |
| `email`                   | String       | NOT NULL, unique, indexed                                    |
| `password`                | String       | Nullable — NULL for GitHub-only accounts                     |
| `avatar_url`              | String       | Nullable                                                     |
| `github_id`               | String       | Nullable, unique                                             |
| `github_access_token`     | String       | Nullable; used for cloning, stored plaintext                 |
| `created_at`              | DateTime(tz) | NOT NULL, server default `now()`                             |
| `ai_provider`             | String       | Nullable — the BYOK provider key                             |
| `ai_api_key`              | String       | Nullable — the user's LLM key, stored plaintext              |
| `ai_model`                | String       | Nullable                                                     |
| `ai_key_validated_at`     | DateTime(tz) | Nullable; set when the save-time probe succeeded             |
| `free_ingest_used`        | Boolean      | NOT NULL, server default `false`                             |
| `free_chat_messages_used` | Integer      | NOT NULL, server default `0`                                 |

The four `ai_*` columns are the BYOK store — see [auth.md](auth.md#the-ai-credential-store). The two
`free_*` columns are the quota counters, claimed with a conditional `UPDATE` — see
[pipeline/generation.md](pipeline/generation.md#the-quota).

`password` being nullable is what lets a GitHub-only account exist, and is also the source of a known
defect: a password login against such an account raises rather than returning `401`. See
[auth.md](auth.md#password-storage).

### `repositories`

The most conceptually loaded table in the schema: identity, lifecycle state, two commit watermarks,
and the entire auto-update schedule.

| Column                       | Type         | Notes                                                                     |
| ---------------------------- | ------------ | ------------------------------------------------------------------------- |
| `id`                         | UUID         | PK, server default `gen_random_uuid()`                                    |
| `repo_number`                | Integer      | NOT NULL, **unique**, Postgres `Identity()`; lookups are still scoped per user |
| `user_id`                    | UUID         | FK → `users.id`, CASCADE, NOT NULL                                        |
| `github_url`                 | String       | NOT NULL                                                                  |
| `name`                       | String       | NOT NULL                                                                  |
| `default_branch`             | String       | Nullable                                                                  |
| `primary_language`           | String       | Nullable                                                                  |
| `status`                     | Enum         | NOT NULL, default `pending`                                               |
| `detected_stack`             | JSONB        | Nullable; languages, frameworks, databases, CI, infrastructure            |
| `entry_points`               | JSONB        | Nullable                                                                  |
| `architecture_summary`       | Text         | Nullable; the generated brief                                             |
| `ingested_branch`            | String       | Nullable                                                                  |
| `ingested_commit_sha`        | String       | Nullable — the **deterministic watermark**                                |
| `analysis_commit_sha`        | String(40)   | Nullable — the **LLM watermark**                                          |
| `created_at`                 | DateTime(tz) | NOT NULL, server default `now()`                                          |
| `updated_at`                 | DateTime(tz) | NOT NULL, server default `now()`, updated on write                        |
| `auto_update_enabled`        | Boolean      | NOT NULL, server default `false`                                          |
| `auto_update_interval_hours` | Integer      | NOT NULL, server default `6`                                              |
| `next_sync_at`               | DateTime(tz) | Nullable — when the next sync is due                                      |
| `last_synced_at`             | DateTime(tz) | Nullable                                                                  |
| `sync_status`                | String(32)   | NOT NULL, server default `idle`                                           |
| `sync_lease_expires_at`      | DateTime(tz) | Nullable — the sync lock                                                  |
| `sync_generation`            | UUID         | Nullable — identifies one sync attempt                                    |
| `last_sync_error`            | Text         | Nullable                                                                  |
| `consecutive_sync_failures`  | Integer      | NOT NULL, server default `0`                                              |
| `last_sync_summary`          | JSONB        | Nullable; counts from the most recent sync                                |

**Two state machines live on this row, and keeping them apart is the design.**

| Column        | Values                                                  | Drives                                        |
| ------------- | ------------------------------------------------------- | --------------------------------------------- |
| `status`      | `pending → cloning → parsing → embedding → ready`, `failed` | Whether the product is usable at all          |
| `sync_status` | `idle │ queued │ checking │ updating │ failed`              | The settings panel's poll                     |

`status` stays `ready` during a background update. The graph endpoint, the navigation, and the
repository page all key off `status='ready'` — so leaving it alone is exactly what keeps the product
usable while a sync runs. `sync_status` is the narrower machine that reports the update.

**Two watermarks, one per kind of staleness.** `ingested_commit_sha` records what the deterministic
data (files, symbols, dependencies, fan metrics, criticality) reflects. `analysis_commit_sha` records
what the LLM artefacts (glossary, reading order, brief, embeddings) reflect. A sync short-circuits only
when **both** equal the remote head, so a partially failed update resumes with only the missing half.
See [pipeline/sync.md](pipeline/sync.md).

**`sync_lease_expires_at` is load-bearing.** A deploy does `docker stop` → `docker rm` → `docker run`,
so a SIGTERM-then-SIGKILL mid-sync would leave `sync_status='updating'` forever without an expiry. The
sweep's claim predicate checks that the lease has expired before claiming a stale-locked row.

**Index:** a **partial** index on `next_sync_at` where `auto_update_enabled` is true. It keeps the
sweep's "what is due?" query cheap no matter how many repositories have auto-update off — which is
most of them.

### `files`

| Column                | Type         | Notes                                                     |
| --------------------- | ------------ | ---------------------------------------------------------- |
| `id`                  | UUID         | PK                                                         |
| `repository_id`       | UUID         | FK → `repositories.id`, CASCADE, NOT NULL                  |
| `path`                | String       | NOT NULL                                                   |
| `language`            | String       | Nullable                                                   |
| `loc`                 | Integer      | Nullable — lines of code                                   |
| `fan_in`              | Integer      | NOT NULL, **Python default** 0                             |
| `fan_out`             | Integer      | NOT NULL, **Python default** 0                             |
| `criticality`         | String       | Nullable — `critical` / `caution` / `safe`                 |
| `criticality_reasons` | JSONB        | Nullable — why the score came out as it did                |
| `change_frequency`    | Float        | Nullable                                                   |
| `has_tests`           | Boolean      | NOT NULL, **Python default** `false`                       |
| `git_last_modified`   | DateTime(tz) | Nullable                                                   |
| `created_at`          | DateTime(tz) | NOT NULL, server default `now()`                           |

**Unique on `(repository_id, path)`**, named `uq_file_repo_path`. This is the constraint that makes
concurrent ingestion of the same repository insert-once rather than duplicate — the parse stage's
insert is `ON CONFLICT DO NOTHING` against exactly this index.

Only `path`, `language`, `loc`, and `created_at` come from the parser. `fan_in`, `fan_out`,
`criticality`, `has_tests`, and `git_last_modified` are all written later in the pipeline.
`git_last_modified` and `has_tests` come from the git analyzer — which is why criticality scoring must
run *after* it. Scoring first grades every file against `NULL` and `False`, and the unit tests inject
those values directly, so they pass either way and cannot catch a regression here.

### `ast_symbols`

| Column                    | Type         | Notes                                                    |
| ------------------------- | ------------ | -------------------------------------------------------- |
| `id`                      | UUID         | PK                                                       |
| `file_id`                 | UUID         | FK → `files.id`, CASCADE, NOT NULL                       |
| `kind`                    | Enum         | `function`/`class`/`method`/`import`/`variable`/`module` |
| `name`                    | String       | NOT NULL; `"<anonymous>"` for unnamed constructs         |
| `start_line` / `end_line` | Integer      | Nullable                                                 |
| `source_code`             | Text         | Nullable                                                 |
| `cyclomatic_complexity`   | Integer      | Nullable                                                 |
| `docstring`               | Text         | Nullable                                                 |
| `created_at`              | DateTime(tz) | NOT NULL, server default `now()`                         |

Indexed on `file_id`, and on `(file_id, kind)` for the filtered lookups the graph builder and the
embedder do.

`kind` is wider than the product uses. Three consumers each take a different subset:

| Consumer      | Kinds it reads                          |
| ------------- | --------------------------------------- |
| Embedder      | `function`, `class`, `method`           |
| Graph builder | `function`, `class`                     |
| Dependency resolver | matches through `import` symbols |

The extra kinds are retained rather than pruned because each of those readers needs something the
others do not.

### `dependencies`

| Column             | Type | Notes                                       |
| ------------------ | ---- | ------------------------------------------- |
| `id`               | UUID | PK                                          |
| `source_symbol_id` | UUID | FK → `ast_symbols.id`, CASCADE, NOT NULL    |
| `target_symbol_id` | UUID | FK → `ast_symbols.id`, CASCADE, NOT NULL    |
| `dep_type`         | Enum | `imports`/`calls`/`inherits`/`instantiates` |

Unique on `(source_symbol_id, target_symbol_id)` — the safety net that makes a repeated resolve insert
nothing rather than duplicate an edge.

> **Only `imports` is ever written.** The enum declares four relationship kinds; the resolver produces
> one. So `calls`, `inherits`, and `instantiates` never appear in this table. The embedder reads
> `dep_type == "calls"` when building its `Called by:` and `Calls:` lines, which means those lines are
> **always empty** and the call graph does not exist anywhere in the system.
>
> This is the most consequential gap in the schema: the column is ready for data that is never
> produced, and a reader who trusts `dep_type` will build on a graph that is not there.

### `embeddings`

| Column          | Type           | Notes                                                              |
| --------------- | -------------- | ------------------------------------------------------------------- |
| `id`            | UUID           | PK                                                                   |
| `source_id`     | UUID           | NOT NULL, **no foreign key** — points at different tables per type    |
| `file_id`       | UUID           | FK → `files.id`, CASCADE, nullable                                   |
| `repository_id` | UUID           | FK → `repositories.id`, CASCADE, NOT NULL                            |
| `chunk_text`    | Text           | NOT NULL — the pre-rendered text that was embedded                   |
| `embedding`     | `Vector(1536)` | NOT NULL                                                             |
| `source_type`   | Enum           | `symbol`/`commit`/`pull_request`/`document`/`file`                   |
| `chunk_hash`    | String(64)     | Nullable; SHA-256 of `chunk_text`, used for incremental reconcile    |

Unique on `(repository_id, source_type, source_id)`.

Three things here deserve attention:

1. **`source_id` has no foreign key.** It points into `ast_symbols`, `commits`, `pull_requests`, or
   `files` depending on `source_type`, so referential integrity is not enforced and a stale embedding
   can outlive its source row. Deleting the parent repository still cleans up through `repository_id`.
2. **The 1536 dimensions are baked into the schema.** Changing the embedding model is a migration, not
   a configuration change.
3. **There is no live vector index.** An HNSW index on `embedding` was created in an early migration
   and later dropped, and nothing recreated it, so similarity search runs as an exact scan. That is
   correct, just slower — and worth knowing before trusting any claim about "indexed" vector search.

`chunk_text` stores the **rendered** text, not raw source: for a symbol, that means the file path, the
kind and name, a definition or docstring, and the source body. Storing the render is what makes a
retrieval result readable without a second lookup. See
[pipeline/retrieval.md](pipeline/retrieval.md#part-1--building-the-index).

### `commits`

| Column               | Type         | Notes                                        |
| -------------------- | ------------ | -------------------------------------------- |
| `id`                 | UUID         | PK, Python default                           |
| `repository_id`      | UUID         | FK → `repositories.id`, CASCADE, NOT NULL     |
| `hash`               | String       | NOT NULL                                      |
| `author_name`        | String       | NOT NULL                                      |
| `author_email`       | String       | NOT NULL                                      |
| `message`            | Text         | NOT NULL                                      |
| `files_changed`      | Integer      | NOT NULL, **Python default** 0                |
| `changed_files_list` | JSONB        | Nullable                                      |
| `authored_at`        | DateTime(tz) | NOT NULL                                      |

Unique on `(repository_id, hash)` — **not** on `hash` globally. A global unique constraint existed
briefly and was removed, because the same commit legitimately appears in two repositories: forks,
mirrors, or the same repository ingested by two users.

### `code_owners`

| Column              | Type    | Notes                                     |
| ------------------- | ------- | ----------------------------------------- |
| `id`                | UUID    | PK, Python default                        |
| `file_id`           | UUID    | FK → `files.id`, CASCADE, NOT NULL, **unique** |
| `primary_owner`     | String  | Nullable                                  |
| `contributors`      | JSONB   | Nullable; names with percentages           |
| `bus_factor`        | Integer | NOT NULL, **Python default** 0             |
| `is_knowledge_silo` | Boolean | NOT NULL, **Python default** `false`       |

One row per file, enforced by the unique constraint on `file_id`. A file is a knowledge silo when
exactly one person has ever changed it.

> The upsert that writes this table **does not include `bus_factor` in its update set**, so on a
> re-analysis the column can hold a stale value while `contributors` is current. See
> [pipeline/git-intelligence.md](pipeline/git-intelligence.md).

### `pull_requests`

| Column          | Type         | Notes                                  |
| --------------- | ------------ | -------------------------------------- |
| `id`            | UUID         | PK, Python default                     |
| `repository_id` | UUID         | FK → `repositories.id`, CASCADE, NOT NULL |
| `number`        | Integer      | NOT NULL                               |
| `title`         | String       | NOT NULL                               |
| `description`   | Text         | Nullable                               |
| `author`        | String       | NOT NULL                               |
| `reviewers`     | JSONB        | Nullable                               |
| `files_changed` | Integer      | NOT NULL, **Python default** 0         |
| `merged_at`     | DateTime(tz) | Nullable; only merged PRs are stored   |

Unique on `(repository_id, number)`. Only **merged** PRs are stored, up to 200 per repository.

### `glossary_entries`

| Column          | Type    | Notes                                       |
| --------------- | ------- | ------------------------------------------- |
| `id`            | UUID    | PK, Python default                          |
| `repository_id` | UUID    | FK → `repositories.id`, CASCADE, NOT NULL    |
| `symbol_id`     | UUID    | FK → `ast_symbols.id`, CASCADE, **nullable** |
| `name`          | String  | NOT NULL                                     |
| `definition`    | Text    | NOT NULL                                     |
| `file_path`     | String  | Nullable                                     |
| `line_number`   | Integer | Nullable                                     |

`symbol_id` is nullable so that a definition survives the symbol it described being removed by a
re-analysis — the prose is still useful even when the code it came from is gone. Entries named
`"<anonymous>"` are filtered at the API layer rather than deleted here.

### `onboarding_guides`

| Column               | Type         | Notes                                                |
| -------------------- | ------------ | ---------------------------------------------------- |
| `id`                 | UUID         | PK, Python default                                   |
| `repository_id`      | UUID         | FK → `repositories.id`, CASCADE, NOT NULL, **unique** |
| `reading_order`      | JSONB        | Nullable — the ordered file list with annotations     |
| `critical_files`     | JSONB        | Nullable                                              |
| `architecture_brief` | JSONB        | Nullable — was `Text`, converted to JSONB             |
| `pdf_path`           | Text         | Nullable; unused in the current product               |
| `created_at`         | DateTime(tz) | NOT NULL, server default `now()`                      |
| `updated_at`         | DateTime(tz) | NOT NULL, server default `now()`, updated on write    |

**One row per repository**, and that is what makes the concurrency safe. The reading-order pass and
the brief pass run on separate threads at the same time and both write here. They do not clobber each
other because each writes **only the columns it owns** — the brief writes `architecture_brief`, the
reading order writes `reading_order`. The same property is what makes `embed ∥ brief` sound in the
ingest pipeline.

The `pdf_path` column is a leftover from a PDF export that never shipped. Nothing reads or writes it.

### `chat_messages`

| Column          | Type         | Notes                                        |
| --------------- | ------------ | -------------------------------------------- |
| `id`            | UUID         | PK                                           |
| `repository_id` | UUID         | FK → `repositories.id`, CASCADE, NOT NULL     |
| `user_id`       | UUID         | FK → `users.id`, CASCADE, NOT NULL            |
| `question`      | Text         | NOT NULL                                     |
| `answer`        | Text         | NOT NULL                                     |
| `sources`       | JSONB        | Nullable — the citation cards, stored as JSON |
| `created_at`    | DateTime(tz) | NOT NULL, server default `now()`             |

Storing `sources` as JSONB is why a reloaded conversation still shows its citations. The source
references are captured **at answer time**, so they survive the code underneath them changing — a
re-analysis that renumbers lines does not invalidate the transcript.

## Cross-cutting notes

### Two enums drift from their database types

Worth knowing because the failure is silent until it is not:

- **`repo_status`** declares `analyzing`, but the database type was created with `scoring`. Nothing
  assigns either value today — the pipeline writes `cloning`, `parsing`, `embedding`, `ready`, and
  `failed` — so the drift is currently harmless. Assigning `analyzing` would raise at runtime.
- **`source_type`** declares five values including `file`, but **no database type enforces any set**.
  The column was first added as a plain `String`, and the four-value enum that later replaced it was
  declared with `native_enum=False`, so PostgreSQL stores a varchar and never validates it. Adding a
  sixth type needs no migration — and a typo would not be caught by the database either.

### Columns with Python-side defaults only

Several NOT NULL columns have no server default: `files.fan_in`, `files.fan_out`, `files.has_tests`,
`code_owners.bus_factor`, `code_owners.is_knowledge_silo`, `commits.files_changed`, and
`pull_requests.files_changed`.

An insert through SQLAlchemy always supplies them. A raw SQL insert must too, or it fails on the
NOT NULL. The application never inserts these tables with raw SQL except through the bulk-upsert
helpers, which do supply the values.

### The engines, and where `get_db_context` actually lives

`server/app/core/database.py` owns both engines and two of the three session helpers:

| Engine         | Driver   | Used by               | Helper           |
| -------------- | -------- | --------------------- | ---------------- |
| `async_engine` | asyncpg  | FastAPI routes        | `get_async_db()` |
| `sync_engine`  | psycopg2 | Celery tasks, Alembic | `get_sync_db()`  |

The third helper, `get_db_context()`, is **not in that module** — it lives in
`server/app/tasks/ingest.py`. It wraps `get_sync_db` so that an exception propagating out of a `with`
block actually reaches the generator's rollback arm. It sits next to its only caller rather than with
the engines, which surprises people looking for it.

The split is **by caller, never by layer**: routes are async, background work is sync. See
[architecture.md](architecture.md#async-and-sync-are-split-by-caller).

## Migrations

Alembic targets `Base.metadata` and reads **`SYNC_DATABASE_URL`** — the same URL Celery uses.

There are **24 revisions**, forming one linear chain with a single head. The base revision creates the
`vector` extension, which is why the test compose file needs no init script.

Online migrations run with `NullPool` and `transaction_per_migration=True`, so each revision commits
independently and a failure leaves the database at the last complete revision rather than mid-way
through a batch.

Two conventions matter:

1. **New model modules must be imported explicitly in `alembic/env.py`**, or autogenerate will not see
   them. The current list names eleven of the twelve modules — `chat_message` is omitted, and is
   present only because importing any model module executes the package `__init__`, which imports it.
   That is an accident, not a design. Add a new model to the list explicitly rather than relying on
   the same accident.
2. **`uv run alembic upgrade head` from a development machine targets whatever `.env` points at** —
   which may be production. To migrate the test database, override the variable:

   ```bash
   SYNC_DATABASE_URL=postgresql://illume:test@localhost:5433/illume_test uv run alembic upgrade head
   ```

   The test suite does this itself; see [testing.md](testing.md).

## Invariants worth preserving

These are the properties the rest of the system relies on. Breaking one breaks something far away from
the change:

1. **A repository owns everything.** All analysis data cascades from `repositories`, so deletion is
   always complete and re-ingest is always safe.
2. **`(repository_id, path)` is unique on files.** This is what makes the parse idempotent under
   concurrent workers.
3. **`(source_symbol_id, target_symbol_id)` is unique on dependencies.** A repeated resolve inserts
   nothing instead of doubling the graph.
4. **`(repository_id, source_type, source_id)` is unique on embeddings.** Re-embedding updates in
   place rather than accumulating duplicates.
5. **One `onboarding_guides` row per repository.** The concurrent reading-order and brief writes
   depend on upserting a single row, each owning different columns.
6. **`repo_number` is unique and database-generated**, so it is never reused and never collides across
   concurrent inserts.

## Troubleshooting

**A re-analysis produces duplicate files.**

`uq_file_repo_path` is missing or was dropped. The parse stage's `ON CONFLICT DO NOTHING` depends on
it, so without the constraint two workers insert twice rather than failing.

**A newly added model does not appear in an autogenerated migration.**

It is not imported in `alembic/env.py`. Add it to the list.

**Criticality scores look uniform and wrong after a re-ingest.**

Scoring ran before the git analyzer. `git_last_modified` and `has_tests` were still `NULL`/`False`, so
every file graded identically. Check the stage ordering in the pipeline, not the scoring rules.

**A repository has a stale `bus_factor`.**

The `code_owners` upsert omits `bus_factor` from its update set, so re-analysis does not refresh it.

**Similarity search is slow on a large repository.**

Expected. There is no vector index; the search is an exact scan.

**`alembic upgrade head` changed the wrong database.**

It read `SYNC_DATABASE_URL` from `server/.env`, which points at whatever the developer configured.
Override the variable explicitly to target the test stack.

**An insert of `files` or `commits` fails on a NOT NULL with no value supplied.**

The column has a Python-side default only. A raw SQL insert must supply it.

## Design decisions and trade-offs

### Why no ORM relationships?

Because relationships invite lazy loading, and lazy loading in a sync session shared with a background
worker is a correctness hazard — an attribute access can emit a query at a moment nobody expected, in
a context where the session has already been closed or the transaction boundary has moved.

The cost is real: no `repo.files`, so every service writes its own loader, and the same join ends up
implemented twice in two places. That duplication is a known, accepted consequence rather than an
oversight — and it is why [pipeline/graph.md](pipeline/graph.md) warns you to check both when changing
edge derivation.

### Why is `onboarding_guides` one row per repository rather than one per artefact?

Because the two artefacts are written concurrently and each owns distinct columns. Two rows would need
a discriminator column, a partial unique index, and a rule for which row the read path picks. One row
with column-level ownership is simpler and makes the concurrent upsert safe by construction.

The cost is that the columns are not obviously grouped — `reading_order` and `architecture_brief` look
like they belong to different concerns and share a row.

### Why does `embeddings.source_id` not have a foreign key?

Because it is polymorphic: it points into four different tables depending on `source_type`, and
PostgreSQL has no foreign key that can express that. A single-column FK would have to point at one
table.

The alternative — four nullable FK columns — adds a check constraint to enforce exactly-one and makes
every query filter on which one is set. The cost of the choice made is that referential integrity is
unenforced, which is why `repository_id` carries the cascade instead: cleanup is complete at the
repository level even though it is not at the chunk level.

### Why store `chunk_text` rather than re-rendering it at read time?

Because the render depends on data that changes: a glossary definition, a docstring, a caller list.
Re-rendering at read time would return different text from what was embedded, so a citation card could
show text that does not match the vector that retrieved it. Storing the render keeps the citation
honest, and `chunk_hash` makes re-embedding incremental.

The cost is denormalisation: the same source appears twice, in `ast_symbols.source_code` and in
`embeddings.chunk_text`, and they can drift if a chunk is not re-embedded when its source changes.

### Why is `commits.hash` not globally unique?

Because the same commit genuinely appears in more than one repository — a fork, a mirror, or the same
public repository ingested by two users. A global unique constraint made the second ingest fail. The
scope that matters is per repository, so that is where the uniqueness is.

### Why does `status` stay `ready` during a sync instead of moving to an `updating` state?

Because the graph endpoint, the navigation, and the repository page all key off `status='ready'`. A
sync that moved the row out of `ready` would blank the product for every user for the duration of the
update — the graph would `409`, the navigation would degrade, and the page would fall back to a
progress view. The second state machine exists precisely so the visible one does not have to move.

The cost is that `status` alone cannot tell you a sync is running. `sync_status` can, and the settings
panel polls it.

## Related documentation

- [architecture.md](architecture.md) — the async/sync engine split and where each is used.
- [pipeline/ingestion.md](pipeline/ingestion.md) — the stages that write these tables, in order.
- [pipeline/sync.md](pipeline/sync.md) — the two watermarks, the lease, and the claim predicate.
- [pipeline/graph.md](pipeline/graph.md) — how symbol-level `dependencies` collapse into the file
  graph served to the client.
- [pipeline/retrieval.md](pipeline/retrieval.md) — how `chunk_text` is rendered and searched.
- [pipeline/git-intelligence.md](pipeline/git-intelligence.md) — the `commits` and `code_owners` tables, and the
  `bus_factor` staleness note above.
- [auth.md](auth.md) — the `users` table, the credential store, and why `password` is nullable.
