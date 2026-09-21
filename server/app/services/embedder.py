"""Builds and stores vector embeddings for a repository's content.

Collects embeddable text chunks from AST symbols (functions, classes,
methods), git commits, pull requests, README sections, and annotated
onboarding files, then generates embeddings via the OpenAI embeddings API
and persists them as `Embedding` rows for later pgvector retrieval.

Memory shape: the embedder previously loaded every embeddable
symbol -- including the ``source_code`` column -- into a single Python list,
then iterated it twice (once to build the chunk text, once to push it through
the API). At ~2x the source text size, that list is the largest single
object the pipeline holds at one time. The flow below splits symbol loading
into ``EMBED_BUILD_BATCH_SIZE``-sized chunks so each batch's source text is
garbage-collected before the next batch begins. The enrichment map
(``callers_map``/``callees_map``/``glossary_map``) is still loaded eagerly --
it is column-projected (names + ids, no source) and the trade-off is
acceptable.

Concurrency shape: the embed-and-store loop submits every batch's
network call to a bounded ``ThreadPoolExecutor`` (see
:mod:`app.services._concurrency`). The worker threads perform the API call
only -- they touch no ``Session``. The parent thread receives responses in
input order and runs the database writes serially, which is the only
threading-safe option on the sync engine without re-architecting session
handling. The speedup is bounded by ``LLM_MAX_WORKERS``: on the box profile this
was tuned for (2 vCPUs), four in-flight requests is the point where adding
more threads does not overlap more wall-clock.
"""

import hashlib
import logging
import re
import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any, Generator, Literal, cast
from uuid import UUID, uuid5

from openai import OpenAI
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AstSymbol,
    Commit,
    Dependency,
    Embedding,
    File,
    GlossaryEntry,
    OnboardingGuide,
    PullRequest,
)
from app.services._concurrency import gather_in_order

logger = logging.getLogger(__name__)

# Symbol kinds worth embedding individually.
EMBEDDABLE_KINDS = {"function", "class", "method"}

# Stable namespace for ``uuid5``-derived ``source_id``s. The constant here
# is a per-application value -- regenerating rows with a different namespace
# changes every id, so it is pinned rather than derived from settings.
# Per-section README ``source_id``s and any other stable synthetic keys flow
# through this single value so all of them are reproducible from a string.
_README_SECTION_NS = uuid.UUID("5c4d6e7f-8a01-4c5d-6e7f-8a014c5d6e7f")


def _chunk_hash(chunk_text: str) -> str:
    """Stable hash of a rendered chunk's text.

    The incremental embedder compares this against the stored value to
    decide whether a re-embed is needed -- a symbol whose callers or
    definition changed without its own source changing should still get
    a fresh vector. SHA-256 is overkill but cheap and stable across
    Python versions; ``String(64)`` in the migration covers it.
    """
    return hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()


def _readme_section_source_id(repository_id: UUID, section_index: int) -> UUID:
    """Per-section ``source_id`` for README chunks.

    Every README section needs a distinct ``source_id`` so the upcoming
    ``uq_embedding_source`` unique constraint does not collapse them
    into one row. ``uuid5`` over a stable namespace plus the section's
    index makes each section individually upsertable.
    """
    return uuid5(_README_SECTION_NS, f"{repository_id}:{section_index}")


# Chunks above this estimated size are skipped to stay within model limits.
MAX_CHUNK_TOKENS = 2048

# Number of chunks per OpenAI embeddings API call. Hardcoded by the model
# vendor at 100 for text-embedding-3-small; raising this does not help.
BATCH_SIZE = 100

# Symbols are projected (id, file_id, kind, name, source_code, docstring) one
# batch at a time and the chunk built from them, so the chunk text never
# coexists in memory with the rest of the source code. A small enough number
# that tracemalloc shows a flat profile through the loop; a large enough
# number that the per-batch query overhead is negligible.
EMBED_BUILD_BATCH_SIZE = 500

# OpenAI's per-request timeouts. The default read timeout is 600s, which would
# pin the only Celery worker for ten minutes on a stalled call.
_OPENAI_TIMEOUT_S = 60.0


