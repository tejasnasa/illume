"""Onboarding guide generation.

Builds a suggested file reading order for a repository using a tiered
topological sort of its dependency graph, enriches it with LLM-generated
"why read this" annotations, and persists the result on an OnboardingGuide.

Memory shape (Phase D): UUIDs are mapped to dense integers once on first
sight, the adjacency map holds ``set[int]`` instead of ``set[UUID]``, and
the dependency-edge query is streamed (``yield_per``) so the E-tuple list
never materialises alongside the two adjacency maps. The previous code
held all three representations at once -- which was the OOM on large
repos.

Determinism (Phase D): within a tier, files are sorted by
``(-fan_in, path)`` rather than the file object's natural order, so the
reading order is reproducible across runs and across machines. ``set``
iteration order in Python is otherwise unspecified and would surface as a
different click-through tour on the frontend without this.
"""

import json
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import openai
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import File, OnboardingGuide, Repository
from app.services.file_graph import build_int_adjacency, iter_file_edges

logger = logging.getLogger(__name__)

MAX_ANNOTATED_FILES = 100

ANNOTATION_BATCH_SIZE = 10


@dataclass(frozen=True)
class _FileInfo:
    """The two fields the topo sort orders by, decoupled from the ORM row.

    Holding only the path and fan_in (rather than a ``File`` ORM entity)
    keeps the per-file footprint at the size of two small Python objects.
    The old code carried every column the brief doesn't read.
    """

    path: str
    fan_in: int


def _sort_key(info: _FileInfo) -> tuple[int, str]:
    """Tier-internal sort key: most-imported first, then path-alphabetical.

    A repo where every file has the same fan-in (the common case for small
    test fixtures) used to come out in arbitrary order because the
    candidate set was a ``set`` and ``sorted(..., key=fan_in)`` was stable
    but the input wasn't. Sorting on a tuple key with a deterministic
    tiebreaker makes the output byte-identical across runs.
    """
    return (-info.fan_in, info.path)


def _topological_sort(
    files_by_int: dict[int, _FileInfo],
    deps: dict[int, set[int]],
    rdeps: dict[int, set[int]],
) -> list[list[int]]:
    """Group files into tiers via Kahn's algorithm; cycles land in a final tier.

    Args:
        files_by_int: Dense-int lookup of file metadata.
        deps: Forward adjacency; ``deps[i]`` is the set of files ``i``
            depends on.
        rdeps: Reverse adjacency; ``rdeps[i]`` is the set of files that
            depend on ``i``.

    Returns:
        List of tiers, each tier being a list of dense-int file ids. The
        list is ordered: tier 0 is the set of files with no remaining
        dependencies, and each subsequent tier only contains files whose
        dependencies are all in earlier tiers. Files that participate in a
        dependency cycle land in a single trailing tier in
        ``(-fan_in, path)`` order.
    """
    all_ids: set[int] = set(files_by_int)
    in_degree: dict[int, int] = {i: len(deps.get(i, set())) for i in all_ids}

    # Seed queue with files that have no remaining dependencies. Sort on
    # the deterministic key so the tier ordering is stable even when every
    # candidate has the same fan-in (the test suite's case).
    seed = sorted(
        (i for i in all_ids if in_degree[i] == 0),
        key=lambda i: _sort_key(files_by_int[i]),
    )
    queue: deque[int] = deque(seed)

    tiers: list[list[int]] = []
    visited: set[int] = set()

    while queue:
        # Snapshot, then re-sort: a candidate inserted mid-tier by an
        # earlier member of the same tier should not appear before the
        # member that unlocked it. The sort makes that explicit and stable.
        current_tier_ids = sorted(
            queue,
            key=lambda i: _sort_key(files_by_int[i]),
        )
        queue.clear()
        visited.update(current_tier_ids)
        tiers.append(current_tier_ids)

        next_candidates: set[int] = set()
        for fid in current_tier_ids:
            for importer_id in rdeps.get(fid, set()):
                if importer_id in visited:
                    continue
                # Decrement in-place; the previous code also called
                # ``deps[importer_id].discard(fid)`` to mutate a structure
                # nothing read again -- pure dead work, dropped here.
                in_degree[importer_id] -= 1
                if in_degree[importer_id] == 0:
                    next_candidates.add(importer_id)
        if next_candidates:
            queue.extend(
                sorted(
                    next_candidates,
                    key=lambda i: _sort_key(files_by_int[i]),
                )
            )

    # Anything never dequeued sits on a dependency cycle; emit as a catch-all
    # final tier instead of dropping those files from the guide. The sort is
    # the same key the rest of the algorithm uses, so a file in a cycle is
    # still positioned deterministically relative to its peers.
    remaining = sorted(
        (i for i in all_ids - visited),
        key=lambda i: _sort_key(files_by_int[i]),
    )
    if remaining:
        logger.warning(
            "reading_order: %d files in dependency cycle(s), appending as final tier",
            len(remaining),
        )
        tiers.append(remaining)

    return tiers


