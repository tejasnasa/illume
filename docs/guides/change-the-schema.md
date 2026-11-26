# Change the database schema

This guide walks through changing a table or adding one: editing the SQLAlchemy model, writing the Alembic revision, testing it against a throwaway database, and getting it to production. Migrations are where this project's mistakes cost the most, because the default Alembic target on a configured machine is the **production** database. Read [the data model](../reference/data-model.md) first.

## Terms used on this page

- **Model**: a SQLAlchemy class in [`server/app/models/`](../../server/app/models/), one table per module.
- **Revision**: one Alembic migration file in [`server/alembic/versions/`](../../server/alembic/versions/), with an `upgrade()` and a `downgrade()`.
- **Head**: the newest revision. The chain must have exactly one.
- **Drift**: a difference between what the models declare and what the migrated schema actually contains.
- **Autogenerate**: Alembic's command that compares the models with a live database and drafts a revision.

## Read this first: which database Alembic touches

```mermaid
flowchart TD
    A["uv run alembic ..."] --> E["alembic/env.py"]
    E --> S["settings.SYNC_DATABASE_URL"]
    S --> F{"Set in the shell?"}
    F -->|"yes"| T["that database"]
    F -->|"no"| X["server/.env<br/>which points at PRODUCTION"]
```

`alembic/env.py` reads `settings.SYNC_DATABASE_URL`, and `Settings` falls back to `server/.env`. On the maintainer's machine that file points at production. So:

| Command                                         | Database it touches                 | Safe locally                             |
| ----------------------------------------------- | ----------------------------------- | ---------------------------------------- |
| `make migrate-test`                             | the test stack on port 5433         | yes                                      |
| `uv run pytest tests/migrations`                | scratch databases on the test stack | yes                                      |
| `make migrate` or `uv run alembic upgrade head` | whatever `server/.env` names        | **no**                                   |
| `make migration m="..."` (autogenerate)         | reads whatever `server/.env` names  | only with `SYNC_DATABASE_URL` overridden |
| `make downgrade`                                | whatever `server/.env` names        | **no**                                   |