def _build_chunk_text(
    file_path: str,
    kind: str,
    name: str,
    source_code: str,
    docstring: str | None = None,
    glossary_def: str | None = None,
    callers: list[str] | None = None,
    callees: list[str] | None = None,
) -> str:
    """Builds a labeled chunk for a symbol with context metadata.

    When both a glossary definition and a docstring are available the
    glossary definition wins (it is what the LLM wrote to summarise the
    code, which is the more useful signal for retrieval). When only a
    docstring is available, it is appended *unless* the docstring text is
    already in the source -- a naive substring check fails on multi-line
    docstrings because the raw source carries indentation on continuation
    lines while the normalised docstring does not, so the comparison runs
    on whitespace-normalised text on both sides.
    """
    parts = [f"# {file_path}", f"## {kind}: {name}"]

    if glossary_def:
        parts.append(f"Description: {glossary_def}")
    elif docstring and not _source_already_contains_docstring(source_code, docstring):
        parts.append(f"Docstring: {docstring}")

    if callers:
        parts.append(f"Called by: {', '.join(callers[:5])}")
    if callees:
        parts.append(f"Calls: {', '.join(callees[:5])}")

    parts.append(source_code)
    return "\n".join(parts)


def _source_already_contains_docstring(source_code: str, docstring: str) -> bool:
    """Return True if the docstring text is already embedded in the source.

    Whitespace-normalising both sides is what makes the check robust on
    multi-line docstrings: the raw source carries the indent, the
    normalised docstring does not, and a plain substring comparison fails
    in exactly that case -- which is the long-docstring case where the
    duplicate-text cost is highest.
    """
    normalised_source = re.sub(r"\s+", " ", source_code)
    normalised_doc = re.sub(r"\s+", " ", docstring).strip()
    if not normalised_doc:
        return False
    return normalised_doc in normalised_source


def _build_commit_chunk(commit: Commit) -> str:
    """Builds a chunk summarizing a commit's message and changed files."""
    parts = [f"# Commit {commit.hash[:8]} by {commit.author_name}"]
    parts.append(f"Message: {commit.message}")
    if commit.changed_files_list:
        file_list = ", ".join(commit.changed_files_list[:20])
        parts.append(f"Files changed: {file_list}")
    return "\n".join(parts)


def _build_file_chunk(file_path: str, symbol_names: list[str], annotation: str) -> str:
    """Builds a chunk pairing an onboarding annotation with the file's symbols."""
    parts = [f"# File: {file_path}"]
    parts.append(f"Note: {annotation}")
    if symbol_names:
        parts.append(f"Contains: {', '.join(symbol_names[:15])}")
    return "\n".join(parts)


def _build_pr_chunk(pr: PullRequest) -> str:
    """Builds a chunk from a PR's number, title, and description."""
    desc = pr.description or ""
    return f"# PR #{pr.number}: {pr.title}\n{desc}".strip()


def _build_readme_chunks(content: str) -> list[str]:
    """Splits README markdown into per-`##`-section chunks within the token cap."""
    sections = re.split(r"(?=^##\s)", content, flags=re.MULTILINE)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        chunk = f"# README\n{section}"
        if _token_estimate(chunk) <= MAX_CHUNK_TOKENS:
            chunks.append(chunk)
    return chunks


def _token_estimate(text: str) -> int:  # token estimate: 4 chars per token
    """Rough token count assuming ~4 characters per token."""
    return len(text) // 4


def _iter_batches(items: list, batch_size: int) -> Generator[list, None, None]:
    """Yields successive fixed-size slices of `items`."""
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


class _CommitProxy:
    """Read-only stand-in for a ``Commit`` carrying only the chunk-builder fields."""

    __slots__ = ("hash", "author_name", "message", "changed_files_list")

    def __init__(self, hash_, author_name, message, changed_files_list) -> None:
        self.hash = hash_
        self.author_name = author_name
        self.message = message
        self.changed_files_list = changed_files_list


class _PRProxy:
    """Read-only stand-in for a ``PullRequest`` carrying only the chunk-builder fields."""

    __slots__ = ("number", "title", "description")

    def __init__(self, number, title, description) -> None:
        self.number = number
        self.title = title
        self.description = description


def _commit_proxy(row) -> _CommitProxy:
    return _CommitProxy(row.hash, row.author_name, row.message, row.changed_files_list)


def _pr_proxy(row) -> _PRProxy:
    return _PRProxy(row.number, row.title, row.description)


