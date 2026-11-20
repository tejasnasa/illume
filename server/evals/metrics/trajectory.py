"""Agent trajectory metrics: tool use, how soon gold is reached, wasted reads, duplicated work.

The import adjacency is passed in as ``file -> files it imports`` (the ``importees``
direction). Path questions follow the product's ``find_path`` tool: a chain is searched from
the first file to the second, and the other way round, and the other way only wins when it is
strictly shorter.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from evals.metrics.retrieval import read_path, step_files
from evals.run.records import Generation, StepRecordOut

Adjacency = Mapping[str, Collection[str]]

DEFAULT_MAX_DEPTH = 6
"""The longest chain the product's path tool will search for."""


@dataclass(frozen=True)
class WastedReads:
    """Reads that did not help reach gold.

    Attributes:
        reads: Distinct files the agent read.
        wasted: Read files that are neither gold nor on a shortest import path from a seed
            file to a gold file.
        wasted_files: Those files, in the order first read.
        rate: ``len(wasted) / reads``; ``None`` when nothing was read or the gold is empty.
    """

    reads: int
    wasted: int
    wasted_files: tuple[str, ...]
    rate: float | None


@dataclass(frozen=True)
class Duplication:
    """Overlap between the files different workers touched.

    Attributes:
        workers: How many workers touched any file.
        mean_jaccard: Mean Jaccard similarity over worker pairs; ``None`` with fewer than two
            workers.
        shared_files: Files touched by two or more workers.
        pairs: Jaccard of each worker pair, keyed ``"a|b"`` in sorted order.
    """

    workers: int
    mean_jaccard: float | None
    shared_files: int
    pairs: Mapping[str, float]


def tool_call_counts(steps: Iterable[StepRecordOut]) -> Counter[str]:
    """Tool calls per tool name. Steps that are not tool calls, or name no tool, add nothing."""
    return Counter(s.tool for s in steps if s.kind == "tool_call" and s.tool)


def stop_reasons(generations: Iterable[Generation]) -> Counter[str]:
    """Stop reasons over agent generations; a missing reason is counted as ``"unknown"``.

    Error records are included, since an agent that ran out of budget is exactly what this
    counts.
    """
    return Counter(g.stop_reason or "unknown" for g in generations if g.steps or g.stop_reason)


def touched_files(steps: Iterable[StepRecordOut]) -> set[str]:
    """Every file any step touched."""
    files: set[str] = set()
    for step in steps:
        files.update(step_files(step))
    return files


def steps_to_first_gold(steps: Sequence[StepRecordOut], gold: Collection[str]) -> int | None:
    """The ``index`` of the first step that touches a gold file.

    Steps are taken in ``index`` order and the step's own recorded index is returned, so a
    seed retrieval at index 0 that already holds a gold file gives 0.

    Returns:
        The index, or ``None`` when no step touches gold or the gold is empty.
    """
    wanted = set(gold)
    if not wanted:
        return None
    for step in sorted(steps, key=lambda s: s.index):
        if wanted.intersection(step_files(step)):
            return step.index
    return None


def gold_never_reached(steps: Sequence[StepRecordOut], gold: Collection[str]) -> bool:
    """Whether no gold file was ever touched. ``False`` for an empty gold."""
    wanted = set(gold)
    return bool(wanted) and not wanted.intersection(touched_files(steps))


def gold_unreached(steps: Sequence[StepRecordOut], gold: Collection[str]) -> tuple[str, ...]:
    """The gold files never touched, sorted."""
    return tuple(sorted(set(gold) - touched_files(steps)))


def _bfs(adj: Mapping[str, Iterable[str]], start: str, max_depth: int) -> dict[str, int]:
    distance = {start: 0}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if distance[current] == max_depth:
            continue
        for neighbour in adj.get(current, ()):
            if neighbour not in distance:
                distance[neighbour] = distance[current] + 1
                queue.append(neighbour)
    return distance


def _reverse(adj: Adjacency) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = {}
    for source, targets in adj.items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)
    return reverse


def _directed_path_nodes(
    adj: Adjacency, reverse: Mapping[str, Iterable[str]], source: str, target: str, max_depth: int
) -> tuple[int, set[str]] | None:
    """Length and nodes of every shortest chain of imports from ``source`` to ``target``."""
    forward = _bfs(adj, source, max_depth)
    if target not in forward:
        return None
    length = forward[target]
    backward = _bfs(reverse, target, length)
    nodes = {n for n, d in forward.items() if n in backward and d + backward[n] == length}
    return length, nodes


