from app.core.database import get_sync_db
from app.models import (
    AstSymbol,
    CodeOwner,
    Commit,
    Dependency,
    Embedding,
    File,
    GlossaryEntry,
    HealthMetric,
    OnboardingGuide,
    PullRequest,
    Repository,
)

db = next(get_sync_db())

try:
    db.query(CodeOwner).delete()
    db.query(Commit).delete()
    db.query(GlossaryEntry).delete()
    db.query(OnboardingGuide).delete()
    db.query(PullRequest).delete()
    db.query(Embedding).delete()
    db.query(Dependency).delete()
    db.query(HealthMetric).delete()
    db.query(AstSymbol).delete()
    db.query(File).delete()
    db.query(Repository).delete()

    db.commit()
    print("All tables cleared")
except Exception as e:
    db.rollback()
    print(f"Error: {e}")
finally:
    db.close()