def _load_stored_hashes(
    db: Session,
    repository_id: UUID,
    source_type: str,
) -> dict[UUID, str | None]:
    """Return ``{source_id: chunk_hash}`` for every stored chunk of one source type.

    Used by the incremental reconcile to skip chunks whose rendered
    text matches what is already on disk. The lookup is keyed by the
    unique constraint columns -- ``source_id`` within a
    ``(repository_id, source_type)`` pair is what uniquely identifies a
    chunk.
    """
    rows = db.execute(
        select(Embedding.source_id, Embedding.chunk_hash).where(
            Embedding.repository_id == repository_id,
            Embedding.source_type == source_type,
        )
    ).all()
    return {row.source_id: row.chunk_hash for row in rows}


def _filter_chunks_by_hash(
    items: list[tuple[UUID, str]],
    stored_hashes: dict[UUID, str | None],
) -> list[tuple[UUID, str]]:
    """Return only chunks whose text differs from the stored hash (or which are missing).

    A ``None`` stored hash (a row written before the column existed) is
    treated as "no match" so old rows get re-embedded -- a one-time
    migration cost that keeps the index self-healing.
    """
    out: list[tuple[UUID, str]] = []
    for source_id, chunk_text in items:
        stored = stored_hashes.get(source_id)
        if stored is None or stored != _chunk_hash(chunk_text):
            out.append((source_id, chunk_text))
    return out


def _iter_query_batches(
    db: Session,
    repository_id: UUID,
    batch_size: int,
) -> Generator[list, None, None]:
    """
    Yield embeddable symbols for a repo in ``batch_size`` slices.

    Joins on ``File.repository_id`` rather than passing ``symbol_ids`` to an
    ``IN (...)``. The previous shape built ``symbol_ids`` in memory from
    every embeddable symbol and then ran four queries against it; past
    ~32k symbols the bind-parameter list exceeded the driver's limit and
    SQLAlchemy does not paginate ``IN`` lists, so the call failed outright.
    Server-side chunking also matches what the file_graph helper already
    does (``file_graph.py:41``).

    ``stream_results=True`` opts in to a server-side cursor (psycopg2
    feature), which is what makes ``fetchmany`` actually page rather than
    slice an already-materialised list.
    """
    stmt = (
        select(
            AstSymbol.id,
            AstSymbol.file_id,
            AstSymbol.kind,
            AstSymbol.name,
            AstSymbol.source_code,
            AstSymbol.docstring,
        )
        .join(File, AstSymbol.file_id == File.id)
        .where(
            File.repository_id == repository_id,
            AstSymbol.kind.in_(EMBEDDABLE_KINDS),
            AstSymbol.source_code.isnot(None),
            AstSymbol.source_code != "",
        )
        .execution_options(stream_results=True, max_row_buffer=batch_size)
    )
    result = db.execute(stmt)
    while True:
        rows = result.fetchmany(batch_size)
        if not rows:
            break
        yield rows


def _embed_batches(
    client: OpenAI,
    batches: list[list[tuple[UUID, str]]],
    label: str,
) -> list:
    """Submit one embedding call per batch to the parallel pool.

    Returns:
        A list of responses, positionally aligned with ``batches``. Each
        ``response.data`` is then paired back to the input items in
        :func:`_embed_and_store`. The pool re-raises any worker exception
        to the caller, which logs and aborts the ingest -- the existing
        "fail loud" contract for embeddings.
    """
    return gather_in_order(
        [
            cast(
                Callable[[], Any],
                (
                    lambda b=batch: client.embeddings.create(
                        model="text-embedding-3-small",
                        input=[chunk_text for _, chunk_text in b],
                    )
                ),
            )
            for batch in batches
        ],
        label=f"embed-{label}",
    )