def shortest_path_nodes(
    adj: Adjacency, source: str, target: str, max_depth: int = DEFAULT_MAX_DEPTH
) -> set[str]:
    """The files on the shortest import chain between two files, as the product's tool sees it.

    The chain from ``source`` to ``target`` is used unless a chain the other way is strictly
    shorter. Every file on any chain of the winning length is included, ends too.

    Args:
        adj: File to the files it imports.
        source: One end.
        target: The other end.
        max_depth: The longest chain to consider.

    Returns:
        The nodes; empty when there is no chain within ``max_depth``. A file paired with itself
        gives just that file.
    """
    if source == target:
        return {source}
    reverse = _reverse(adj)
    forward = _directed_path_nodes(adj, reverse, source, target, max_depth)
    limit = max_depth if forward is None else forward[0] - 1
    backward = _directed_path_nodes(adj, reverse, target, source, limit) if limit >= 1 else None
    if backward is not None:
        return backward[1]
    return forward[1] if forward is not None else set()


def seed_files(steps: Sequence[StepRecordOut]) -> set[str]:
    """The files of the agent's seed retrieval: its ``seed`` steps, or else its first step."""
    ordered = sorted(steps, key=lambda s: s.index)
    seeds = [s for s in ordered if s.kind == "seed"] or ordered[:1]
    files: set[str] = set()
    for step in seeds:
        files.update(step_files(step))
    return files


def read_files(steps: Sequence[StepRecordOut]) -> list[str]:
    """Distinct files read with ``read_file``, in order of first read."""
    files: list[str] = []
    for step in sorted(steps, key=lambda s: s.index):
        path = read_path(step)
        if path is not None and path not in files:
            files.append(path)
    return files


def wasted_reads(
    steps: Sequence[StepRecordOut],
    gold: Collection[str],
    adjacency: Adjacency,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> WastedReads:
    """Count reads that are neither gold nor on a shortest import path from a seed to gold.

    Every seed file is paired with every gold file; the files on the shortest chain between
    them (see :func:`shortest_path_nodes`) are useful, as is the gold itself.

    Edge cases: no reads gives zero reads and rate ``None``; an empty gold makes every read
    wasted by definition, so the rate is ``None`` rather than 1; a seed that cannot reach
    gold within ``max_depth`` contributes nothing; a run with no steps reads nothing.

    Args:
        steps: The agent's steps.
        gold: The required files.
        adjacency: File to the files it imports.
        max_depth: The longest chain to consider.

    Returns:
        The counts.
    """
    reads = read_files(steps)
    wanted = set(gold)
    if not wanted:
        return WastedReads(len(reads), 0, (), None)
    useful = set(wanted)
    for seed in seed_files(steps):
        for target in wanted:
            useful |= shortest_path_nodes(adjacency, seed, target, max_depth)
    wasted = tuple(path for path in reads if path not in useful)
    rate = len(wasted) / len(reads) if reads else None
    return WastedReads(len(reads), len(wasted), wasted, rate)


def worker_overlap(steps: Iterable[StepRecordOut]) -> Duplication:
    """How much the files touched by different workers overlap.

    Only steps with a ``worker_id`` count. Pairwise Jaccard is over each worker's set of
    touched files (0 when both sets are empty, which cannot happen for a worker that touched
    anything). Fewer than two workers gives ``mean_jaccard=None``.
    """
    by_worker: dict[str, set[str]] = {}
    for step in steps:
        if step.worker_id is None:
            continue
        files = by_worker.setdefault(step.worker_id, set())
        files.update(step_files(step))
    by_worker = {w: f for w, f in by_worker.items() if f}
    pairs: dict[str, float] = {}
    for a, b in combinations(sorted(by_worker), 2):
        union = by_worker[a] | by_worker[b]
        pairs[f"{a}|{b}"] = len(by_worker[a] & by_worker[b]) / len(union)
    counts = Counter(path for files in by_worker.values() for path in files)
    return Duplication(
        workers=len(by_worker),
        mean_jaccard=sum(pairs.values()) / len(pairs) if pairs else None,
        shared_files=sum(1 for n in counts.values() if n >= 2),
        pairs=pairs,
    )


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "Duplication",
    "WastedReads",
    "gold_never_reached",
    "gold_unreached",
    "read_files",
    "seed_files",
    "shortest_path_nodes",
    "steps_to_first_gold",
    "stop_reasons",
    "tool_call_counts",
    "touched_files",
    "wasted_reads",
    "worker_overlap",
]
