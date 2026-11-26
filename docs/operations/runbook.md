# Runbook

This page is for whoever is operating the production backend when something looks wrong. It lists the checks to run first, then symptom by symptom what usually causes each problem and how to confirm and fix it. Every command here runs on the droplet or against the production database, so read each one before running it; the queries that change data are marked.

## Terms used on this page

- **The droplet**: the production VM running `illume-server`, `illume-worker` and `illume-beat`.
- **Stuck repository**: a repository whose `status` is neither `ready` nor `failed` and is no longer changing.
- **Lease**: the expiry time a sync writes before it starts work, so a killed sync cannot hold a repository forever.
- **psql**: the Postgres command-line client. Connect with the `SYNC_DATABASE_URL` from the environment file; never print the file's values into a shared log.

## First checks

```bash
docker ps --format '{{.Names}}\t{{.Status}}'           # all three up, and for how long
curl -s localhost:8000/healthz                          # {"status":"ok","checks":{"redis":"ok"}}
docker logs --tail 200 illume-server
docker logs --tail 200 illume-worker
docker logs --tail 50  illume-beat
df -h /                                                 # disk, for the clone cache and logs
free -m                                                 # memory, for the worker
```

| Check       | Healthy                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------ |
| `docker ps` | three containers `Up`; a short uptime on the worker alone is a memory recycle, not a crash |
| `/healthz`  | 200 and `"redis": "ok"`; a 503 names the failing check                                     |
| worker log  | `celery@… ready`, then task lines                                                          |
| beat log    | `Scheduler: Sending due task sweep-due-repositories` every 10 minutes                      |

