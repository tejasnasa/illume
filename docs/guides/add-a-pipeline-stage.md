# Add a pipeline stage

This guide walks through adding a new stage to the ingestion pipeline: a step that runs inside `ingest_repository` after the clone and writes something new for each repository. It covers where the code goes, the stage vocabulary and progress frames the client depends on, the rules for running beside other stages, the sync path, and the tests that must change. Read [ingestion](../pipeline/ingestion.md) and [concurrency and failure](../pipeline/concurrency-and-failure.md) first.

## Terms used on this page

- **Stage**: a named unit of work, a member of the `Stage` enum in [`app/services/_stages.py`](../../server/app/services/_stages.py).
- **Phase**: where a stage is in its lifecycle: `started`, `progress`, `done` or `failed` (the `Phase` enum).
- **Frame**: one JSON message on the Redis channel `task:{repo_id}:logs`, relayed to the browser by the ingest WebSocket.
- **Overlapped stage**: a stage run on a bounded thread pool beside another, from [`app/tasks/_parallel.py`](../../server/app/tasks/_parallel.py).

## Before you start

Decide three things, because each changes what you write:

| Question                                        | If yes                                                                                                                       |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Does it call a model?                           | it takes `llm: LLMConfig` keyword-only and must work with BYOK keys; see [generation](../pipeline/generation.md)             |
| Does it read data another stage writes?         | it must run after that stage; see [the load-bearing orderings](../pipeline/ingestion.md#two-orderings-that-are-load-bearing) |
| Could it run at the same time as another stage? | it follows [the scalars-only rule](../pipeline/concurrency-and-failure.md#the-scalars-only-rule)                             |
| Must a background sync keep it current?         | it needs an incremental form in the sync task; see [auto-update](../pipeline/sync.md)                                        |

## Steps

### 1. Write the service

Create `server/app/services/<name>.py`. Celery runs on the **sync** engine, so the service is synchronous and takes a `Session` (or, if it may be overlapped, only scalars and opens its own session with `get_db_context()`). Match the docstring style of the neighbouring services. If it writes rows, make the write idempotent (an upsert or a delete-then-insert) so a retried task does not duplicate data; [idempotency of each write](../pipeline/ingestion.md#idempotency-of-each-write) lists how every existing stage does it.

### 2. Add the stage to the vocabulary

Add a member to `Stage`:

```python
class Stage(StrEnum):
    ...
    BRIEF = "brief"
    MY_STAGE = "my_stage"
    READY = "ready"
```

The value is a bare string because frames are serialised with `json.dumps` and consumers compare strings.

### 3. Time it and publish its frames

Wrap the work in the stage timer, using the **same name** as the enum value, and publish a `started` frame and a `done` frame:

```python
publish(
    "my_stage_started",
    "Doing the new thing...",
    stage=Stage.MY_STAGE,
    phase=Phase.STARTED,
)
with stage("my_stage"):
    run_my_stage(db, repo.id)
    db.commit()
publish(
    "my_stage_complete",
    "The new thing is ready.",
    stage=Stage.MY_STAGE,
    phase=Phase.DONE,
)
```

The `publish(event, message, stage=…, phase=…)` closure is the one `run_full_analysis` in [`app/services/pipeline.py`](../../server/app/services/pipeline.py) already uses for `cochange` and `criticality`; copy that shape exactly. [every frame, in order](../interfaces/websockets.md#every-frame-in-order) lists them.

[`tests/unit/services/test_stages.py`](../../server/tests/unit/services/test_stages.py) parses every `stage(...)` call in `app/` and fails if the set differs from `Stage`, so a timer name and an enum value cannot drift apart. The client never infers that a stage finished because a later one started, which is why a stage that calls a model needs its explicit `done` frame.

An overlapped stage passes `measure_memory=False` to the timer, because the memory counters are process-wide and would mix the two threads' allocations; see [reading the stage timer](../pipeline/concurrency-and-failure.md#reading-the-stage-timer).

### 4. Put it in the right place

Add the call to `run_full_analysis` in [`app/services/pipeline.py`](../../server/app/services/pipeline.py) at the point its inputs exist. The ingest task in [`app/tasks/ingest.py`](../../server/app/tasks/ingest.py) calls it after the clone, and a full sync calls it too, so a stage placed there runs on both paths. If it can overlap with a neighbour, add a helper to `app/tasks/_parallel.py` that takes only `repo_id`, `github_url` and an `LLMConfig`, opens its own session, and is joined before anything that reads its output. Never pass an ORM object or a `Session` across threads.

### 5. Show it in the client

The progress board is driven by [`client/src/utils/ingestFlow.ts`](../../client/src/utils/ingestFlow.ts):

- add a node to `NODES` with the stage's id and a label;
- add it to the right column in `PIPELINE_COLUMNS`;
- check `seedFromStatus`, which reconstructs node states from the repository's `status` when the page loads mid-ingest, still proves only what the status proves.

[`useIngestStream`](../interfaces/websockets.md#the-client) turns frames into node states with no per-stage code, so nothing else on the client changes. The mobile app has its own board in `mobile/`; update it to match.

### 6. Keep it current on sync

If the stage's output must stay correct as a repository changes, decide what `sync_repository` in [`app/tasks/sync.py`](../../server/app/tasks/sync.py) does with it: rebuild it inside the deterministic transaction, regenerate it in the incremental model pass that follows it, or leave it to a full re-ingest. A sync publishes no frames, so nothing on the client changes for this.

### 7. Test it

| Test                                                                                                      | Why                                            |
| --------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| a unit test of the service in `tests/unit/services/`                                                      | the logic, with fakes                          |
| [`tests/integration/tasks/test_ingest_task.py`](../../server/tests/integration/tasks/test_ingest_task.py) | the eager pipeline persists the new output     |
| `test_stages.py`                                                                                          | passes once the enum and the timer agree       |
| [`tests/unit/utils/ingestFlow.test.ts`](../../client/tests/unit/utils/ingestFlow.test.ts)                 | the board knows the new node                   |
| `test_parallelism.py`, if overlapped                                                                      | the stages really overlap                      |
| `test_byok_credential_threading.py`, if it calls a model in a thread                                      | the user's key reaches the thread              |
| `test_sync_task.py`, if sync touches it                                                                   | a sync leaves the same state as a fresh ingest |

### 8. Document it

Add the stage to [ingestion](../pipeline/ingestion.md#the-stages), to the frame table in [WebSockets](../interfaces/websockets.md), and to the page that owns its subject.

## Checklist

- [ ] Service written on the sync engine, idempotent writes
- [ ] `Stage` member, `stage(...)` timer with the same name, `started` and `done` frames
- [ ] Placed after its inputs; overlapped only through `_parallel.py` with scalars
- [ ] `NODES` and `PIPELINE_COLUMNS` updated, web and mobile
- [ ] Sync behaviour decided
- [ ] Tests from the table above
- [ ] Docs updated

## Design trade-offs and limits

- **One task, not a chain.** A new stage makes every ingest longer unless it overlaps, and an exception anywhere fails the whole ingest and retries it from the start.
- **Memory.** The worker runs one ingest at a time on a memory-bound box; a stage that holds a whole repository in memory raises the floor for every ingest.
- **No per-stage retry.** A transient failure in the new stage retries the entire task.

## Related documentation

- [Ingestion](../pipeline/ingestion.md): every existing stage.
- [Concurrency and failure](../pipeline/concurrency-and-failure.md): the threading rules.
- [WebSockets](../interfaces/websockets.md): the frames and the client reducer.
- [Auto-update](../pipeline/sync.md): what a sync re-runs.
