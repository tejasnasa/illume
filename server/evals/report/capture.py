"""Capturing a run's context into its directory, so the report never needs the eval database.

After a generation pass the run directory receives ``gold.jsonl`` (the slice's items),
``gold_labels.jsonl`` (the hand verdicts on the gold), ``corpus_counts.json`` (counts per
repository, with its language), ``files_at_base.json`` (every file at the base commit) and
``graph.json`` (the import adjacency, file to the files it imports). Reading the database happens
here and only here; :mod:`evals.report.load` reads the files.
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
from evals.gold.schema import GoldItem, write_jsonl
from evals.gold.verify import Label, append_label, read_labels
from evals.report.load import (
    CORPUS_COUNTS,
    FILES_AT_BASE,
    GOLD_COPY,
    GOLD_LABELS_COPY,
    GRAPH,
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
) -> list[str]:
    """Write the report's context files into a run directory.

    Args:
        db: A sync session on the database the repositories were ingested into.
        run_dir: The run directory.
        items: The slice's gold items.
        out_dir: The eval output directory, where the gold hand labels live.
        user_email: The user the repositories were ingested for.
        corpus_path: The corpus file, for each repository's language.

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
        language = _language(corpus, name)
        if language:
            entry["language"] = language
        counts[name] = entry
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
    return missing


def _language(corpus: Any, name: str) -> str | None:
    if corpus is None:
        return None
    try:
        return str(corpus.get(name).language)
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
            )
    finally:
        engine.dispose()


__all__ = ["capture_from_url", "capture_run_context"]
