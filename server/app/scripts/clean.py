# server/test.py
from app.core.database import get_sync_db
from app.models.repository import Repository
from app.models.file import File
from app.models.ast_symbol import AstSymbol
from app.models.dependency import Dependency
from app.models.embedding import Embedding
from app.models.health_metric import HealthMetric

db = next(get_sync_db())

try:
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