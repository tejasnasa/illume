# services/glossary_builder.py

import json
import logging
import uuid

from app.core.config import settings
from app.models import AstSymbol, File, GlossaryEntry
from openai import OpenAI
from sqlalchemy import Row
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

BATCH_SIZE = 25


def _get_top_symbols(
    db: Session, repository_id: uuid.UUID, limit: int = 50
) -> list[Row[tuple[AstSymbol, File]]]:
    return (
        db.query(AstSymbol, File)
        .join(File, AstSymbol.file_id == File.id)
        .filter(File.repository_id == repository_id)
        .filter(AstSymbol.kind.in_(["function", "class", "method", "variable"]))
        .order_by(File.fan_in.desc())
        .limit(limit)
        .all()
    )


def _build_prompt(pairs: list[Row[tuple[AstSymbol, File]]]) -> str:
    entries = []
    for symbol, file in pairs:
        parts = [
            f"Name: {symbol.name}",
            f"File: {file.path}",
            f"Lines: {symbol.start_line}-{symbol.end_line}",
        ]
        if symbol.docstring:
            parts.append(f"Docstring: {symbol.docstring}")
        if symbol.source_code:
            parts.append(f"Source (truncated):\n{symbol.source_code[:300]}")
        entries.append("\n".join(parts))

    joined = "\n\n---\n\n".join(entries)

    return f"""You are analyzing a software codebase. For each symbol below, write a plain-English definition (1-2 sentences) that a new engineer would understand on day one. Focus on what it does and why it exists, not how it's implemented.

Respond ONLY with a JSON array. Each element must have exactly these two keys:
- "name": the symbol name (copy exactly as given)
- "definition": your plain-English explanation

Symbols:
{joined}"""


def _parse_response(text: str) -> dict[str, str]:
    clean = (
        text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    print(clean)
    try:
        parsed = json.loads(clean)
        return {item["name"]: item["definition"] for item in parsed}
    except json.JSONDecodeError as e:
        logger.error(
            f"[glossary] Failed to parse LLM response: {e}\nRaw: {clean[:200]}"
        )
        return {}


def build_glossary(db: Session, repository_id: uuid.UUID) -> int:
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    logger.info(f"[glossary] Starting for repo {repository_id}")

    db.query(GlossaryEntry).filter(
        GlossaryEntry.repository_id == repository_id
    ).delete()
    db.commit()

    pairs = _get_top_symbols(db, repository_id)
    if not pairs:
        logger.warning(f"[glossary] No symbols found for repo {repository_id}")
        return 0

    logger.info(f"[glossary] Processing {len(pairs)} symbols")

    all_definitions: dict[str, str] = {}

    for i in range(0, len(pairs), BATCH_SIZE):
        batch = pairs[i : i + BATCH_SIZE]
        prompt = _build_prompt(batch)

        response = client.responses.create(
            model=settings.AI_MODEL,
            reasoning={"effort": "minimal"},
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=2000,
        )

        definitions = _parse_response(response.output_text or "")
        all_definitions.update(definitions)
        logger.info(
            f"[glossary] Batch {i // BATCH_SIZE + 1} done ({len(definitions)} definitions)"
        )

    created = 0
    for symbol, file in pairs:
        definition = all_definitions.get(symbol.name)
        if not definition:
            logger.warning(f"[glossary] Missing definition for: {symbol.name}")
            continue

        entry = GlossaryEntry(
            repository_id=repository_id,
            symbol_id=symbol.id,
            name=symbol.name,
            definition=definition,
            file_path=file.path,
            line_number=symbol.start_line,
        )
        db.add(entry)
        created += 1

    db.commit()
    logger.info(f"[glossary] Done. {created} entries created for repo {repository_id}")
    return created
