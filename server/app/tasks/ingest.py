import logging

from app.core.celery import celery
from app.core.database import get_sync_db
from app.core.redis import get_sync_redis
from app.models.repository import Repository
from app.services.ingestion import (
    cleanup_clone,
    clone_repository,
    embed_repository_symbols,
    process_repository_files,
    score_repository_health,
)
from app.services.summarizer import generate_repo_summary

logger = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=3)
def ingest_repository(self, repo_id: str, access_token: str | None = None):
    db = next(get_sync_db())
    redis_client = get_sync_redis()

    def publish(msg: str):
        redis_client.publish(f"task:{repo_id}:logs", msg)

    try:
        repo = db.query(Repository).filter(Repository.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        tmp_dir = clone_repository(db, redis_client, repo, access_token)

        try:
            process_repository_files(db, redis_client, repo, tmp_dir)
        finally:
            cleanup_clone(tmp_dir)

        embed_repository_symbols(db, redis_client, repo)

        score_repository_health(db, redis_client, repo)

        publish("Generating architecture summary...")
        summary = generate_repo_summary(
            repo_id=repo.id,
            repo_name=repo.name,
            db=db,
        )
        repo.summary = summary

        repo.status = "ready"
        db.commit()
        publish("Ingestion complete!")
        publish("DONE")

    except Exception as exc:
        logger.exception("Ingestion failed for repo %s", repo_id)
        try:
            repo = db.query(Repository).filter(Repository.id == repo_id).first()
            if repo:
                repo.status = "failed"
                db.commit()
        except Exception:
            pass
        publish(f"Error: {exc}")
        publish("ERROR")
        raise self.retry(exc=exc, countdown=10)

    finally:
        db.close()
