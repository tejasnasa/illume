"""``corpus ingest | snapshot | restore | report``."""

import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Repository
from app.services.llm_config import LLMConfig
from app.services.llm_providers import PROVIDERS
from evals.corpus.corpus import CORPUS_PATH, CorpusError, load_corpus
from evals.corpus.ingest import ingest_at_base
from evals.corpus.report import corpus_counts, format_table
from evals.corpus.snapshot import SnapshotError, restore, snapshot

EVAL_USER_EMAIL = "eval-harness@example.com"
GENERATOR_MODEL = "deepseek-v4-1-flash-1017"


def generator_config(api_key: str) -> LLMConfig:
    """Build the pinned generator configuration.

    Args:
        api_key: The generator's API key.

    Returns:
        A config for the pinned model at the DeepSeek registry's base URL.

    Raises:
        CorpusError: If the key is empty.
    """
    if not api_key:
        raise CorpusError("AI_API_KEY is not set in server/evals/.env.eval")
    deepseek = PROVIDERS["deepseek"]
    return LLMConfig(
        api_key=api_key,
        model=GENERATOR_MODEL,
        base_url=deepseek.base_url,
        supports_reasoning=deepseek.supports_reasoning,
        source="server",
        supports_strict_tools=deepseek.supports_strict_tools,
    )


def snapshot_path(out_dir: Path, name: str) -> Path:
    """Return where a named snapshot lives under the output directory."""
    return Path(out_dir) / "snapshots" / f"{name}.dump"


def cmd_ingest(
    *,
    sync_url: str,
    out_dir: Path,
    api_key: str,
    repo_name: str,
    corpus_path: Path = CORPUS_PATH,
) -> int:
    """Ingest one corpus repository at its base commit.

    Args:
        sync_url: The eval database's sync URL.
        out_dir: The eval output directory; the GitHub cache is ``<out_dir>/github``.
        api_key: The generator API key.
        repo_name: The corpus entry to ingest.
        corpus_path: The corpus file.

    Returns:
        The process exit status.
    """
    try:
        corpus_repo = load_corpus(corpus_path).get(repo_name)
        llm = generator_config(api_key)
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    engine = create_engine(sync_url)
    try:
        with sessionmaker(bind=engine)() as db:
            result = ingest_at_base(
                db,
                corpus_repo=corpus_repo,
                user_email=EVAL_USER_EMAIL,
                cache_dir=Path(out_dir) / "github",
                llm_config=llm,
            )
    finally:
        engine.dispose()
    print(f"repository {result.repo_id} ingested at {result.base_commit[:12]}")
    print(f"history pull requests: {len(result.inserted_pr_numbers)}")
    print(format_table({corpus_repo.name: result.counts}))
    return 0


def cmd_snapshot(*, sync_url: str, out_dir: Path, name: str) -> int:
    """Dump the eval database to ``<out_dir>/snapshots/<name>.dump``."""
    try:
        target = snapshot(sync_url, snapshot_path(out_dir, name))
    except SnapshotError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"snapshot written: {target}")
    return 0


def cmd_restore(*, sync_url: str, out_dir: Path, name: str) -> int:
    """Restore ``<out_dir>/snapshots/<name>.dump`` into the eval database."""
    try:
        restore(sync_url, snapshot_path(out_dir, name))
    except SnapshotError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"snapshot restored: {snapshot_path(out_dir, name)}")
    return 0


def cmd_report(*, sync_url: str) -> int:
    """Print per-repository counts for every ready repository in the eval database."""
    engine = create_engine(sync_url)
    try:
        with sessionmaker(bind=engine)() as db:
            repos = db.execute(
                select(Repository.id, Repository.name)
                .where(Repository.status == "ready")
                .order_by(Repository.name, Repository.created_at)
            ).all()
            names = [name for _, name in repos]
            rows = {
                (name if names.count(name) == 1 else f"{name}@{str(repo_id)[:8]}"): corpus_counts(
                    db, repo_id
                )
                for repo_id, name in repos
            }
    finally:
        engine.dispose()
    if not rows:
        print("no ingested repositories")
        return 0
    print(format_table(rows))
    return 0
