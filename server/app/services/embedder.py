import logging
from typing import Generator
from uuid import UUID

from app.core.config import settings
from app.models import AstSymbol, Commit, Embedding, File, PullRequest
from openai import OpenAI
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EMBEDDABLE_KINDS = {"function", "class", "method"}

MAX_CHUNK_TOKENS = 2048

BATCH_SIZE = 100


def _build_chunk_text(file_path: str, kind: str, name: str, source_code: str) -> str:
    return f"# {file_path}\n## {kind}: {name}\n{source_code}"


def _build_commit_chunk(commit: Commit) -> str:
    return f"# Commit {commit.hash[:8]} by {commit.author_name}\n{commit.message}"


def _build_pr_chunk(pr: PullRequest) -> str:
    desc = pr.description or ""
    return f"# PR #{pr.number}: {pr.title}\n{desc}".strip()


def _build_readme_chunk(content: str) -> str:
    return f"# README\n{content}"


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

    for symbol in symbols:
        file_path = file_path_map.get(symbol.file_id, "unknown")
        chunk_text = _build_chunk_text(
            file_path=file_path,
            kind=symbol.kind,
            name=symbol.name,
            source_code=symbol.source_code,
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
    commit_chunks = [
        (c, _build_commit_chunk(c))
        for c in commits
        if _token_estimate(_build_commit_chunk(c)) <= MAX_CHUNK_TOKENS
    ]
    for batch_idx, batch in enumerate(_iter_batches(commit_chunks, BATCH_SIZE)):
        batch_texts = [t for _, t in batch]
        if publish_log:
            publish_log(
                f"Embedding commits batch {batch_idx + 1}/{len(list(_iter_batches(commit_chunks, BATCH_SIZE)))}..."
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
    pr_chunks = [
        (p, _build_pr_chunk(p))
        for p in prs
        if _token_estimate(_build_pr_chunk(p)) <= MAX_CHUNK_TOKENS
    ]
    for batch_idx, batch in enumerate(_iter_batches(pr_chunks, BATCH_SIZE)):
        batch_texts = [t for _, t in batch]
        if publish_log:
            publish_log(
                f"Embedding PRs batch {batch_idx + 1}/{len(list(_iter_batches(pr_chunks, BATCH_SIZE)))}..."
            )
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
        chunk_text = _build_readme_chunk(readme_content)
        if _token_estimate(chunk_text) <= MAX_CHUNK_TOKENS:
            response = client.embeddings.create(
                model="text-embedding-3-small", input=[chunk_text]
            )
            db.add(
                Embedding(
                    source_type="document",
                    source_id=repository_id,
                    file_id=None,
                    repository_id=repository_id,
                    chunk_text=chunk_text,
                    embedding=response.data[0].embedding,
                )
            )
            db.commit()
            total_inserted += 1
            if publish_log:
                publish_log("README embedded.")

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
