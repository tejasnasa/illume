"""File criticality scoring.

Assigns each indexed file a criticality level ("critical", "caution", or
"safe") based on fan-in, path patterns, staleness, and test coverage, with
human-readable reasons for the score.
"""

import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import File

# Regexes matched against file paths to flag core infrastructure files.
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
    """Score a single file and return (criticality level, reasons)."""
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
        # Normalize naive DB timestamps to UTC before comparing.
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        if (now - last_modified).days > 180:
            score += 1
            reasons.append("untouched for 6+ months")

    if not file.has_tests:
        # Untested code is riskier to change, so it scores higher.
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
    """Score every file in a repository and persist the results.

    Args:
        db: Database session used to read files and persist scores.
        repo_id: ID of the repository whose files should be scored.

    Returns:
        Number of files scored.
    """
    files = db.query(File).filter(File.repository_id == repo_id).all()

    for f in files:
        f.criticality, f.criticality_reasons = _score_file(f)

    db.commit()
    return len(files)
