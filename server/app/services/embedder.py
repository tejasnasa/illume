import logging
import re
from collections import defaultdict
from typing import Generator
from uuid import UUID

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
from openai import OpenAI
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EMBEDDABLE_KINDS = {"function", "class", "method"}

MAX_CHUNK_TOKENS = 2048

BATCH_SIZE = 100


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
    parts = [f"# {file_path}", f"## {kind}: {name}"]

    if glossary_def:
        parts.append(f"Description: {glossary_def}")
    elif docstring:
        parts.append(f"Docstring: {docstring}")

    if callers:
        parts.append(f"Called by: {', '.join(callers[:5])}")
    if callees:
        parts.append(f"Calls: {', '.join(callees[:5])}")

    parts.append(source_code)
    return "\n".join(parts)


def _build_commit_chunk(commit: Commit) -> str:
    parts = [f"# Commit {commit.hash[:8]} by {commit.author_name}"]
    parts.append(f"Message: {commit.message}")
    if commit.changed_files_list:
        file_list = ", ".join(commit.changed_files_list[:20])
        parts.append(f"Files changed: {file_list}")
    return "\n".join(parts)


def _build_file_chunk(file_path: str, symbols: list[AstSymbol], annotation: str) -> str:
    parts = [f"# File: {file_path}"]
    parts.append(f"Note: {annotation}")
    symbol_names = [
        f"{s.kind} {s.name}"
        for s in symbols
        if s.kind in ("function", "class", "method")
    ]
    if symbol_names:
        parts.append(f"Contains: {', '.join(symbol_names[:15])}")
    return "\n".join(parts)


def _build_pr_chunk(pr: PullRequest) -> str:
    desc = pr.description or ""
    return f"# PR #{pr.number}: {pr.title}\n{desc}".strip()


def _build_readme_chunks(content: str) -> list[str]:
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
    return len(text) // 4


