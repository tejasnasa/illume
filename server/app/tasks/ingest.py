import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

from app.core.celery import celery
from app.core.database import get_sync_db
from app.core.redis import get_sync_redis
from app.models.repository import Repository
from app.services._stage_timer import stage
from app.services.cloner import cleanup_clone, clone_repository
from app.services.criticality import run_criticality_scoring
from app.services.git_analyzer import analyze_git_history
from app.services.scanner import embed_repository_symbols, process_repository_files
from app.tasks._parallel import (
    run_brief_in_thread,
    run_glossary_in_thread,
    run_pr_fetch_in_thread,
    run_reading_order_in_thread,
)

logger = logging.getLogger(__name__)


@contextmanager
def get_db_context():
    """Wrap ``get_sync_db`` so its ``except`` rollback branch actually runs.

    ``get_sync_db`` is a generator with an ``except Exception: rollback`` arm, but the
    original wrapper resumed it with ``next(gen)``, which exits cleanly and silently
    skips the rollback. Threading the exception back in with ``gen.throw`` makes the
    rollback reachable.
    """
    gen = get_sync_db()
    db = next(gen)
    exc: BaseException | None = None
    try:
        yield db
    except BaseException as e:
        exc = e
    finally:
        try:
            if exc is not None:
                gen.throw(exc)
            else:
                next(gen)
        except StopIteration:
            pass


@celery.task(bind=True, max_retries=3)
def ingest_repository(
    self,
    repo_id: str,
    access_token: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
):
    redis_client = get_sync_redis()

    def publish(event: str, message: str, **kwargs):
        data = {
            "event": event,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        redis_client.publish(f"task:{repo_id}:logs", json.dumps(data))

    with get_db_context() as db:
        try:
            repo = db.query(Repository).filter(Repository.id == repo_id).first()
            if not repo:
                raise ValueError(f"Repository {repo_id} not found")

            with stage("clone"):
                tmp_dir, actual_branch, actual_sha = clone_repository(
                    db,
                    redis_client,
                    repo,
                    access_token,
                    branch=branch,
                    commit_sha=commit_sha,
                )

            # Capture the only two fields the parallel threads need; this
            # is what stops them from reaching back into the main session's
            # identity map (a stale-instance hazard if
            # ``expire_on_commit=False`` were ever flipped on).
            repo_id_value: UUID = repo.id
            repo_github_url: str = repo.github_url

            repo.ingested_branch = actual_branch
            repo.ingested_commit_sha = actual_sha
            db.commit()

            pr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest-pr")
            pr_future = pr_executor.submit(
                run_pr_fetch_in_thread,
                repo_id_value,
                repo_github_url,
                access_token,
                redis_client,
            )

            readme_content = None
            try:
                # ``process_repository_files`` carries its own per-stage timers
                # (parse / resolve_dependencies / compute_fan_metrics /
                # detect_stack), so it is deliberately not wrapped again here --
                # a nesting timer would double-count their memory deltas.
                process_repository_files(db, redis_client, repo, tmp_dir)
                with stage("git_history"):
                    analyze_git_history(db, redis_client, repo, tmp_dir)

                for name in ("README.md", "readme.md", "Readme.md"):
                    readme_path = os.path.join(tmp_dir, name)
                    if os.path.exists(readme_path):
                        with open(readme_path, "r", errors="ignore") as f:
                            readme_content = f.read()
                        break
            finally:
                cleanup_clone(tmp_dir)

            try:
                pr_future.result()
            finally:
                pr_executor.shutdown(wait=True)

            publish("criticality_started", "Scoring file criticality...")
            with stage("criticality"):
                run_criticality_scoring(db, repo.id)

            publish("glossary_started", "Building project glossary...")
            publish("reading_order_started", "Generating recommended reading order...")
            parallel_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingest-llm")
            try:
                glossary_future = parallel_executor.submit(
                    run_glossary_in_thread, repo_id_value, repo_github_url
                )
                reading_order_future = parallel_executor.submit(
                    run_reading_order_in_thread, repo_id_value, repo_github_url
                )
                # Wall-clock for the overlapped pair. Comparing it against the
                # two helpers' individual walls shows whether the overlap paid
                # off: the pair should land near max(glossary, reading_order),
                # not their sum.
                with stage("glossary_and_reading_order_join", measure_memory=False):
                    glossary_future.result()
                    reading_order_future.result()
            finally:
                parallel_executor.shutdown(wait=True)

            publish("embedding_started", "Generating embeddings...")
            publish("brief_started", "Synthesizing AI architecture brief...")
            brief_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest-brief")
            try:
                brief_future = brief_executor.submit(
                    run_brief_in_thread, repo_id_value, readme_content
                )
                with stage("embed_and_brief_join", measure_memory=False):
                    embed_repository_symbols(
                        db,
                        redis_client,
                        repo,
                        readme_content=readme_content,
                        measure_memory=False,
                    )
                    # Joined before ``status = "ready"`` so a brief failure
                    # still fails the ingest, exactly as it did when the call
                    # was sequential.
                    brief_future.result()
            finally:
                brief_executor.shutdown(wait=True)

            repo.status = "ready"
            db.commit()
            publish("status_update", "Ingestion complete!", status="ready")
            publish("done", "DONE")

        except Exception as exc:
            logger.exception("Ingestion failed for repo %s", repo_id)
            db.rollback()
            try:
                repo = db.query(Repository).filter(Repository.id == repo_id).first()
                if repo:
                    repo.status = "failed"
                    db.commit()
            except Exception:
                pass
            publish("status_update", f"Error: {exc}", status="failed")
            publish("error", "ERROR")
            raise self.retry(exc=exc, countdown=10)

        finally:
            db.close()
