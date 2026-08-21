import re
from datetime import datetime, timezone
from uuid import UUID

from app.models import File
from sqlalchemy.orm import Session

CRITICAL_PATH_PATTERNS = [
    r"config\.",
    r"database\.",
    r"middleware/",
    r"migrations/",
    r"auth\.",
    r"security\.",
    r"celery\.",
    r"main\.",
]


def _score_file(file: File) -> tuple[str, list[str]]:
    score = 0
    reasons: list[str] = []
    now = datetime.now(tz=timezone.utc)

    fan_in = file.fan_in or 0
    if fan_in >= 10:
        score += 3
        reasons.append(f"imported by {fan_in} files")
    elif fan_in >= 5:
        score += 1
        reasons.append(f"imported by {fan_in} files")

    if any(re.search(p, file.path) for p in CRITICAL_PATH_PATTERNS):
        score += 2
        reasons.append("core infrastructure file")

    if file.git_last_modified:
        last_modified = file.git_last_modified
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        if (now - last_modified).days > 180:
            score += 1
            reasons.append("untouched for 6+ months")

    if not file.has_tests:
        score += 1
        reasons.append("no test coverage")

    if score >= 4:
        criticality = "critical"
    elif score >= 2:
        criticality = "caution"
    else:
        criticality = "safe"

    return criticality, reasons


def run_criticality_scoring(db: Session, repo_id: UUID) -> int:
    files = db.query(File).filter(File.repository_id == repo_id).all()

    for f in files:
        f.criticality, f.criticality_reasons = _score_file(f)

    db.commit()
    return len(files)
