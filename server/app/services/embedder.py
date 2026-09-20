"""Builds and stores vector embeddings for a repository's content.

Collects embeddable text chunks from AST symbols (functions, classes,
methods), git commits, pull requests, README sections, and annotated
onboarding files, then generates embeddings via the OpenAI embeddings API
and persists them as `Embedding` rows for later pgvector retrieval.

Memory shape (Phase B): the embedder previously loaded every embeddable
symbol -- including the ``source_code`` column -- into a single Python list,
then iterated it twice (once to build the chunk text, once to push it through
the API). At ~2x the source text size, that list is the largest single
object the pipeline holds at one time. The flow below splits symbol loading
into ``EMBED_BUILD_BATCH_SIZE``-sized chunks so each batch's source text is
garbage-collected before the next batch begins. The enrichment map
(``callers_map``/``callees_map``/``glossary_map``) is still loaded eagerly --
it is column-projected (names + ids, no source) and the trade-off is
acceptable.
"""

import logging
import re
from collections import defaultdict
from typing import Generator
from uuid import UUID

from openai import OpenAI
from sqlalchemy import select
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

logger = logging.getLogger(__name__)

# Symbol kinds worth embedding individually.
EMBEDDABLE_KINDS = {"function", "class", "method"}

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


def _embed_and_store(
    client: OpenAI,
    db: Session,
    repository_id: UUID,
    items: list[tuple[UUID, str]],
    source_type: str,
    file_id_of=None,
    publish_log=None,
    label: str = "chunks",
) -> int:
    """Embed a list of ``(source_id, chunk_text)`` pairs and persist the vectors.

    Single implementation of the embed-batch loop shared by all source types:
    batches the chunks, calls OpenAI (response order matches input order), and
    inserts one ``Embedding`` row per chunk. Each batch is committed as it
    completes so partial progress survives a later API failure.

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

    Returns:
        Number of embeddings inserted.
    """
    inserted = 0
    batches = list(_iter_batches(items, BATCH_SIZE))

    for batch_idx, batch in enumerate(batches):
        batch_texts = [chunk_text for _, chunk_text in batch]

        if publish_log:
            publish_log(f"Embedding {label} batch {batch_idx + 1}/{len(batches)}...")

        try:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=batch_texts,
            )
        except Exception as e:
            logger.error(f"OpenAI embedding call failed on {label} batch {batch_idx + 1}: {e}")
            raise

        rows = [
            {
                "source_type": source_type,
                "source_id": source_id,
                "file_id": file_id_of(source_id) if file_id_of else None,
                "repository_id": repository_id,
                "chunk_text": chunk_text,
                "embedding": embedding_data.embedding,
            }
            for (source_id, chunk_text), embedding_data in zip(batch, response.data)
        ]
        # Bulk insert bypasses the identity map entirely; the previous
        # per-row ``db.add`` was the same shape for a long batch.
        db.execute(pg_insert(Embedding).values(rows))

        db.commit()
        inserted += len(batch)
        logger.info(
            f"{label} batch {batch_idx + 1}/{len(batches)} committed — {inserted} total embeddings so far"
        )

    return inserted


def generate_embeddings(
    repository_id: UUID,
    db: Session,
    publish_log=None,
    readme_content: str | None = None,
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

    Returns:
        Total number of embeddings inserted.

    Raises:
        Exception: If an OpenAI embeddings API call fails; the error is
            logged and re-raised after earlier batches have been committed.
    """
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

    def _embed_symbol_chunks() -> int:
        """Stream symbols, build chunks, embed each batch in place.

        Returns:
            Number of embeddings inserted.
        """
        nonlocal skipped
        inserted = 0
        # Each entry carries ``(symbol_id, file_id, chunk_text)``. Holding
        # the ``file_id`` alongside the ``source_id`` lets ``_embed_and_store``
        # populate ``Embedding.file_id`` without a per-row lookup.
        pending: list[tuple[UUID, UUID, str]] = []

        def _flush() -> None:
            nonlocal inserted
            if not pending:
                return
            # Build the (source_id, chunk_text) view for the embed helper
            # while we still have the file_ids in scope; afterwards the
            # local ``pending`` list is the only reference to those chunk
            # strings, so clearing it lets them be collected.
            items = [(sym_id, chunk_text) for sym_id, _fid, chunk_text in pending]
            file_ids = {sym_id: fid for sym_id, fid, _t in pending}
            inserted += _embed_and_store(
                client,
                db,
                repository_id,
                items,
                source_type="symbol",
                file_id_of=file_ids.get,
                publish_log=publish_log,
                label="symbol chunks",
            )
            pending.clear()

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

                pending.append((sym_id, file_id, chunk_text))
                embedded_file_ids.add(file_id)
                source_id_to_file_id[sym_id] = file_id

                if len(pending) >= BATCH_SIZE:
                    _flush()

            if publish_log:
                publish_log(f"Built and embedded {inserted} symbol chunks ({skipped} skipped)")

        _flush()
        return inserted

    total_inserted += _embed_symbol_chunks()

    # --- Commits ---
    # Embedded first because they're small and fast; their completion gives
    # early searchable signal while bigger sets process.
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
    # README sections are stored as repo-level documents (source_id = repo id),
    # since they don't belong to any single file or symbol.
    if readme_content:
        readme_chunks = _build_readme_chunks(readme_content)
        if readme_chunks:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=readme_chunks,
            )
            rows = [
                {
                    "source_type": "document",
                    "source_id": repository_id,
                    "file_id": None,
                    "repository_id": repository_id,
                    "chunk_text": readme_chunks[i],
                    "embedding": embedding_data.embedding,
                }
                for i, embedding_data in enumerate(response.data)
            ]
            db.execute(pg_insert(Embedding).values(rows))
            db.commit()
            total_inserted += len(readme_chunks)
            if publish_log:
                publish_log(f"README embedded ({len(readme_chunks)} sections).")

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

    total_inserted += _embed_and_store(
        client,
        db,
        repository_id,
        file_chunks,
        source_type="file",
        file_id_of=source_id_to_file_id.get,
        publish_log=publish_log,
        label="files",
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
        total_inserted += _embed_and_store(
            client,
            db,
            repository_id,
            fallback_chunks,
            source_type="symbol",
            file_id_of=source_id_to_file_id.get,
            publish_log=publish_log,
            label="file-fallback chunks",
        )

    if publish_log:
        publish_log(f"Embedding complete — {total_inserted} vectors stored.")

    return total_inserted
