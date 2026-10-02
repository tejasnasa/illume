"""Builds plain-English glossary definitions for a repository's key symbols.

Selects the most-referenced symbols (by file fan-in), asks an LLM in small
batches to write 1-2 sentence definitions from each symbol's docstring and
source, parses the JSON responses, and replaces the repository's stored
`GlossaryEntry` rows with the results.

The glossary holds one entry per distinct symbol name -- the highest fan-in
definition site wins -- and symbols the parser could not name are never
selected.

Concurrency shape: the LLM batches are submitted in parallel
through :func:`app.services._concurrency.gather_in_order`. Worker threads
do the network call only; the parent thread collects responses in input
order and does all ``Session`` writes serially. The "failed batch yields
fewer definitions, not a total loss" contract is unchanged from before --
:func:`_parse_response` still swallows JSON errors, so a single malformed
batch is just absent from the glossary rather than fatal.
"""

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any, Literal, cast

from openai import OpenAI
from sqlalchemy import Row, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AstSymbol, File, GlossaryEntry, Repository
from app.services._concurrency import gather_in_order
from app.services.llm_config import LLMConfig

logger = logging.getLogger(__name__)

# Symbols per LLM request; keeps prompts and JSON responses well under limits.
BATCH_SIZE = 25

# How many ranked symbols to fetch per entry the glossary may store. The
# one-row-per-name trim discards same-named duplicates, so fetching exactly
# ``limit`` would under-fill whenever the top of the ranking repeats a name.
CANDIDATE_MULTIPLIER = 5

# The repository's glossary is bounded to this many entries. ``full`` mode
# fills the budget; ``incremental`` mode refills any empty slots in the
# current top-N without ever exceeding the cap.
MAX_GLOSSARY_ENTRIES = 200


def _get_top_symbols(
    db: Session,
    repository_id: uuid.UUID,
    limit: int = MAX_GLOSSARY_ENTRIES,
    *,
    exclude_with_entry: bool = False,
) -> list[Row[tuple[AstSymbol, File]]]:
    """Fetches the top symbols by file fan-in, joined with their files.

    Returns at most ``limit`` rows and at most one row per distinct symbol
    name: the highest fan-in symbol wins, so the glossary holds one entry per
    term rather than one per definition site. Symbols the parser could not
    name (``"<anonymous>"``) are never returned.

    ``exclude_with_entry=True`` returns only symbols without a
    ``GlossaryEntry`` for the repo -- the incremental mode's working set:
    symbols that need a definition written for them. An entry counts as
    already written when it matches either the symbol's ``symbol_id`` or its
    name, so a same-named symbol in a newly-changed file is not defined a
    second time.
    """
    stmt = (
        select(AstSymbol, File)
        .join(File, AstSymbol.file_id == File.id)
        .where(File.repository_id == repository_id)
        .where(AstSymbol.kind.in_(["function", "class", "method", "variable"]))
        .where(AstSymbol.name != "<anonymous>")
    )
    if exclude_with_entry:
        stmt = stmt.where(
            ~select(GlossaryEntry.id)
            .where(GlossaryEntry.repository_id == repository_id)
            .where(
                or_(
                    GlossaryEntry.symbol_id == AstSymbol.id,
                    func.lower(GlossaryEntry.name) == func.lower(AstSymbol.name),
                )
            )
            .exists()
        )

    rows = db.execute(stmt.order_by(File.fan_in.desc()).limit(limit * CANDIDATE_MULTIPLIER)).all()

    # Rows arrive fan-in descending, so the first sighting of a name is its
    # most-referenced definition site.
    best: dict[str, Row[tuple[AstSymbol, File]]] = {}
    for row in rows:
        best.setdefault(row[0].name.lower(), row)
    return list(best.values())[:limit]


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
        logger.error(f"[glossary] Failed to parse LLM response: {e}\nRaw: {clean[:200]}")
        return {}


