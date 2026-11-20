"""Capturing a run's context into its directory, so the report never needs the eval database.

After a generation pass the run directory receives ``gold.jsonl`` (the slice's items),
``gold_labels.jsonl`` (the hand verdicts on the gold), ``corpus_counts.json`` (counts per
repository, with its language), ``files_at_base.json`` (every file at the base commit) and
``graph.json`` (the import adjacency, file to the files it imports) and ``style.json`` (how the
codebases differ, from the database and, for commit messages, the harness clones). Reading the
database happens here and only here; :mod:`evals.report.load` reads the files.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import File, Repository, User
from app.services.file_graph import build_adjacency, query_file_edges
from evals.corpus.corpus import CORPUS_PATH, CorpusError, load_corpus
from evals.corpus.report import corpus_counts
from evals.corpus.style import repo_style, write_style
from evals.gold.schema import GoldItem, write_jsonl
from evals.gold.verify import Label, append_label, read_labels
from evals.mining.clones import clone_dir
from evals.report.load import (
    CORPUS_COUNTS,
    FILES_AT_BASE,
    GOLD_COPY,
    GOLD_LABELS_COPY,
    GRAPH,
    STYLE,
)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def capture_run_context(
    db: Session,
    *,
    run_dir: Path,
    items: Sequence[GoldItem],
    out_dir: Path,
    user_email: str,
    corpus_path: Path = CORPUS_PATH,
    clones_dir: Path | None = None,
) -> list[str]:
    """Write the report's context files into a run directory.

    Args:
        db: A sync session on the database the repositories were ingested into.
        run_dir: The run directory.
        items: The slice's gold items.
        out_dir: The eval output directory, where the gold hand labels live.
        user_email: The user the repositories were ingested for.
        corpus_path: The corpus file, for each repository's language, era and base commit.
        clones_dir: Where the harness clones live, for the commit measurements of the style
            file; those are left out when it is omitted or a clone is missing.

    Returns:
        The names of repositories that were not found ready in the database and so were left
        out of the context files.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(run_dir / GOLD_COPY, items)
    names = sorted({item.repo for item in items})

    seen: dict[str, Label] = {}
    for name in names:
        directory = Path(out_dir) / "gold" / name
        for path in sorted(directory.glob("labels*.jsonl")) if directory.is_dir() else []:
            for label in read_labels(path):
                seen.setdefault(label.item_id, label)
    labels_path = run_dir / GOLD_LABELS_COPY
    labels_path.unlink(missing_ok=True)
    for label in seen.values():
        append_label(labels_path, label)

    try:
        corpus = load_corpus(corpus_path)
    except CorpusError:
        corpus = None

    counts: dict[str, Any] = {}
    files: dict[str, list[str]] = {}
    graph: dict[str, dict[str, list[str]]] = {}
    styles: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name in names:
        repository = (
            db.execute(
                select(Repository)
                .join(User, User.id == Repository.user_id)
                .where(
                    User.email == user_email,
                    Repository.name == name,
                    Repository.status == "ready",
                )
                .order_by(Repository.created_at.desc())
            )
            .scalars()
            .first()
        )
        if repository is None:
            missing.append(name)
            continue
        entry = corpus_counts(db, repository.id)
        pinned = _corpus_entry(corpus, name)
        if pinned is not None:
            entry["language"] = pinned.language
            if pinned.era:
                entry["era"] = pinned.era
            if pinned.base_date:
                entry["base_date"] = pinned.base_date.isoformat()
        counts[name] = entry
        base_commit = repository.ingested_commit_sha or (pinned.base_commit if pinned else "")
        clone = clone_dir(clones_dir, pinned.slug) if clones_dir and pinned else None
        styles[name] = repo_style(
            db, repository.id, clone if clone and clone.exists() else None, base_commit
        )
        paths = {
            row.id: row.path
            for row in db.execute(
                select(File.id, File.path).where(File.repository_id == repository.id)
            ).all()
        }
        files[name] = sorted(paths.values())
        deps, _ = build_adjacency(query_file_edges(db, repository.id))
        graph[name] = {
            paths[src]: sorted(paths[t] for t in targets if t in paths)
            for src, targets in sorted(deps.items(), key=lambda pair: paths.get(pair[0], ""))
            if src in paths
        }
    _write_json(run_dir / CORPUS_COUNTS, counts)
    _write_json(run_dir / FILES_AT_BASE, files)
    _write_json(run_dir / GRAPH, graph)
    write_style(run_dir / STYLE, styles)
    return missing


def _corpus_entry(corpus: Any, name: str) -> Any:
    """The corpus entry named ``name``, or ``None`` without a corpus or an entry."""
    if corpus is None:
        return None
    try:
        return corpus.get(name)
    except CorpusError:
        return None


def capture_from_url(
    sync_url: str,
    *,
    run_dir: Path,
    items: Sequence[GoldItem],
    out_dir: Path,
    user_email: str,
    corpus_path: Path = CORPUS_PATH,
    clones_dir: Path | None = None,
) -> list[str]:
    """:func:`capture_run_context` on a session opened (and closed) from a sync URL."""
    engine = create_engine(sync_url)
    try:
        with sessionmaker(bind=engine)() as db:
            return capture_run_context(
                db,
                run_dir=run_dir,
                items=items,
                out_dir=out_dir,
                user_email=user_email,
                corpus_path=corpus_path,
                clones_dir=clones_dir,
            )
    finally:
        engine.dispose()


__all__ = ["capture_from_url", "capture_run_context"]