`/healthz` deliberately does not probe Postgres ([why](../testing/frontend-and-e2e.md#why-healthz-has-no-database-probe)). To check the database, load any signed-in page, or run `SELECT 1` with psql.

The nightly [production smoke run](ci-cd.md#production-smoke) is the quickest end-to-end signal; its last result is on the repository's Actions tab, and it can be re-run by hand.

## Profiling an ingest

Every stage logs one `stage_timer` line with its wall time and, when measured, its memory peak:

```bash
docker logs illume-worker 2>&1 | grep stage_timer
```

Concurrent stages log `mem=not_measured`; compare their walls with the matching `*_join` line, which should be close to the longer of the pair, not their sum. [Reading the stage timer](../pipeline/concurrency-and-failure.md#reading-the-stage-timer) explains every field.

## Symptoms

### A repository shows progress forever

**Cause.** The worker was killed mid-ingest (a deploy, an out-of-memory kill). Celery acknowledged the task on delivery, so it is gone, and the row stays in `cloning`, `parsing` or `embedding` with nothing to move it. Re-ingest refuses the row because its status is neither `ready` nor `failed`.

**Confirm.**

```sql
SELECT id, repo_number, name, status, updated_at
FROM repositories
WHERE status NOT IN ('ready', 'failed') AND updated_at < now() - interval '30 minutes';
```

Then check the worker log for that repository's id and for the container restart time (`docker ps`).

**Fix** (writes data). Mark it failed, then the owner can re-ingest from the UI:

```sql
UPDATE repositories SET status = 'failed' WHERE id = '<id>';
```

See [a worker killed mid-ingest](../pipeline/concurrency-and-failure.md#a-worker-killed-mid-ingest).

### Ingestion fails immediately

| Log shows                           | Cause                                                                                                                             |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `git: not found` or similar         | the image lost `git` from its runtime stage                                                                                       |
| a clone error naming authentication | the user's stored GitHub token was revoked or lacks access; the masked URL hides the token                                        |
| `PendingRollbackError`              | an exception path that skipped `db.rollback()`; see [failure and retry](../pipeline/concurrency-and-failure.md#failure-and-retry) |

The task retries up to three times, 10 seconds apart, before the row stays `failed`.

### The worker keeps restarting or a large repository never finishes

**Cause.** Memory. Either the box is out of memory or the per-child limit recycled the worker mid-task.

**Confirm.** `docker inspect illume-worker --format '{{.State.OOMKilled}} {{.RestartCount}}'`, `dmesg | grep -i oom`, and the `stage_timer` lines for the last stage that logged.

**Fix.** Confirm the worker command still has `--concurrency=1` (the prefork default follows the container's CPU count and can be higher). A single repository too large for the box has no fix short of more memory.

### Auto-update has stopped

**Confirm**, in order:

1. Beat is running and logging `sweep-due-repositories` every 10 minutes.
2. The global switch `AUTO_UPDATE_ENABLED` in [`app/tasks/autoupdate.py`](../../server/app/tasks/autoupdate.py) is on in the deployed commit.
3. The repositories are due:

```sql
SELECT repo_number, name, auto_update_enabled, sync_status, next_sync_at,
       sync_lease_expires_at, consecutive_sync_failures, last_sync_error
FROM repositories
WHERE auto_update_enabled
ORDER BY next_sync_at;
```

| What you see                                               | Meaning                                                                  |
| ---------------------------------------------------------- | ------------------------------------------------------------------------ |
| `sync_status = 'updating'`, lease in the past              | a sync was killed; the next sweep reclaims it once the lease has expired |
| `sync_status = 'failed'`, high `consecutive_sync_failures` | backing off; `last_sync_error` names the cause                           |
| `next_sync_at` far in the future                           | back-off, or a long interval                                             |
| all rows look right but nothing happens                    | the worker is not consuming the `sync` queue; check its `-Q celery,sync` |

The settings panel's manual sync button enqueues the same task. See [auto-update](../pipeline/sync.md).

**Beat re-fires everything after a deploy** means the state mount is missing, so the schedule file did not survive.

### Syncs are slow, or the clone cache is always empty

**Cause.** The cache mount is missing or at the wrong container path; the cache then writes into the container's ephemeral layer and every deploy empties it. Nothing logs this, by design.

**Confirm.** `docker inspect illume-worker --format '{{json .Mounts}}'` shows `/tmp/illume/clone_cache`, and `ls /home/tejas/illume_data/clone_cache` on the host lists repository directories.

See [the clone cache](../pipeline/clone-cache.md).

### Everyone is signed out, or sign-in does not stick

**Cause.** The session cookie is being dropped. `DOMAIN` in the environment file is not a bare hostname shared by the web and API origins, or `ENVIRONMENT` is not `production` behind HTTPS so `Secure` is wrong.

**Confirm.** The production smoke `setup` project fails with a message naming `DOMAIN`. In a browser, the `Set-Cookie` header on `POST /api/v1/auth/login` shows the `Domain` attribute.

A changed `SECRET_KEY` also signs everyone out, because every existing JWT stops verifying.

### Chat answers fail

| Symptom                                       | Likely cause                                                                                                               |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| "Failed to get response" for every user       | the embedding call is failing: `OPENAI_API_KEY` is invalid or out of credit                                                |
| fails for keyless users only                  | the operator's free-tier credential (`AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`) is invalid, or the free allowance is used up |
| fails for one BYOK user                       | that user's key; they can replace it in Settings                                                                           |
| "No relevant code was found" for a repository | its embeddings are missing; re-ingest it                                                                                   |
| Deep or Auto runs end as `interrupted`        | a deploy or crash cut the run; see [the chat agent](../retrieval/agent.md#persistence)                                     |

The production smoke `journey` project makes one real chat turn every night, which is the check that the operator's provider still accepts its key.

### Stored keys stop working for every user

**Cause.** `CREDENTIAL_ENCRYPTION_KEY` changed, so every stored AI key and GitHub token fails to decrypt. Restore the previous value. There is no re-encryption tool. See [BYOK and encryption](../security/byok-and-encryption.md).

### The contact form returns 503 or 502

`RESEND_API_KEY` or `CONTACT_TO_EMAIL` is empty (503), or Resend rejected the sender (502), usually because `CONTACT_FROM_EMAIL` is quoted or its domain is not verified on that Resend account.

### MCP clients cannot connect

| Symptom                             | Check                                                                             |
| ----------------------------------- | --------------------------------------------------------------------------------- |
| 401 with `WWW-Authenticate: Bearer` | the token is missing, revoked or expired; the user mints a new one in Settings    |
| 404 for every request               | the `MCP_ENABLED` kill switch is off in the deployed commit                       |
| 413                                 | a request body over 1 MiB                                                         |
| an error result naming a limit      | a per-user rate limit; the message gives the seconds until the window resets      |
| a Host or Origin rejection          | the client's `Host` is not on the allowed list derived from `GITHUB_REDIRECT_URL` |
| a protocol error on every call      | the client did not send `Accept: application/json, text/event-stream`             |

The nightly smoke run's MCP step reproduces a full `initialize`, `tools/list` and `tools/call`. See [the MCP server](../mcp/server.md).

### A deploy ran but the old code is still live

1. CI must have succeeded for that commit **on a push**; a pull-request run or the nightly run deploys nothing.
2. The deploy log must show the pull succeeding. With `set -e`, a failed pull stops the script before any container is replaced.
3. If the migration step failed, the API is new and the worker and beat are old. Fix the migration and push again.

### The disk is filling

The clone cache is bounded by `CLONE_CACHE_MAX_BYTES` and evicts least-recently-used repositories ([eviction](../pipeline/clone-cache.md#eviction)). Container logs are capped at 100 MB each by the deploy's log options. Old images are not pruned automatically: `docker image prune` removes dangling ones.

## Things never to do

- **Do not run `alembic downgrade` in production** without reading the revision's `downgrade()`: several drop columns or data.
- **Do not run `app/scripts/clean.py` or `make db-truncate`** against production. Both empty every table in whatever database `SYNC_DATABASE_URL` points at.
- **Do not set `OPENAI_BASE_URL`** in the environment file; it redirects every embedding call.
- **Do not raise the worker's concurrency** to clear a queue; it multiplies peak memory.
- **Do not paste the environment file** into an issue, chat or log.

## Design trade-offs and limits

- **Manual recovery for killed ingests.** There is no lease on the ingest path, so a stuck row needs a hand-written `UPDATE`.
- **No metrics or alerting.** Diagnosis is logs, `/healthz`, the database and the nightly smoke run; nothing pages anyone.
- **No database probe.** `/healthz` can be green while Postgres is unreachable.
- **No admin interface.** Every fix in this page is a shell or SQL command.

## Related documentation

- [Deployment](deployment.md): the containers and their state.
- [CI and CD](ci-cd.md): the deploy and smoke workflows.
- [Concurrency and failure](../pipeline/concurrency-and-failure.md): how the ingest task fails.
- [Auto-update](../pipeline/sync.md): the sweep, leases and back-off.
- [Constants](../reference/constants.md): the tunables named here.