def _embed_and_store(
    client: OpenAI,
    db: Session,
    repository_id: UUID,
    items: list[tuple[UUID, str]],
    source_type: str,
    file_id_of=None,
    publish_log=None,
    label: str = "chunks",
    upsert: bool = False,
) -> int:
    """Embed a list of ``(source_id, chunk_text)`` pairs and persist the vectors.

    Single implementation of the embed-batch loop shared by all source types:
    batches the chunks, runs the OpenAI calls in parallel through
    :func:`_embed_batches`, and inserts one ``Embedding`` row per chunk in
    input order on the parent thread. Each batch is committed as it
    completes so partial progress survives a later API failure.

    Threads perform only the network call -- no ``Session`` is shared. The
    parent thread does all DB writes because the sync engine has no
    thread-safe mode and re-architecting session handling for a bounded
    pool is not justified by the speedup. See :mod:`app.services._concurrency`
    for the threading contract.

    The ``chunk_hash`` column is set to a SHA-256 of ``chunk_text`` at insert
    time so the incremental path can compare against the stored value and
    only re-embed chunks whose rendered text actually changed.

    ``upsert=True`` switches the insert into ``ON CONFLICT DO UPDATE`` against
    the ``uq_embedding_source`` constraint -- the incremental reconcile
    relies on this so a chunk whose text changed overwrites the previous
    row instead of failing the unique key.

    Args:
        client: OpenAI client used for the embeddings API.
        db: SQLAlchemy session for persistence.
        repository_id: Repository the embeddings belong to.
        items: List of ``(source_id, chunk_text)`` tuples. ``source_id`` is the
            value written to ``Embedding.source_id`` -- for symbol chunks it
            is the AstSymbol id, for file chunks it is the File id, and so
            on.
        source_type: Value for ``Embedding.source_type`` (e.g. "commit").
        file_id_of: Optional callable mapping a source_id to its
            ``file_id``; when omitted, ``file_id`` is stored as None.
        publish_log: Optional progress callback receiving status messages.
        label: Human-readable noun for progress messages.
        upsert: When True, update an existing row on the
            ``(repository_id, source_type, source_id)`` unique key.

    Returns:
        Number of embeddings inserted or updated.
    """
    inserted = 0
    batches = list(_iter_batches(items, BATCH_SIZE))

    if not batches:
        return 0

    if publish_log:
        publish_log(f"Embedding {len(batches)} {label} batches in parallel...")

    try:
        responses = _embed_batches(client, batches, label)
    except Exception as e:
        logger.error(f"OpenAI embedding call failed for {label}: {e}")
        raise

    # Walk the batches and their responses together; the embed-and-store
    # helper guarantees positional alignment so the ``response.data`` items
    # pair back to the input ``(source_id, chunk_text)`` tuples in order.
    for batch_idx, (batch, response) in enumerate(zip(batches, responses, strict=True)):
        rows = [
            {
                "source_type": source_type,
                "source_id": source_id,
                "file_id": file_id_of(source_id) if file_id_of else None,
                "repository_id": repository_id,
                "chunk_text": chunk_text,
                "chunk_hash": _chunk_hash(chunk_text),
                "embedding": embedding_data.embedding,
            }
            for (source_id, chunk_text), embedding_data in zip(batch, response.data)
        ]
        stmt = pg_insert(Embedding).values(rows)
        if upsert:
            stmt = stmt.on_conflict_do_update(
                index_elements=["repository_id", "source_type", "source_id"],
                set_={
                    "file_id": stmt.excluded.file_id,
                    "chunk_text": stmt.excluded.chunk_text,
                    "chunk_hash": stmt.excluded.chunk_hash,
                    "embedding": stmt.excluded.embedding,
                },
            )
        # Bulk insert bypasses the identity map entirely; the previous
        # per-row ``db.add`` was the same shape for a long batch.
        db.execute(stmt)

        db.commit()
        inserted += len(batch)
        logger.info(
            f"{label} batch {batch_idx + 1}/{len(batches)} committed "
            f"\u2014 {inserted} total embeddings so far"
        )

    return inserted