def _iter_batches(items: list, batch_size: int) -> Generator[list, None, None]:
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def generate_embeddings(
    repository_id: UUID,
    db: Session,
    publish_log=None,
    readme_content: str | None = None,
) -> int:
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    symbols = (
        db.query(AstSymbol)
        .join(File, AstSymbol.file_id == File.id)
        .filter(
            File.repository_id == repository_id,
            AstSymbol.kind.in_(EMBEDDABLE_KINDS),
            AstSymbol.source_code.isnot(None),
            AstSymbol.source_code != "",
        )
        .all()
    )

    if not symbols:
        logger.warning(f"No embeddable symbols found for repo {repository_id}")
        return 0

    chunks = []
    skipped = 0

    file_ids = {s.file_id for s in symbols}
    files = db.query(File).filter(File.id.in_(file_ids)).all()
    file_path_map: dict[UUID, str] = {f.id: f.path for f in files}

    symbol_ids = [s.id for s in symbols]
    symbol_name_map = {s.id: s.name for s in symbols}

    glossary_map = {
        row.symbol_id: row.definition
        for row in db.query(GlossaryEntry.symbol_id, GlossaryEntry.definition)
        .filter(GlossaryEntry.symbol_id.in_(symbol_ids))
        .all()
    }

    callers_map = defaultdict(list)
    for dep in (
        db.query(Dependency.target_symbol_id, Dependency.source_symbol_id)
        .filter(Dependency.target_symbol_id.in_(symbol_ids))
        .filter(Dependency.dep_type == "calls")
        .all()
    ):
        name = symbol_name_map.get(dep.source_symbol_id)
        if name:
            callers_map[dep.target_symbol_id].append(name)

    callees_map = defaultdict(list)
    for dep in (
        db.query(Dependency.source_symbol_id, Dependency.target_symbol_id)
        .filter(Dependency.source_symbol_id.in_(symbol_ids))
        .filter(Dependency.dep_type == "calls")
        .all()
    ):
        name = symbol_name_map.get(dep.target_symbol_id)
        if name:
            callees_map[dep.source_symbol_id].append(name)

    for symbol in symbols:
        file_path = file_path_map.get(symbol.file_id, "unknown")
        chunk_text = _build_chunk_text(
            file_path=file_path,
            kind=symbol.kind,
            name=symbol.name,
            source_code=symbol.source_code,
            docstring=symbol.docstring,
            glossary_def=glossary_map.get(symbol.id),
            callers=callers_map.get(symbol.id),
            callees=callees_map.get(symbol.id),
        )

        if _token_estimate(chunk_text) > MAX_CHUNK_TOKENS:
            logger.debug(f"Skipping oversized chunk: {symbol.name} in {file_path}")
            skipped += 1
            continue

        chunks.append((symbol, chunk_text))

    logger.info(
        f"Repo {repository_id}: {len(chunks)} chunks to embed, {skipped} skipped (oversized)"
    )

    embedded_file_ids = {s.file_id for s, _ in chunks}
    all_files = db.query(File).filter(File.repository_id == repository_id).all()
    for file in all_files:
        if file.id in embedded_file_ids:
            continue
        file_symbols = db.query(AstSymbol).filter(AstSymbol.file_id == file.id).all()
        symbol_lines = "\n".join(s.source_code for s in file_symbols if s.source_code)
        if not symbol_lines.strip():
            continue
        chunk_text = f"# {file.path}\n{symbol_lines}"
        if _token_estimate(chunk_text) <= MAX_CHUNK_TOKENS:
            chunks.append((file, chunk_text))

    total_inserted = 0

    commits = db.query(Commit).filter(Commit.repository_id == repository_id).all()
    commit_chunks = []
    for c in commits:
        chunk = _build_commit_chunk(c)
        if _token_estimate(chunk) <= MAX_CHUNK_TOKENS:
            commit_chunks.append((c, chunk))
    commit_batches = list(_iter_batches(commit_chunks, BATCH_SIZE))
    total_commit_batches = len(commit_batches)

    for batch_idx, batch in enumerate(commit_batches):
        batch_texts = [t for _, t in batch]

        if publish_log:
            publish_log(
                f"Embedding commits batch {batch_idx + 1}/{total_commit_batches}..."
            )

        response = client.embeddings.create(
            model="text-embedding-3-small", input=batch_texts
        )

        for i, embedding_data in enumerate(response.data):
            commit, chunk_text = batch[i]
            db.add(
                Embedding(
                    source_type="commit",
                    source_id=commit.id,
                    file_id=None,
                    repository_id=repository_id,
                    chunk_text=chunk_text,
                    embedding=embedding_data.embedding,
                )
            )
        db.commit()
        total_inserted += len(batch)

    prs = db.query(PullRequest).filter(PullRequest.repository_id == repository_id).all()
    pr_chunks = []
    for p in prs:
        chunk = _build_pr_chunk(p)
        if _token_estimate(chunk) <= MAX_CHUNK_TOKENS:
            pr_chunks.append((p, chunk))
    pr_batches = list(_iter_batches(pr_chunks, BATCH_SIZE))
    total_pr_batches = len(pr_batches)

    for batch_idx, batch in enumerate(pr_batches):
        batch_texts = [t for _, t in batch]

        if publish_log:
            publish_log(f"Embedding PRs batch {batch_idx + 1}/{total_pr_batches}...")

        response = client.embeddings.create(
            model="text-embedding-3-small", input=batch_texts
        )

        for i, embedding_data in enumerate(response.data):
            pr, chunk_text = batch[i]
            db.add(
                Embedding(
                    source_type="pull_request",
                    source_id=pr.id,
                    file_id=None,
                    repository_id=repository_id,
                    chunk_text=chunk_text,
                    embedding=embedding_data.embedding,
                )
            )
        db.commit()
        total_inserted += len(batch)

    if readme_content:
        readme_chunks = _build_readme_chunks(readme_content)
        if readme_chunks:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=readme_chunks,
            )
            for i, embedding_data in enumerate(response.data):
                db.add(
                    Embedding(
                        source_type="document",
                        source_id=repository_id,
                        file_id=None,
                        repository_id=repository_id,
                        chunk_text=readme_chunks[i],
                        embedding=embedding_data.embedding,
                    )
                )
            db.commit()
            total_inserted += len(readme_chunks)
            if publish_log:
                publish_log(f"README embedded ({len(readme_chunks)} sections).")

    guide = (
        db.query(OnboardingGuide)
        .filter(OnboardingGuide.repository_id == repository_id)
        .first()
    )
    annotation_map: dict[str, str] = {}
    if guide and guide.reading_order:
        annotation_map = {
            item["path"]: item["annotation"]
            for item in guide.reading_order
            if item.get("annotation")
        }

    file_chunks = []
    for file in all_files:
        annotation = annotation_map.get(file.path, "")
        if not annotation:
            continue
        file_symbols = [s for s in symbols if s.file_id == file.id]
        chunk_text = _build_file_chunk(file.path, file_symbols, annotation)
        if _token_estimate(chunk_text) <= MAX_CHUNK_TOKENS:
            file_chunks.append((file, chunk_text))
    file_batches = list(_iter_batches(file_chunks, BATCH_SIZE))
    total_file_batches = len(file_batches)

    for batch_idx, batch in enumerate(_iter_batches(file_chunks, BATCH_SIZE)):
        batch_texts = [t for _, t in batch]
        if publish_log:
            publish_log(
                f"Embedding files batch {batch_idx + 1}/{total_file_batches}..."
            )
        response = client.embeddings.create(
            model="text-embedding-3-small", input=batch_texts
        )
        for i, embedding_data in enumerate(response.data):
            file, chunk_text = batch[i]
            db.add(
                Embedding(
                    source_type="file",
                    source_id=file.id,
                    file_id=file.id,
                    repository_id=repository_id,
                    chunk_text=chunk_text,
                    embedding=embedding_data.embedding,
                )
            )
        db.commit()
        total_inserted += len(batch)

    batches = list(_iter_batches(chunks, BATCH_SIZE))

    for batch_idx, batch in enumerate(batches):
        batch_texts = [chunk_text for _, chunk_text in batch]

        if publish_log:
            publish_log(
                f"Embedding batch {batch_idx + 1}/{len(batches)} ({len(batch_texts)} chunks)..."
            )

        try:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=batch_texts,
            )
        except Exception as e:
            logger.error(f"OpenAI embedding call failed on batch {batch_idx + 1}: {e}")
            raise

        for i, embedding_data in enumerate(response.data):
            item, chunk_text = batch[i]
            if isinstance(item, AstSymbol):
                source_id = item.id
                file_id = item.file_id
            else:
                source_id = item.id
                file_id = item.id
            db_embedding = Embedding(
                source_type="symbol",
                source_id=source_id,
                file_id=file_id,
                repository_id=repository_id,
                chunk_text=chunk_text,
                embedding=embedding_data.embedding,
            )
            db.add(db_embedding)

        db.commit()
        total_inserted += len(batch)
        logger.info(
            f"Batch {batch_idx + 1}/{len(batches)} committed — {total_inserted} total embeddings so far"
        )

    if publish_log:
        publish_log(f"Embedding complete — {total_inserted} vectors stored.")

    return total_inserted
