import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone

from app.core.celery import celery
from app.core.database import get_sync_db
from app.core.redis import get_sync_redis
from app.models.repository import Repository
from app.services._stage_timer import stage
from app.services.cloner import cleanup_clone, clone_repository
from app.services.pipeline import run_full_analysis
from app.tasks._parallel import run_pr_fetch_in_thread

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
            from uuid import UUID

            repo_id_value: UUID = repo.id
            repo_github_url: str = repo.github_url

            repo.ingested_branch = actual_branch
            repo.ingested_commit_sha = actual_sha
            db.commit()

            # PR fetch overlaps the parse work: it is purely a network
            # round-trip plus its own session, and the original
            # ``ingest_repository`` overlapped it for exactly that reason.
            # The pipeline itself runs PR fetch after parse, so this
            # backgrounded fetch is the only place the overlap survives.
            pr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest-pr")
            pr_future = pr_executor.submit(
                run_pr_fetch_in_thread,
                repo_id_value,
                repo_github_url,
                access_token,
                redis_client,
            )

            try:
                # ``manage_status=True`` preserves today's
                # ``status='parsing'/'embedding'`` transitions for the
                # initial-ingest path; the sync task passes ``False``.
                run_full_analysis(
                    db,
                    repo,
                    tmp_dir,
                    redis_client,
                    publish,
                    manage_status=True,
                    overlap_llm=True,
                )
            finally:
                cleanup_clone(tmp_dir)

            try:
                pr_future.result()
            finally:
                pr_executor.shutdown(wait=True)

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
