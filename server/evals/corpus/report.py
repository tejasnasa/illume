"""Row counts per ingested repository, for the corpus table."""

from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AstSymbol,
    Commit,
    Dependency,
    Embedding,
    File,
    FileCochange,
    PullRequest,
)

COLUMNS = ("files", "symbols", "edges", "commits", "prs", "cochange_pairs")


def _count(db: Session, model, *where) -> int:
    """Count rows of ``model`` matching ``where``."""
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


def corpus_counts(db: Session, repo_id) -> dict:
    """Count what ingestion stored for one repository.

    Args:
        db: A sync session.
        repo_id: The repository to count.

    Returns:
        ``{"files", "symbols", "edges", "commits", "prs", "cochange_pairs"}`` as ints, plus
        ``"embeddings"``, a mapping from ``source_type`` to count. Edges are dependency rows
        whose source symbol belongs to the repository.
    """
    file_ids = select(File.id).where(File.repository_id == repo_id)
    symbol_ids = select(AstSymbol.id).where(AstSymbol.file_id.in_(file_ids))
    by_type = db.execute(
        select(Embedding.source_type, func.count())
        .where(Embedding.repository_id == repo_id)
        .group_by(Embedding.source_type)
    ).all()
    return {
        "files": _count(db, File, File.repository_id == repo_id),
        "symbols": _count(db, AstSymbol, AstSymbol.file_id.in_(file_ids)),
        "edges": _count(db, Dependency, Dependency.source_symbol_id.in_(symbol_ids)),
        "commits": _count(db, Commit, Commit.repository_id == repo_id),
        "prs": _count(db, PullRequest, PullRequest.repository_id == repo_id),
        "cochange_pairs": _count(db, FileCochange, FileCochange.repository_id == repo_id),
        "embeddings": {str(source_type): int(n) for source_type, n in by_type},
    }


def format_table(rows: Mapping[str, dict]) -> str:
    """Render per-repository counts as a plain-text table.

    Args:
        rows: Repository name to the dict ``corpus_counts`` returns.

    Returns:
        A fixed-width table, one line per repository, with an embeddings total column.
    """
    headers = ("repo", *COLUMNS, "embeddings")
    body = [
        [
            name,
            *(str(counts[column]) for column in COLUMNS),
            str(sum(counts["embeddings"].values())),
        ]
        for name, counts in rows.items()
    ]
    widths = [max(len(row[i]) for row in [list(headers), *body]) for i in range(len(headers))]

    def line(cells) -> str:
        first, rest = cells[0].ljust(widths[0]), cells[1:]
        return "  ".join([first, *(c.rjust(w) for c, w in zip(rest, widths[1:], strict=True))])

    separator = "  ".join("-" * w for w in widths)
    return "\n".join([line(list(headers)), separator, *(line(row) for row in body)])
