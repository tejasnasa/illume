import logging
from typing import Generator
from uuid import UUID

from app.core.config import settings
from app.models import AstSymbol, Embedding, File
from openai import OpenAI
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EMBEDDABLE_KINDS = {"function", "class", "method"}

MAX_CHUNK_TOKENS = 2048

BATCH_SIZE = 100


def _build_chunk_text(file_path: str, kind: str, name: str, source_code: str) -> str:
    return f"# {file_path}\n## {kind}: {name}\n{source_code}"


def _token_estimate(text: str) -> int:  # token estimate: 4 chars per token
    return len(text) // 4


def _iter_batches(items: list, batch_size: int) -> Generator[list, None, None]:
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def generate_embeddings(
    repository_id: UUID,
    db: Session,
    publish_log=None,
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

    total_inserted = 0
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
            symbol, chunk_text = batch[i]

            db_embedding = Embedding(
                source_type="symbol",
                source_id=symbol.id,
                file_id=symbol.file_id,
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