def generate_embeddings(
    repository_id: UUID,
    db: Session,
    publish_log=None,
    readme_content: str | None = None,
    mode: Literal["full", "incremental"] = "full",
    changed_file_ids: list[UUID] | None = None,
) -> int:
    """Generate and persist vector embeddings for a repository.

    Builds text chunks from four source types and embeds each with the
    OpenAI ``text-embedding-3-small`` model in batches of ``BATCH_SIZE``:

    - **Symbols**: functions/classes/methods with source code, enriched
      with glossary definitions (preferred over docstrings), caller/callee
      names (up to 5 each), and file paths. Files whose symbols were all
      skipped as oversized get one fallback chunk of their concatenated
      symbol source, so they remain searchable at coarse granularity.
    - **Commits**: hash, author, message, and up to 20 changed files.
    - **Pull requests**: number, title, and description.
    - **README**: split into per-section chunks prefixed with a header.
    - **Annotated files**: files listed in the repository's onboarding
      guide reading order get a chunk combining the annotation with the
      file's symbol names.

    Any chunk whose estimated token count exceeds ``MAX_CHUNK_TOKENS`` is
    skipped rather than truncated. Each batch is committed to the database
    as it completes, so partial progress survives failures.

    Args:
        repository_id: ID of the repository to embed.
        db: SQLAlchemy session used for queries and persistence.
        publish_log: Optional callback receiving progress messages
            (e.g. for streaming status to a client).
        readme_content: Optional raw README markdown to embed as documents.
        mode: ``"full"`` deletes the repository's existing embeddings first
            (the only correct behaviour for a full re-ingest, since commits
            and PRs have no ``file_id`` and therefore no cascade to clear
            them). ``"incremental"`` reconciles: it rebuilds every desired
            chunk in pure CPU, computes ``chunk_hash``, and only calls
            OpenAI for chunks whose stored hash differs or which are
            missing. Symbol and file chunks tied to ``changed_file_ids``
            are deleted up front so a chunk whose source file was removed
            does not survive; chunks whose hash already matches are left
            alone.
        changed_file_ids: Files touched by the current sync. Required for
            ``incremental`` mode; controls the targeted symbol/file chunk
            delete that closes the orphan-row gap. Ignored in ``full``
            mode (the whole-repo delete handles it).

    Returns:
        Total number of embeddings inserted or updated.

    Raises:
        Exception: If an OpenAI embeddings API call fails; the error is
            logged and re-raised after earlier batches have been committed.
    """
    if mode == "full":
        # Repo-scoped delete: ``File`` cascades only reach ``Embedding.file_id``,
        # so commit/PR/document rows survive a ``DELETE FROM files``. The full
        # re-ingest path used to rely on the parse stage's file delete taking
        # them with it, but the parse stage now runs as ``ON CONFLICT DO
        # NOTHING`` and never deletes -- so this is the only place the old
        # rows get cleared.
        db.query(Embedding).filter(Embedding.repository_id == repository_id).delete()
        db.commit()
    else:
        # Incremental: drop chunks for the files touched in this sync.
        # Symbol chunks and annotated-file chunks both carry ``file_id``;
        # the targeted delete covers both with one predicate and never
        # touches commit/PR embeddings (whose ``file_id IS NULL``).
        if changed_file_ids:
            db.execute(
                delete(Embedding).where(
                    Embedding.repository_id == repository_id,
                    Embedding.file_id.in_(changed_file_ids),
                    Embedding.source_type.in_(("symbol", "file")),
                )
            )
            db.commit()

    client = OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=_OPENAI_TIMEOUT_S,
        max_retries=2,
    )

    # Load file metadata once -- ``path`` for every file is needed for the
    # chunk text. This is small (path + id + language per file).
    file_rows = db.execute(
        select(File.id, File.path, File.language).where(File.repository_id == repository_id)
    ).all()
    file_path_map: dict[UUID, str] = {row.id: row.path for row in file_rows}
    all_file_ids = {row.id for row in file_rows}

    if not file_rows:
        logger.warning(f"No files found for repo {repository_id}")
        return 0

    # Eagerly load the enrichment data the chunk builder needs. None of this
    # carries source text, so loading it as one map is cheaper than the
    # per-symbol query it replaced.
    symbol_id_to_name: dict[UUID, str] = {}

    def _load_symbol_names() -> None:
        # Run once per repository: column-projected (id, name) on every
        # embeddable symbol. A separate pass from the per-batch loop above.
        for row in db.execute(
            select(AstSymbol.id, AstSymbol.name)
            .join(File, AstSymbol.file_id == File.id)
            .where(File.repository_id == repository_id)
            .where(AstSymbol.kind.in_(EMBEDDABLE_KINDS))
        ):
            symbol_id_to_name[row.id] = row.name or ""

    _load_symbol_names()

    if not symbol_id_to_name:
        logger.warning(f"No embeddable symbols found for repo {repository_id}")

    # Glossary definitions are keyed by symbol_id and weight the chunk heavily
    # in retrieval; loading them upfront keeps the build loop free of queries.
    glossary_map: dict[UUID, str] = {}
    if symbol_id_to_name:
        for row in db.execute(
            select(GlossaryEntry.symbol_id, GlossaryEntry.definition).where(
                GlossaryEntry.symbol_id.in_(symbol_id_to_name.keys())
            )
        ):
            glossary_map[row.symbol_id] = row.definition

    # Caller/callee maps: ``Dependency.dep_type == 'calls'`` is never
    # actually written by the resolver (only ``'imports'`` is), so these
    # maps are empty in practice. Keep the lookup so the schema can be
    # filled in later without touching this code path.
    callers_map: dict[UUID, list[str]] = defaultdict(list)
    callees_map: dict[UUID, list[str]] = defaultdict(list)
    if symbol_id_to_name:
        for dep in db.execute(
            select(Dependency.target_symbol_id, Dependency.source_symbol_id).where(
                Dependency.target_symbol_id.in_(symbol_id_to_name.keys()),
                Dependency.dep_type == "calls",
            )
        ).all():
            name = symbol_id_to_name.get(dep.source_symbol_id)
            if name:
                callers_map[dep.target_symbol_id].append(name)
        for dep in db.execute(
            select(Dependency.source_symbol_id, Dependency.target_symbol_id).where(
                Dependency.source_symbol_id.in_(symbol_id_to_name.keys()),
                Dependency.dep_type == "calls",
            )
        ).all():
            name = symbol_id_to_name.get(dep.target_symbol_id)
            if name:
                callees_map[dep.source_symbol_id].append(name)

    # Build symbol chunks in bounded batches and embed each batch before the
    # next is read. The previous shape loaded every ``source_code`` column
    # in one ORM list and then iterated it twice -- once to build chunk
    # text, once to embed -- so the chunk text and the source text lived
    # side by side for the duration. Doing both steps inside the same loop
    # bounds the live set to a single batch's worth of source text.
    embedded_file_ids: set[UUID] = set()
    skipped = 0
    total_inserted = 0
    # source_id_to_file_id has to outlive the build loop because the
    # embeddings row needs ``file_id`` at insert time, but it is just a
    # UUID-to-UUID map -- bounded by the number of surviving symbol
    # chunks, not their text.
    source_id_to_file_id: dict[UUID, UUID] = {}

    # In incremental mode, load stored hashes for every source_type that
    # derives from files -- symbol and annotated-file chunks. Commit and
    # PR chunks are not reconciled: their content is immutable, the row
    # count is bounded by git history and PR list size, and a full
    # rebuild resets them on the next escalation. README chunks are
    # handled separately below because the desired content comes from
    # the caller, not the database.
    stored_symbol_hashes: dict[UUID, str | None] = {}
    stored_file_hashes: dict[UUID, str | None] = {}
    if mode == "incremental":
        stored_symbol_hashes = _load_stored_hashes(db, repository_id, "symbol")
        stored_file_hashes = _load_stored_hashes(db, repository_id, "file")

    def _embed_symbol_chunks() -> int:
        """Stream symbols, build chunks, embed all batches in parallel.

        Returns:
            Number of embeddings inserted or updated.
        """
        nonlocal skipped
        # Each entry carries ``(symbol_id, file_id, chunk_text)``. Holding
        # the ``file_id`` alongside the ``source_id`` lets ``_embed_and_store``
        # populate ``Embedding.file_id`` without a per-row lookup. Building
        # the whole chunk list before submitting to the pool is what lets
        # the parallel path actually overlap multiple OpenAI calls: a
        # previous per-flush shape called ``_embed_and_store`` once per
        # ``BATCH_SIZE`` slice, and the single-batch ``_iter_batches``
        # inside only ever emitted one future, defeating the pool.
        all_pending: list[tuple[UUID, UUID, str]] = []

        for batch_rows in _iter_query_batches(db, repository_id, EMBED_BUILD_BATCH_SIZE):
            for row in batch_rows:
                sym_id, file_id, kind, name, source_code, docstring = row
                file_path = file_path_map.get(file_id, "unknown")
                chunk_text = _build_chunk_text(
                    file_path=file_path,
                    kind=kind,
                    name=name or "",
                    source_code=source_code,
                    docstring=docstring,
                    glossary_def=glossary_map.get(sym_id),
                    callers=callers_map.get(sym_id),
                    callees=callees_map.get(sym_id),
                )

                if _token_estimate(chunk_text) > MAX_CHUNK_TOKENS:
                    logger.debug(f"Skipping oversized chunk: {name} in {file_path}")
                    skipped += 1
                    continue

                all_pending.append((sym_id, file_id, chunk_text))
                embedded_file_ids.add(file_id)
                source_id_to_file_id[sym_id] = file_id

        if not all_pending:
            return 0

        items_full = [(sym_id, chunk_text) for sym_id, _fid, chunk_text in all_pending]
        file_ids = {sym_id: fid for sym_id, fid, _t in all_pending}
        if mode == "incremental":
            # Reconcile: drop chunks whose stored hash matches the
            # freshly-rendered text. An unchanged symbol in an unchanged
            # file does not pay the OpenAI call.
            items = _filter_chunks_by_hash(items_full, stored_symbol_hashes)
        else:
            items = items_full
        if not items:
            return 0
        if publish_log:
            publish_log(
                f"Built {len(items_full)} symbol chunks ({skipped} skipped, "
                f"{len(items_full) - len(items)} up to date)"
            )
        # The ``all_pending`` local is the only reference to the chunk
        # strings; once ``_embed_and_store`` returns they are unreachable
        # and the per-batch lists inside the pool are the live copies.
        return _embed_and_store(
            client,
            db,
            repository_id,
            items,
            source_type="symbol",
            file_id_of=file_ids.get,
            publish_log=publish_log,
            label="symbol chunks",
            upsert=(mode == "incremental"),
        )

    total_inserted += _embed_symbol_chunks()

    # --- Commits ---
    # Embedded first because they're small and fast; their completion gives
    # early searchable signal while bigger sets process. In incremental
    # mode the git history is re-mined by ``analyze_git_history`` -- commit
    # messages and authorship are immutable so the previously-stored
    # chunks remain correct and are left alone; the new commits only
    # land in the index when ``analyze_git_history`` inserts them, which
    # then flows through this path on the next ingest.
    if mode == "full":
        commit_rows = db.execute(
            select(
                Commit.id,
                Commit.hash,
                Commit.author_name,
                Commit.message,
                Commit.changed_files_list,
            ).where(Commit.repository_id == repository_id)
        ).all()
        commit_chunks: list[tuple[UUID, str]] = []
        for row in commit_rows:
            chunk = _build_commit_chunk(_commit_proxy(row))
            if _token_estimate(chunk) <= MAX_CHUNK_TOKENS:
                commit_chunks.append((row.id, chunk))
        total_inserted += _embed_and_store(
            client,
            db,
            repository_id,
            commit_chunks,
            source_type="commit",
            publish_log=publish_log,
            label="commits",
        )

    # --- Pull requests ---
    # PRs are not refreshed on the sync path (``_bulk_insert_pull_requests``
    # is ``ON CONFLICT DO NOTHING``); skip them in incremental mode.
    if mode == "full":
        pr_rows = db.execute(
            select(
                PullRequest.id, PullRequest.number, PullRequest.title, PullRequest.description
            ).where(PullRequest.repository_id == repository_id)
        ).all()
        pr_chunks: list[tuple[UUID, str]] = []
        for row in pr_rows:
            chunk = _build_pr_chunk(_pr_proxy(row))
            if _token_estimate(chunk) <= MAX_CHUNK_TOKENS:
                pr_chunks.append((row.id, chunk))
        total_inserted += _embed_and_store(
            client,
            db,
            repository_id,
            pr_chunks,
            source_type="pull_request",
            publish_log=publish_log,
            label="PRs",
        )

    # --- README ---
    # Per-section ``source_id``s (``uuid5`` over a stable namespace plus the
    # section index). Every section needs its own id so the upcoming
    # ``uq_embedding_source`` constraint does not collapse them.
    if readme_content:
        desired_readme_chunks = _build_readme_chunks(readme_content)
        if desired_readme_chunks:
            if mode == "incremental":
                # Reconcile by chunk_hash: a README edit only re-embeds
                # the sections that actually changed, and the upsert
                # overwrites stale rows in place.
                stored = _load_stored_hashes(db, repository_id, "document")
                desired_with_ids = [
                    (
                        _readme_section_source_id(repository_id, i),
                        chunk_text,
                    )
                    for i, chunk_text in enumerate(desired_readme_chunks)
                ]
                to_embed = _filter_chunks_by_hash(desired_with_ids, stored)
            else:
                to_embed = [
                    (
                        _readme_section_source_id(repository_id, i),
                        chunk_text,
                    )
                    for i, chunk_text in enumerate(desired_readme_chunks)
                ]

            if to_embed:
                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[chunk_text for _, chunk_text in to_embed],
                )
                rows = [
                    {
                        "source_type": "document",
                        "source_id": source_id,
                        "file_id": None,
                        "repository_id": repository_id,
                        "chunk_text": chunk_text,
                        "chunk_hash": _chunk_hash(chunk_text),
                        "embedding": embedding_data.embedding,
                    }
                    for (source_id, chunk_text), embedding_data in zip(
                        to_embed, response.data, strict=True
                    )
                ]
                stmt = pg_insert(Embedding).values(rows)
                if mode == "incremental":
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["repository_id", "source_type", "source_id"],
                        set_={
                            "chunk_text": stmt.excluded.chunk_text,
                            "chunk_hash": stmt.excluded.chunk_hash,
                            "embedding": stmt.excluded.embedding,
                        },
                    )
                db.execute(stmt)
                db.commit()
                total_inserted += len(to_embed)
                if publish_log:
                    publish_log(f"README embedded ({len(to_embed)} sections).")

    guide = db.query(OnboardingGuide).filter(OnboardingGuide.repository_id == repository_id).first()
    annotation_map: dict[str, str] = {}
    if guide and guide.reading_order:
        # Path -> why-read-this annotation, written during onboarding-guide
        # generation; only annotated files get a dedicated file-level chunk.
        annotation_map = {
            item["path"]: item["annotation"]
            for item in guide.reading_order
            if item.get("annotation")
        }

    # --- Annotated files ---
    annotated_file_ids = [row.id for row in file_rows if annotation_map.get(row.path)]
    annotated_symbols_rows: dict[UUID, list[tuple[str, str]]] = defaultdict(list)
    if annotated_file_ids:
        for row in db.execute(
            select(AstSymbol.file_id, AstSymbol.kind, AstSymbol.name).where(
                AstSymbol.file_id.in_(annotated_file_ids),
                AstSymbol.kind.in_(["function", "class", "method"]),
            )
        ).all():
            annotated_symbols_rows[row.file_id].append((row.kind, row.name or ""))

    file_chunks: list[tuple[UUID, str]] = []
    for file_id in annotated_file_ids:
        file_path = file_path_map[file_id]
        syms = annotated_symbols_rows.get(file_id, [])
        syms_label = ", ".join(f"{k} {n}" for k, n in syms[:15])
        text = f"# File: {file_path}\nNote: {annotation_map[file_path]}"
        if syms_label:
            text += f"\nContains: {syms_label}"
        if _token_estimate(text) <= MAX_CHUNK_TOKENS:
            file_chunks.append((file_id, text))
            source_id_to_file_id[file_id] = file_id

    if file_chunks:
        if mode == "incremental":
            items = _filter_chunks_by_hash(file_chunks, stored_file_hashes)
        else:
            items = file_chunks
        if items:
            total_inserted += _embed_and_store(
                client,
                db,
                repository_id,
                items,
                source_type="file",
                file_id_of=source_id_to_file_id.get,
                publish_log=publish_log,
                label="files",
                upsert=(mode == "incremental"),
            )

    # Symbol chunks go last: they're the largest batch set, and each
    # committed batch represents durable progress if a later API call fails.
    # Whole-file fallback chunks share the same ``symbol`` source_type;
    # their ``source_id`` is the file id (already mapped to itself above).
    fallback_chunks: list[tuple[UUID, str]] = []
    files_needing_fallback = all_file_ids - embedded_file_ids
    if files_needing_fallback:
        file_symbols_rows = db.execute(
            select(AstSymbol.file_id, AstSymbol.source_code).where(
                AstSymbol.file_id.in_(files_needing_fallback)
            )
        ).all()
        per_file_sources: dict[UUID, list[str]] = defaultdict(list)
        for row in file_symbols_rows:
            if row.source_code:
                per_file_sources[row.file_id].append(row.source_code)
        for file_id, sources in per_file_sources.items():
            chunk_text = f"# {file_path_map.get(file_id, '')}\n" + "\n".join(sources)
            if _token_estimate(chunk_text) <= MAX_CHUNK_TOKENS:
                fallback_chunks.append((file_id, chunk_text))
                source_id_to_file_id[file_id] = file_id

    if fallback_chunks:
        if mode == "incremental":
            items = _filter_chunks_by_hash(fallback_chunks, stored_symbol_hashes)
        else:
            items = fallback_chunks
        if items:
            total_inserted += _embed_and_store(
                client,
                db,
                repository_id,
                items,
                source_type="symbol",
                file_id_of=source_id_to_file_id.get,
                publish_log=publish_log,
                label="file-fallback chunks",
                upsert=(mode == "incremental"),
            )

    if publish_log:
        publish_log(f"Embedding complete — {total_inserted} vectors stored.")

    return total_inserted