Production is migrated by the deploy, never from a laptop ([what a deploy does](../operations/deployment.md#what-a-deploy-does)).

## Steps

### 1. Change the model

Edit the module in `app/models/`. For a new table, create a module, export the class from [`app/models/__init__.py`](../../server/app/models/__init__.py), and **add the module to the import list in [`alembic/env.py`](../../server/alembic/env.py)**. Autogenerate only sees modules that `env.py` imports, so a missing import produces a revision that silently leaves the new table out.

Conventions the existing models follow:

- UUID primary keys, and `repository_id` foreign keys with `ondelete="CASCADE"`, so deleting a repository (and re-ingesting, which deletes and recreates the row) clears every child row.
- A unique constraint wherever a concurrent insert could duplicate a row; the parse stage's `ON CONFLICT DO NOTHING` depends on `uq_file_repo_path`.
- Secrets stored through [`app/core/crypto.py`](../../server/app/core/crypto.py), never in plain text ([BYOK and encryption](../security/byok-and-encryption.md)).

### 2. Draft the revision against the test database

Start the test stack, bring it to head, and run autogenerate with the URL overridden:

```bash
make test-infra
make migrate-test
cd server
SYNC_DATABASE_URL=postgresql://illume:test@localhost:5433/illume_test \
  uv run alembic revision --autogenerate -m "add thing table"
```

Then read the draft line by line. Autogenerate compares tables, columns, plain indexes and foreign keys well. The Postgres-specific parts of this schema are written by hand in the existing revisions, and you should copy them rather than trust a draft:

| Feature                                     | How the existing revisions write it                                                                                                                          |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| the HNSW vector index                       | raw `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)` in [`a7b8c9d0e1f2`](../../server/alembic/versions/a7b8c9d0e1f2_add_embeddings_hnsw_index.py) |
| the stored generated `search_tsv` column    | raw `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in [`c9d0e1f2a3b4`](../../server/alembic/versions/c9d0e1f2a3b4_add_lexical_trigram_and_cochange.py)           |
| partial trigram GIN indexes                 | raw `CREATE INDEX CONCURRENTLY IF NOT EXISTS ... WHERE` in the same revision                                                                                 |
| Postgres enum types (`dep_type` and others) | a new value needs `ALTER TYPE ... ADD VALUE`; autogenerate does not alter an existing enum                                                                   |
| data backfills                              | an explicit `UPDATE` in `upgrade()`, as in the credential-encryption revision                                                                                |

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction; the trigram revision shows how it steps outside Alembic's. Adding a stored generated column rewrites the whole table under an exclusive lock, which that revision's docstring also discusses.

Recent revisions use hand-picked twelve-character hex ids, such as `d9e0f1a2b3c4`, which revises `c8d9e0f1a2b3`. Set `down_revision` to the current head.

### 3. Make the upgrade safe to run twice

The deploy runs `alembic upgrade head` on every push to `main`, and a failed deploy can leave a revision partly applied. Write `upgrade()` so that a second run does nothing harmful. The credential-encryption revision, [`d9e0f1a2b3c4_encrypt_stored_credentials.py`](../../server/alembic/versions/d9e0f1a2b3c4_encrypt_stored_credentials.py), checks `is_envelope` before encrypting a value, so already-encrypted rows are skipped.

Write a real `downgrade()` too. Several existing ones drop columns or data; say so in the docstring.

### 4. Test it

| Test                                                                                | What it catches                                                                                                                                                                 |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`tests/migrations/test_migrate.py`](../../server/tests/migrations/test_migrate.py) | more than one head, a non-linear chain, an unreachable revision, an empty no-op revision, a non-idempotent `upgrade head`, and drift between the models and the migrated schema |
| a new `tests/migrations/test_<name>_migration.py`                                   | the revision's own behaviour: it follows its parent, upgrade then downgrade then upgrade works, backfills produce the right rows                                                |

The per-revision tests run against a `scratch_database`: an empty database created on the test server for one test and dropped afterwards. The fixture is defined in [`test_agent_runs_migration.py`](../../server/tests/migrations/test_agent_runs_migration.py) and imported by the others.

**One existing test will fail by design.** The newest revision's test asserts it is the head: `test_the_revision_follows_the_conversations_and_is_the_head` in [`test_credential_encryption_migration.py`](../../server/tests/migrations/test_credential_encryption_migration.py). Move that "is the head" assertion into your new revision's test.

Then run the whole backend suite. Factories in [`tests/factories.py`](../../server/tests/factories.py) build rows for many tests, so a new required column breaks every factory that does not set it. CI applies migrations as a separate step before pytest, which avoids the race in which several xdist workers try to migrate a fresh database at once ([backend tests](../testing/backend.md)).

### 5. Update everything that reads the table

- API response models and the client types, if the column is exposed ([add an endpoint](add-an-endpoint.md)).
- The `.illume` exporter, if the table is part of what an export contains ([the export format](../interfaces/illume-export.md)).
- The re-ingest and sync paths, if the column holds per-repository data a sync must keep current ([auto-update](../pipeline/sync.md)).
- [`app/scripts/clean.py`](../../server/app/scripts/clean.py), which truncates tables in foreign-key-safe order, for a new table.
- [The data model](../reference/data-model.md): the table section and the revision list.

### 6. Ship it

Pushing to `main` runs CI, and a green CI triggers the deploy. The deploy starts the new API container, runs `alembic upgrade head` inside it, and then replaces the worker and beat ([CI and CD](../operations/ci-cd.md#deploy)). Between those steps the old worker runs against the new schema, so a revision must not break the code it replaces:

| Change                    | Safe in one deploy?                                                                    |
| ------------------------- | -------------------------------------------------------------------------------------- |
| add a nullable column     | yes                                                                                    |
| add a table               | yes                                                                                    |
| add a `NOT NULL` column   | only with a server default or a backfill in the same revision                          |
| rename or drop a column   | no; stop reading it in one deploy, drop it in the next                                 |
| change a vector dimension | no; a different embedding model is a migration and a full re-embed of every repository |

If the migration step fails, the deploy stops with the new API and the old worker and beat. Fix the revision and push again ([runbook](../operations/runbook.md#a-deploy-ran-but-the-old-code-is-still-live)).

## Checklist

- [ ] Model changed; new module exported and imported in `alembic/env.py`
- [ ] Revision drafted with `SYNC_DATABASE_URL` pointing at the test stack
- [ ] Draft read and corrected for vectors, generated columns, partial indexes, enums and backfills
- [ ] Idempotent `upgrade()`, real `downgrade()`
- [ ] Revision test added; the "is the head" assertion moved
- [ ] Full backend suite green; factories updated
- [ ] Readers, exporter, sync, `clean.py` and docs updated
- [ ] Change is compatible with the previous worker for one deploy

## Design trade-offs and limits

- **The production default.** `alembic` with no override targets production on a configured machine. The Makefile's `migrate-test` target and the test suite's port assertion are the only guards.
- **No pre-deploy migration check against production data.** The tests prove a revision works on an empty or seeded test database, not on production's row counts or data.
- **No expand-and-contract tooling.** Two-step changes are a discipline, not something the code enforces.
- **Downgrades are not exercised by the deploy.** A rollback means a new forward revision.

## Related documentation

- [Data model](../reference/data-model.md): every table and every revision.
- [Deployment](../operations/deployment.md): when the migration runs.
- [Backend tests](../testing/backend.md): the migration and drift tests.
- [CLI reference](../reference/cli.md#database): the Makefile database targets.
