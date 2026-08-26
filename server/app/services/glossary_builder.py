"""Builds plain-English glossary definitions for a repository's key symbols.

Selects the most-referenced symbols (by file fan-in), asks an LLM in small
batches to write 1-2 sentence definitions from each symbol's docstring and
source, parses the JSON responses, and replaces the repository's stored
`GlossaryEntry` rows with the results.
"""

import json
import logging
import uuid

from openai import OpenAI
from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AstSymbol, File, GlossaryEntry, Repository

logger = logging.getLogger(__name__)

# Symbols per LLM request; keeps prompts and JSON responses well under limits.
BATCH_SIZE = 25


def _get_top_symbols(
    db: Session, repository_id: uuid.UUID, limit: int = 200
) -> list[Row[tuple[AstSymbol, File]]]:
    """Fetches the top symbols by file fan-in, joined with their files."""
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
    """Builds the batch prompt requesting JSON name/definition pairs."""
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
    """Parses the LLM's JSON array into a name-to-definition map; returns {} on malformed output."""
    clean = (
        text.strip()
        # Models often wrap JSON in markdown fences; strip them before parsing.
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    try:
        parsed = json.loads(clean)
        return {item["name"]: item["definition"] for item in parsed}
    except json.JSONDecodeError as e:
        logger.error(
            f"[glossary] Failed to parse LLM response: {e}\nRaw: {clean[:200]}"
        )
        return {}


def build_glossary(db: Session, repo: Repository) -> int:
    """Regenerate glossary definitions for a repository.

    Deletes all existing `GlossaryEntry` rows for the repository, selects
    up to 200 of its most-referenced symbols, requests plain-English
    definitions from the LLM in batches of ``BATCH_SIZE``, and persists one
    entry per symbol that received a definition. Name matching is done
    case-insensitively to tolerate LLM casing drift.

    Args:
        db: SQLAlchemy session used for queries and persistence.
        repo: Repository whose glossary should be rebuilt.

    Returns:
        Number of glossary entries created.
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    logger.info(f"[glossary] Starting for repo {repo.id}")

    db.query(GlossaryEntry).filter(GlossaryEntry.repository_id == repo.id).delete()
    db.commit()

    pairs = _get_top_symbols(db, repo.id)
    if not pairs:
        logger.warning(f"[glossary] No symbols found for repo {repo.id}")
        return 0

    logger.info(f"[glossary] Processing {len(pairs)} symbols")

    all_definitions: dict[str, str] = {}

    for i in range(0, len(pairs), BATCH_SIZE):
        batch = pairs[i : i + BATCH_SIZE]
        prompt = _build_prompt(batch)

        # Small batches keep prompts/responses within token limits; a failed
        # or malformed batch just yields fewer definitions, not a total loss.
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

    # Rebuild a lowercase lookup per pair rather than once — cheap here, but
    # matching is case-insensitive because the LLM may alter capitalization.
    created = 0
    lower_definitions = {k.lower(): v for k, v in all_definitions.items()}
    for symbol, file in pairs:
        definition = lower_definitions.get(symbol.name.lower())
        if not definition:
            logger.warning(f"[glossary] Missing definition for: {symbol.name}")
            continue

        entry = GlossaryEntry(
            repository_id=repo.id,
            symbol_id=symbol.id,
            name=symbol.name,
            definition=definition,
            file_path=file.path,
            line_number=symbol.start_line,
        )
        db.add(entry)
        created += 1

    db.commit()
    logger.info(f"[glossary] Done. {created} entries created for repo {repo.id}")
    return created
