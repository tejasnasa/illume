"""Exact and fuzzy matching of identifiers in the question against symbol names."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.channels._common import SEARCHABLE_KINDS_SQL
from app.services.retrieval.channels._symbols import SymbolRow, symbol_candidates
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.config import ChannelSpec, SymbolChannel
from app.services.retrieval.identifiers import identifier_tokens

_THRESHOLD_SETTING = "pg_trgm.similarity_threshold"
_DEFAULT_THRESHOLD = "0.3"

# ``%`` is the index-backed trigram operator; ``similarity(...) > x`` is not. The
# partial index also needs the kind predicate repeated verbatim. The exact
# comparison is there so an exact name still matches when the threshold is 1.
_MATCH_NAMES = text(
    f"""
    SELECT s.id, s.file_id, f.path, s.kind::text AS kind, s.name, s.start_line, s.end_line,
           s.source_code, COALESCE(f.fan_in, 0) AS fan_in,
           (s.name = :token) AS is_exact,
           similarity(s.name, :token) AS score
    FROM ast_symbols s
    JOIN files f ON f.id = s.file_id
    WHERE f.repository_id = :repo
      AND s.{SEARCHABLE_KINDS_SQL}
      AND (s.name % :token OR s.name = :token)
    ORDER BY is_exact DESC, score DESC, f.fan_in DESC NULLS LAST, s.id
    LIMIT :k
    """
)


async def _match_tokens(
    db: AsyncSession,
    repository_id: UUID,
    tokens: list[str],
    *,
    k: int,
    min_similarity: float,
) -> list[tuple[SymbolRow, bool, float]]:
    """Runs the name query for each token under the requested similarity threshold.

    The threshold is a transaction-local setting; the previous value is put back
    afterwards because the session outlives this search. If a query fails the
    transaction is aborted and the setting goes with it.
    """
    previous = (
        await db.execute(text("SELECT current_setting(:name, true)"), {"name": _THRESHOLD_SETTING})
    ).scalar_one_or_none()
    await db.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": _THRESHOLD_SETTING, "value": str(min_similarity)},
    )
    best: dict[UUID, tuple[SymbolRow, bool, float]] = {}
    for token in tokens:
        result = await db.execute(_MATCH_NAMES, {"repo": repository_id, "token": token, "k": k})
        for row in result:
            fields = dict(row._mapping)
            is_exact = bool(fields.pop("is_exact"))
            similarity = float(fields.pop("score"))
            symbol = SymbolRow(**fields)
            score = 1.0 if is_exact else similarity
            known = best.get(symbol.id)
            if known is None or (is_exact, score) > (known[1], known[2]):
                best[symbol.id] = (symbol, is_exact, score)
    await db.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": _THRESHOLD_SETTING, "value": previous or _DEFAULT_THRESHOLD},
    )
    return list(best.values())


class SymbolSearch:
    """Finds symbols whose names the question mentions, spelled exactly or nearly."""

    kind = "symbol"

    async def search(
        self, ctx: RetrievalContext, variant: QueryVariant, spec: ChannelSpec
    ) -> list[Candidate]:
        """Returns up to ``spec.k`` symbols named by identifiers in the variant.

        Identifier-like tokens are pulled from the text; each is matched against
        symbol names exactly and then fuzzily, above ``spec.min_similarity``. An
        exact name beats any fuzzy one, then higher similarity, then the file
        that more of the repository imports. A ``hyde`` variant is searched by
        the dense channel only, so it returns nothing here.

        Raises:
            TypeError: When ``spec`` is not a :class:`SymbolChannel`.
        """
        if not isinstance(spec, SymbolChannel):
            raise TypeError(f"symbol channel given a {type(spec).__name__}")
        if variant.kind == "hyde":
            return []
        tokens = identifier_tokens(variant.text)
        if not tokens:
            return []

        matches = await _match_tokens(
            ctx.db,
            ctx.repository_id,
            tokens,
            k=spec.k,
            min_similarity=spec.min_similarity,
        )
        matches.sort(key=lambda m: (not m[1], -m[2], -m[0].fan_in, m[0].id))
        ranked = [(symbol, score) for symbol, _, score in matches[: spec.k]]
        return await symbol_candidates(ctx.db, ctx.repository_id, ranked, variant, self.kind)
