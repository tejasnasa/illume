"""Structural items: questions the import graph answers.

Two kinds, both read from the eval database's file graph with the same edge source and
direction convention as the product's ``find_path`` tool (``query_neighbours_async``, a path
followed along imports, barrels walked through):

* importers: "what breaks if this file changes?", gold the files that import it;
* path: "how does A reach B through imports?", gold the files on the shortest import chain.

Both are circular with the graph by design and are reported as a sanity class only.
"""

import random
from collections import defaultdict, deque
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File
from app.services.file_graph import query_neighbours_async
from app.services.test_files import is_test_path
from evals.gold.schema import GoldItem, make_item

MIN_IMPORTERS = 2
MAX_IMPORTERS = 15
MIN_PATH_FILES = 3
MAX_PATH_FILES = 5
MAX_PATH_SOURCES = 200

IMPORTERS_SEED = "What breaks if `{path}` changes? Which files depend on it?"
PATH_SEED = "How does `{source}` reach `{target}` through imports? Which files are on the chain?"


def shortest_unique_paths(
    deps: dict[str, list[str]], source: str, max_hops: int
) -> dict[str, list[str]]:
    """Find the targets reachable from ``source`` by exactly one shortest import chain.

    Neighbours are expanded in sorted order, so the result is deterministic.

    Args:
        deps: File to the sorted files it imports.
        source: The starting file.
        max_hops: The longest chain to follow.

    Returns:
        Target to its chain (source first), only for targets whose shortest chain is
        unique; a target with several equally short chains is left out.
    """
    depth = {source: 0}
    parent: dict[str, str] = {}
    count = {source: 1}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        if depth[current] == max_hops:
            continue
        for neighbour in deps.get(current, ()):
            if neighbour not in depth:
                depth[neighbour] = depth[current] + 1
                parent[neighbour] = current
                count[neighbour] = count[current]
                queue.append(neighbour)
            elif depth[neighbour] == depth[current] + 1:
                count[neighbour] += count[current]
    chains: dict[str, list[str]] = {}
    for target in depth:
        if target == source or count[target] != 1:
            continue
        chain = [target]
        while chain[-1] != source:
            chain.append(parent[chain[-1]])
        chains[target] = chain[::-1]
    return chains


def reaches(deps: dict[str, list[str]], start: str, goal: str, max_hops: int) -> bool:
    """Whether ``goal`` is at most ``max_hops`` imports from ``start``."""
    seen = {start}
    frontier = [start]
    for _ in range(max_hops):
        frontier = [n for current in frontier for n in deps.get(current, ()) if n not in seen]
        seen.update(frontier)
        if goal in seen:
            return True
    return False


async def build_structural_items(
    db: AsyncSession,
    *,
    repo_name: str,
    repo_id: UUID,
    base_commit: str,
    seed: int,
    n_importers: int = 5,
    n_paths: int = 5,
) -> list[GoldItem]:
    """Build importer and path items from a repository's file graph.

    Args:
        db: A session on the database holding the ingested repository.
        repo_name: The corpus entry's name.
        repo_id: The repository's id.
        base_commit: The commit the repository was ingested at.
        seed: Seeds the choice, together with the repository and base commit.
        n_importers: How many importer items to make.
        n_paths: How many path items to make. A path item needs a chain of 3 to 5 files
            whose shortest chain is unique and has no equally short chain back.

    Returns:
        The items; fewer than asked when the graph does not have enough qualifying files.
    """
    rng = random.Random(f"{repo_name}:{base_commit}:{seed}")
    rows = (await db.execute(select(File.id, File.path).where(File.repository_id == repo_id))).all()
    path_of = {row.id: row.path for row in rows}
    ids = list(path_of)

    importers: dict[str, set[str]] = defaultdict(set)
    for target_id, importer_id, _ in await query_neighbours_async(
        db, repo_id, ids, direction="importers"
    ):
        if importer_id in path_of and importer_id != target_id:
            importers[path_of[target_id]].add(path_of[importer_id])
    deps_sets: dict[str, set[str]] = defaultdict(set)
    for source_id, target_id, _ in await query_neighbours_async(
        db, repo_id, ids, direction="importees"
    ):
        if target_id in path_of and target_id != source_id:
            deps_sets[path_of[source_id]].add(path_of[target_id])
    deps = {path: sorted(targets) for path, targets in deps_sets.items()}

    items: list[GoldItem] = []

    eligible = sorted(
        path for path, found in importers.items() if MIN_IMPORTERS <= len(found) <= MAX_IMPORTERS
    )
    for path in sorted(rng.sample(eligible, min(n_importers, len(eligible)))):
        gold = tuple(sorted(importers[path]))
        items.append(
            _item(
                repo_name,
                base_commit,
                "structural.importers",
                IMPORTERS_SEED.format(path=path),
                gold,
            )
        )

    sources = sorted(deps)
    rng.shuffle(sources)
    candidates: list[list[str]] = []
    for source in sources[:MAX_PATH_SOURCES]:
        reached = shortest_unique_paths(deps, source, MAX_PATH_FILES - 1)
        for target in sorted(reached):
            chain = reached[target]
            if len(chain) < MIN_PATH_FILES:
                continue
            # A shorter or equal chain in the other direction would be the one the
            # product's find_path reports, so the direction would be ambiguous.
            if reaches(deps, target, source, len(chain) - 1):
                continue
            candidates.append(chain)
        if len(candidates) >= n_paths * 10:
            break
    candidates.sort(key=lambda chain: (chain[0], chain[-1]))
    for chain in sorted(rng.sample(candidates, min(n_paths, len(candidates)))):
        items.append(
            _item(
                repo_name,
                base_commit,
                "structural.path",
                PATH_SEED.format(source=chain[0], target=chain[-1]),
                tuple(sorted(chain)),
            )
        )
    return items


def _item(
    repo_name: str, base_commit: str, template: str, seed_text: str, gold: tuple[str, ...]
) -> GoldItem:
    """Make one structural item."""
    return make_item(
        repo=repo_name,
        base_commit=base_commit,
        family="structural",
        template=template,
        question_seed=seed_text,
        gold_files=gold,
        gold_test_files=tuple(path for path in gold if is_test_path(path)),
        circular_with=("graph",),
    )
