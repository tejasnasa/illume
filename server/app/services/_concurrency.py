"""Bounded I/O concurrency for LLM batch calls.

The sequential OpenAI call loops in four service modules (``embedder``,
``glossary_builder``, ``onboarding``, and the ``ingest`` task's PR fetch) run
on a bounded thread pool so the network round trips *overlap* in time on a
memory-constrained box -- the box has plenty of idle CPU for threading but
cannot afford the per-worker overhead of multiprocessing.

Design rules (the load-bearing ones):

* **Threads perform only the network call.** ``openai.OpenAI(...)`` builds one
  ``httpx.Client`` eagerly in ``__init__``; ``httpx.Client`` is thread-safe,
  so a single shared client is reused across threads. The parent thread does
  all database writes -- no ``Session`` is ever touched from a worker thread.
  Sidestepping the shared-session hazard is the rule, not exception handling.
* **Bounded pool.** ``LLM_MAX_WORKERS = 4`` caps the number of in-flight
  requests. The value is tuned for the box profile of 2 vCPUs: a small bounded
  pool that bounds memory and lets each thread own exactly one request +
  response. Larger numbers buy diminishing wall-clock wins because the OpenAI
  rate limit and the LLM serving the response are the actual bottleneck.
* **Failures do not lose sibling progress.** A worker thread raising an
  exception is re-raised on the main thread after any sibling responses are
  collected, mirroring the existing "failures skip the batch silently" pattern
  in ``onboarding._annotate_files``. For the embedder and glossary builder
  the LLM call IS the work, so a thread exception propagates as the call site's
  exception -- the partial results collected so far are not committed.
* **Order independence.** Callers that parallelise a batch loop submit the
  per-batch callables in their original order and ``gather_in_order``
  returns results in the same order. The downstream code can therefore pair
  each result back with its input key without re-sorting.
* **Bounded results, not just bounded requests.** ``gather_in_order`` holds
  every response until the last one lands. Callers that persist each result
  as it arrives -- the embedder's batch loop is the one today -- use
  ``iter_gather_in_order`` instead, which yields in order from a fixed-size
  in-flight window so a stage's peak memory does not scale with its input.

The helper intentionally does *no* logging or progress reporting -- the
caller drives the ``publish_log`` callback. That keeps this module boring
and easy to reason about.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TypeVar

logger = logging.getLogger(__name__)

# Maximum number of in-flight OpenAI requests during an ingestion run.
# Mirrors the box profile (2 vCPUs, small box); four threads each holding
# one request + one response sits well under the box's per-thread memory
# footprint, while overlapping enough wall-clock for the speedup to matter.
LLM_MAX_WORKERS = 4

T = TypeVar("T")


def gather_in_order[T](
    callables: list[Callable[[], T]],
    *,
    max_workers: int = LLM_MAX_WORKERS,
    label: str = "llm",
) -> list[T]:
    """Run ``callables`` on a thread pool and return results in input order.

    Each callable is a no-arg closure that performs exactly one network round
    trip. The parent thread receives results back via ``Future.result()`` in
    the order the callables were submitted, so the caller's bookkeeping
    (e.g. the ``Embedding`` rows indexed by ``source_id``) is untouched by
    the threading layer.

    Args:
        callables: One no-arg callable per network call. They are submitted
            in order; ``gather_in_order`` preserves that order in its return
            value.
        max_workers: Pool size. Defaults to ``LLM_MAX_WORKERS``; tests that
            need a smaller or larger pool pass it explicitly.
        label: Short tag used in the ``concurrent.futures.ThreadPoolExecutor``
            thread-name prefix, so a hung thread is identifiable in
            ``faulthandler`` dumps.

    Returns:
        List of results, positionally aligned with ``callables``. If any
        callable raised, ``Future.result()`` propagates the exception on the
        caller thread after siblings have completed -- the ``concurrent.futures``
        default.

    Raises:
        Any exception raised inside a worker callable. Sibling results
        that were already collected are discarded -- the caller treats
        the batch as failed.
    """
    if not callables:
        return []

    if len(callables) == 1:
        # ``concurrent.futures`` serialises even a one-call submission
        # through a pool worker, which costs a context switch for no
        # parallelism. Inline the call instead.
        return [callables[0]()]

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"llm-{label}") as pool:
        futures: list[Future[T]] = [pool.submit(fn) for fn in callables]
        return [future.result() for future in futures]


def iter_gather_in_order[T](
    callables: Iterable[Callable[[], T]],
    *,
    max_workers: int = LLM_MAX_WORKERS,
    label: str = "llm",
) -> Iterator[T]:
    """Yield results in submission order, keeping a bounded window in flight.

    :func:`gather_in_order` returns only once *every* callable has completed,
    so a caller that wants to consume results incrementally -- committing each
    batch before the next is requested -- ends up holding all responses at
    once. For embeddings that is the dominant term in the stage's peak
    memory: a 1536-dimension vector is ~48 KB, so a repository-sized batch
    list is hundreds of megabytes of floats that exist only to be written and
    dropped.

    This variant submits at most ``max_workers`` callables at a time and hands
    each result back as soon as its future resolves, so the caller can release
    one response before the next arrives. The window is topped up after each
    yield rather than drained at a barrier, so the pool stays saturated.

    Ordering, error propagation and the thread contract match
    :func:`gather_in_order`: results arrive in submission order, a worker
    exception surfaces on the caller thread, and the pool is shut down (which
    joins the threads still running) before the exception leaves.

    Args:
        callables: One no-arg callable per network call, consumed lazily --
            the tail is never submitted if the caller stops early.
        max_workers: Size of the in-flight window, and of the pool.
        label: Short tag used in the ``concurrent.futures.ThreadPoolExecutor``
            thread-name prefix, so a hung thread is identifiable in
            ``faulthandler`` dumps.

    Yields:
        Results, positionally aligned with ``callables``.

    Raises:
        Any exception raised inside a worker callable. Callables still queued
        in the window are cancelled rather than started; the ones already
        running are joined by the pool's shutdown.
    """
    iterator = iter(callables)
    window: list[Callable[[], T]] = []
    for _ in range(max_workers):
        try:
            window.append(next(iterator))
        except StopIteration:
            break

    if not window:
        return

    if len(window) == 1:
        # One call in total: a pool round trip would cost a context switch
        # for no parallelism, matching ``gather_in_order``'s inline path.
        yield window[0]()
        return

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"llm-{label}") as pool:
        pending: deque[Future[T]] = deque(pool.submit(fn) for fn in window)
        while pending:
            future = pending.popleft()
            try:
                result = future.result()
            except BaseException:
                for outstanding in pending:
                    outstanding.cancel()
                raise
            yield result

            try:
                following = next(iterator)
            except StopIteration:
                continue
            pending.append(pool.submit(following))