def build_glossary(
    db: Session,
    repo: Repository,
    *,
    mode: Literal["full", "incremental"] = "full",
    llm: LLMConfig | None = None,
) -> int:
    """Regenerate glossary definitions for a repository.

    ``mode="full"`` deletes all existing ``GlossaryEntry`` rows for the
    repository, then selects up to ``MAX_GLOSSARY_ENTRIES`` of its
    most-referenced symbols and asks the LLM to define them in batches.

    ``mode="incremental"`` skips the delete: it selects symbols lacking
    an entry, ranked by the *current* file fan-in, and refills empty
    slots in the top-N budget. The glossary never exceeds
    ``MAX_GLOSSARY_ENTRIES``: a newly-promoted symbol whose definition
    was already cached stays cached, and entries that fall out of the
    top-N are not regenerated.

    Name matching is case-insensitive on the LLM side; a missing
    definition just means the LLM dropped a name, not that the entry
    was lost.

    Args:
        db: SQLAlchemy session used for queries and persistence.
        repo: Repository whose glossary should be updated.
        mode: ``"full"`` for initial ingest; ``"incremental"`` for the
            sync task.
        llm: The credential bundle to authenticate the LLM call with.
            ``None`` falls through to the server key for backwards
            compatibility -- the route layer's quota gates 
            are what make ``None`` legitimate in production.

    Returns:
        Number of glossary entries created.
    """
    client_kwargs = llm.client_kwargs() if llm is not None else {"api_key": settings.OPENAI_API_KEY}
    client = OpenAI(**client_kwargs)
    model = llm.model if llm is not None else settings.AI_MODEL
    # Resolve the per-call ``responses.create`` extras once. The legacy
    # ``llm=None`` path keeps the historical ``reasoning.effort="minimal"``
    # payload; the configured-byok path delegates to ``LLMConfig`` so a
    # reasoning-incapable preset (Groq) sends an empty dict rather than
    # 400-ing on a parameter the model does not understand.
    response_kwargs = (
        llm.response_kwargs("minimal") if llm is not None else {"reasoning": {"effort": "minimal"}}
    )
    if not response_kwargs:
        response_kwargs = {"reasoning": {"effort": "minimal"}}

    logger.info("[glossary] Starting for repo %s (mode=%s)", repo.id, mode)

    if mode == "full":
        db.query(GlossaryEntry).filter(GlossaryEntry.repository_id == repo.id).delete()
        db.commit()

    # ``MAX_GLOSSARY_ENTRIES`` bounds the glossary, not the query: in
    # incremental mode the entries already stored stay, so the budget for
    # new ones is what is left of it. Asking for the full cap while
    # excluding symbols that already have an entry selects the next N
    # *undefined* symbols instead, which grows the glossary by up to the cap
    # on every update rather than refilling the empty slots.
    if mode == "incremental":
        stored = (
            db.query(func.count(GlossaryEntry.id))
            .filter(GlossaryEntry.repository_id == repo.id)
            .scalar()
            or 0
        )
        budget = max(0, MAX_GLOSSARY_ENTRIES - stored)
    else:
        budget = MAX_GLOSSARY_ENTRIES

    pairs = _get_top_symbols(
        db,
        repo.id,
        limit=budget,
        exclude_with_entry=(mode == "incremental"),
    )
    if not pairs:
        logger.warning("[glossary] No symbols need entries for repo %s", repo.id)
        return 0

    logger.info("[glossary] Processing %d symbols", len(pairs))

    all_definitions: dict[str, str] = {}

    # Build the prompts up front so the pool's workers carry no per-batch
    # closure over the ORM rows. The ``client`` is built once above and
    # shared across threads (``httpx.Client`` is thread-safe).
    batches: list[list[Row[tuple[AstSymbol, File]]]] = [
        pairs[i : i + BATCH_SIZE] for i in range(0, len(pairs), BATCH_SIZE)
    ]
    prompts: list[str] = [_build_prompt(batch) for batch in batches]

    responses = gather_in_order(
        [
            cast(
                Callable[[], Any],
                (
                    lambda p=prompt: client.responses.create(
                        model=model,
                        **response_kwargs,
                        input=[{"role": "user", "content": p}],
                        max_output_tokens=3000,
                    )
                ),
            )
            for prompt in prompts
        ],
        label="glossary",
    )

    for batch_idx, response in enumerate(responses):
        # Small batches keep prompts/responses within token limits; a failed
        # or malformed batch just yields fewer definitions, not a total loss.
        definitions = _parse_response(response.output_text or "")
        all_definitions.update(definitions)
        logger.info(f"[glossary] Batch {batch_idx + 1} done ({len(definitions)} definitions)")

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
