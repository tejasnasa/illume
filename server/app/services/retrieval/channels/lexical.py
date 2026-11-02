"""Full-text search over every chunk, with identifiers split into words."""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.sql.expression import cast

from app.models import Embedding
from app.services.retrieval.candidate import Candidate, QueryVariant
from app.services.retrieval.channels._common import embedding_candidates
from app.services.retrieval.channels.base import RetrievalContext
from app.services.retrieval.config import ChannelSpec, LexicalChannel
from app.services.retrieval.identifiers import lexical_text

_WORD = re.compile(r"[A-Za-z0-9]+")

# Question and filler words. They are common enough in chunk text that matching
# on them ranks nothing, and with an OR query each one would pull in every chunk
# that happens to contain it.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "any", "are", "be", "by", "can", "do", "does", "for",
        "from", "how", "in", "is", "it", "of", "on", "or", "that", "the", "there",
        "this", "to", "what", "when", "where", "which", "who", "why", "with",
    }
)  # fmt: skip

# A pasted stack trace or file would otherwise become a thousand-term query.
MAX_QUERY_TOKENS = 64


def query_tokens(text: str) -> list[str]:
    """The distinct, lower-cased search terms of a query, stop words removed.

    The text goes through the same identifier splitting the index applies, so
    ``getUserById`` yields ``get``, ``user``, ``id`` and the whole identifier.

    Args:
        text: The query variant's text.

    Returns:
        Terms in order of first appearance; empty when only stop words remain.
    """
    words = (word.lower() for word in _WORD.findall(lexical_text(text)))
    terms = dict.fromkeys(word for word in words if word not in STOP_WORDS)
    return list(terms)[:MAX_QUERY_TOKENS]


def or_query(text: str) -> str | None:
    """A ``to_tsquery`` string matching any term of the query, or ``None`` when empty.

    Terms are alphanumeric, so joining them with ``|`` cannot form operators or
    break the tsquery grammar.
    """
    tokens = query_tokens(text)
    return " | ".join(tokens) if tokens else None


async def lexical_rows(
    db: AsyncSession,
    repository_id: UUID,
    query_text: str,
    *,
    k: int,
    source_types: Sequence[str] | None = None,
) -> list[tuple[Embedding, float]]:
    """The chunks of one repository matching any term of the query, best first.

    Ranked by ``ts_rank_cd`` with length normalisation 32, then by row id so
    equal ranks come back in a stable order.

    Args:
        db: The request's session.
        repository_id: The only repository searched.
        query_text: The query variant's text.
        k: How many rows to return at most.
        source_types: When given, only chunks of these types are searched.

    Returns:
        ``(row, rank)`` pairs; empty when the query has no usable terms.
    """
    query = or_query(query_text)
    if query is None:
        return []
    tsquery = func.to_tsquery(cast(literal("simple"), REGCONFIG), query)
    rank = func.ts_rank_cd(Embedding.search_tsv, tsquery, 32)
    statement = (
        select(Embedding, rank.label("rank"))
        .options(defer(Embedding.embedding))
        .where(Embedding.repository_id == repository_id, Embedding.search_tsv.op("@@")(tsquery))
    )
    if source_types is not None:
        statement = statement.where(Embedding.source_type.in_(list(source_types)))
    rows = (await db.execute(statement.order_by(rank.desc(), Embedding.id).limit(k))).all()
    return [(row[0], float(row[1])) for row in rows]


class LexicalSearch:
    """Keyword search that matches an identifier whole and as its words."""

    kind = "lexical"

    async def search(
        self, ctx: RetrievalContext, variant: QueryVariant, spec: ChannelSpec
    ) -> list[Candidate]:
        """Returns up to ``spec.k`` chunks sharing a term with the variant.

        A ``hyde`` variant is hypothetical code rather than a question, so it is
        left to the dense channel and this returns nothing for it.

        Raises:
            TypeError: When ``spec`` is not a :class:`LexicalChannel`.
        """
        if not isinstance(spec, LexicalChannel):
            raise TypeError(f"lexical channel given a {type(spec).__name__}")
        if variant.kind == "hyde":
            return []
        rows = await lexical_rows(ctx.db, ctx.repository_id, variant.text, k=spec.k)
        return await embedding_candidates(ctx.db, rows, variant, self.kind)