def _build_annotation_prompt(batch: list[dict[str, Any]]) -> str:
    """Render one LLM prompt covering a batch of files in reading order.

    Only fields the LLM can use to write a useful annotation are
    surfaced: the file path (it appears in the answer), fan-in (a rough
    importance signal), tier (the order the file should be read at) and
    language (it shapes the vocabulary). ``fan_out`` was dropped because
    it doesn't change the prompt's usefulness and was never read by the
    model.
    """
    items = "\n".join(
        f"{i + 1}. file_path={item['path']} | fan_in={item['fan_in']} "
        f"| tier={item['tier']} "
        f"| language={item.get('language') or 'unknown'}"
        for i, item in enumerate(batch)
    )

    return f"""You are an expert software engineer writing an onboarding guide.

For each file below, write a 1-2 sentence explanation of WHY a new engineer should read it at this point in their onboarding journey. Be concrete about what the file does and why understanding it early unlocks the rest of the codebase. Do not use filler phrases like "this file is important". Be direct.

Files (in suggested reading order):
{items}

Respond ONLY with a JSON array, no markdown fences, no preamble:
[
  {{"file_path": "<path>", "annotation": "<1-2 sentence why-read-this>"}},
  ...
]
"""


def _annotate_files(
    ordered_files: list[dict[str, Any]],
    language_by_path: dict[str, str | None],
) -> dict[str, str]:
    """Request LLM annotations in batches; failures skip the batch silently.

    The language lookup is supplied by the caller because the trimmed
    stored payload (Phase D) no longer carries ``language`` per item --
    only the columns that are actually consumed downstream.
    """
    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    annotations: dict[str, str] = {}

    to_annotate = ordered_files[:MAX_ANNOTATED_FILES]
    # Carry the language through so the prompt can still mention it
    # without storing it on every item.
    annotated_batch_input = [
        {**item, "language": language_by_path.get(item["path"])} for item in to_annotate
    ]

    for i in range(0, len(annotated_batch_input), ANNOTATION_BATCH_SIZE):
        batch = annotated_batch_input[i : i + ANNOTATION_BATCH_SIZE]
        prompt = _build_annotation_prompt(batch)

        try:
            response = client.responses.create(
                model=settings.AI_MODEL,
                reasoning={"effort": "minimal"},
                input=[{"role": "user", "content": prompt}],
                max_output_tokens=1000,
            )
            raw = response.output_text or "[]"
            raw = raw.strip()
            # Strip markdown fences even though the prompt forbids them;
            # models add them often enough that parsing would otherwise fail.
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed: list[dict] = json.loads(raw)
            for entry in parsed:
                path = entry.get("file_path", "")
                annotation = entry.get("annotation", "")
                if path and annotation:
                    annotations[path] = annotation
        except Exception as exc:
            logger.error(
                "reading_order: LLM annotation failed for batch %d-%d: %s",
                i,
                i + ANNOTATION_BATCH_SIZE,
                exc,
            )

    return annotations


def build_reading_order(db: Session, repo: Repository) -> OnboardingGuide:
    """Build and persist a suggested file reading order for a repository.

    Constructs the file-level dependency graph from symbol dependencies,
    orders files into tiers with a topological sort (files inside dependency
    cycles are appended as a final tier), then asks the LLM to annotate up to
    ``MAX_ANNOTATED_FILES`` files explaining why each should be read at that
    point in onboarding. The result is stored on the repository's
    OnboardingGuide (created if absent).

    Args:
        db: SQLAlchemy database session.
        repo: The repository to build the reading order for.

    Returns:
        The upserted OnboardingGuide containing the annotated reading order.
    """
    logger.info("reading_order: starting for repo %s", repo.id)

    # Column-tuple load: only ``id``, ``path``, ``fan_in`` and ``language``
    # are read by this function or the annotation prompt. ``select(File)``
    # would materialise ORM instances carrying every other column too,
    # which is what the previous implementation held throughout the sort.
    file_rows = db.execute(
        select(File.id, File.path, File.fan_in, File.language).where(File.repository_id == repo.id)
    ).all()

    if not file_rows:
        logger.warning("reading_order: no files found for repo %s", repo.id)
        return _upsert_guide(db, repo.id, [])

    logger.info("reading_order: loaded %d files", len(file_rows))

    files_by_int: dict[int, _FileInfo] = {}
    int_by_uuid: dict[UUID, int] = {}
    language_by_path: dict[str, str | None] = {}
    for row in file_rows:
        i = len(int_by_uuid)
        int_by_uuid[row.id] = i
        files_by_int[i] = _FileInfo(path=row.path, fan_in=row.fan_in or 0)
        language_by_path[row.path] = row.language

    # Stream the edges; ``build_int_adjacency`` populates the int-keyed
    # adjacency maps without ever holding the E-tuple list. This is the
    # single change that fixes the OOM: the previous code coexisted the
    # edge list with two UUID-keyed adjacency maps and the ORM file rows.
    #
    # The pre-existing ``int_by_uuid`` is passed in so the int keys line
    # up with ``files_by_int``; otherwise the adjacency would re-assign
    # ints in edge-encounter order and the two maps would refer to
    # different nodes by the same int -- a silent correctness bug.
    deps, rdeps, _ = build_int_adjacency(iter_file_edges(db, repo.id), int_by_uuid=int_by_uuid)

    tiers = _topological_sort(files_by_int, deps, rdeps)

    # Stored payload: ``path``, ``fan_in``, ``tier``, ``position``,
    # ``annotation``. ``file_id`` is never read; ``fan_out`` and
    # ``language`` were only used by the annotation prompt, which now
    # looks the language up from a side table. The result is roughly half
    # the JSONB size per item, and a JSONB-column scan is cheaper too.
    ordered_flat: list[dict[str, Any]] = []
    position = 1
    for tier_index, tier in enumerate(tiers):
        for int_id in tier:
            info = files_by_int[int_id]
            ordered_flat.append(
                {
                    "path": info.path,
                    "fan_in": info.fan_in,
                    "tier": tier_index,
                    "position": position,
                    "annotation": "",
                }
            )
            position += 1

    logger.info("reading_order: %d tiers, %d files total", len(tiers), len(ordered_flat))

    annotations = _annotate_files(ordered_flat, language_by_path)

    for item in ordered_flat:
        item["annotation"] = annotations.get(item["path"], "")

    guide = _upsert_guide(db, repo.id, ordered_flat)
    logger.info("reading_order: done for repo %s", repo.id)
    return guide


def _upsert_guide(
    db: Session,
    repo_id: UUID,
    reading_order: list[dict[str, Any]] | None = None,
    *,
    architecture_brief: dict[str, Any] | None = None,
    critical_files: list[dict[str, Any]] | None = None,
) -> OnboardingGuide:
    """Create or update the OnboardingGuide row for a repository.

    The guide is written in two passes by two different services: the reading order runs
    first, then the architecture brief. Each pass supplies only the columns it owns, and
    an omitted argument leaves that column untouched rather than clearing it -- otherwise
    the second pass would wipe the first pass's work.

    Args:
        db: SQLAlchemy database session.
        repo_id: Repository the guide belongs to.
        reading_order: Annotated reading-order steps, or None to leave unchanged.
        architecture_brief: Architecture sections, or None to leave unchanged.
        critical_files: Critical file summaries, or None to leave unchanged.

    Returns:
        The created or updated OnboardingGuide.
    """
    guide = db.query(OnboardingGuide).filter(OnboardingGuide.repository_id == repo_id).first()

    if guide is None:
        guide = OnboardingGuide(
            repository_id=repo_id,
            reading_order=reading_order,
            architecture_brief=architecture_brief if architecture_brief is not None else {},
            critical_files=critical_files if critical_files is not None else [],
            pdf_path=None,
        )
        db.add(guide)
    else:
        if reading_order is not None:
            guide.reading_order = reading_order
        if architecture_brief is not None:
            guide.architecture_brief = architecture_brief
        if critical_files is not None:
            guide.critical_files = critical_files

    db.commit()
    db.refresh(guide)
    return guide
