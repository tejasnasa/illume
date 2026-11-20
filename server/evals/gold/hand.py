"""Load the hand-written questions from ``hand/<repo>.yaml``.

The format and the writing rules are in ``hand/GUIDE.md``; ``hand/example.yaml`` shows the
shape and is never loaded for a real repository.
"""

from pathlib import Path

import yaml

from app.services.test_files import is_test_path
from evals.gold.schema import GoldItem, make_item

HAND_DIR = Path(__file__).with_name("hand")
KINDS = ("architecture", "flow", "unanswerable")


class HandError(ValueError):
    """Raised when a hand file is unreadable or an entry breaks the format."""


def hand_path(repo_name: str) -> Path:
    """Return where a repository's hand file lives."""
    return HAND_DIR / f"{repo_name}.yaml"


def _strings(value: object, label: str) -> tuple[str, ...]:
    """Read a string or list of strings field."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(entry, str) for entry in value):
        return tuple(value)
    raise HandError(f"{label} must be a string or a list of strings")


def load_hand_items(path: Path, *, repo_name: str, base_commit: str) -> list[GoldItem]:
    """Read a hand file into gold items.

    Args:
        path: The YAML file.
        repo_name: The corpus entry's name.
        base_commit: The commit the repository was ingested at.

    Returns:
        One item per entry, template ``hand.<kind>``, ``gold_files`` the required files and
        ``acceptable_files`` the optional ones. An ``unanswerable`` entry has no files and is
        tagged ``unanswerable``. A missing file gives an empty list.

    Raises:
        HandError: If the file cannot be parsed or an entry is malformed.
    """
    path = Path(path)
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise HandError(f"cannot read {path}: {exc}") from exc
    entries = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise HandError(f"{path}: expected an `items` list")

    items: list[GoldItem] = []
    for position, entry in enumerate(entries, 1):
        label = f"{path.name} item {position}"
        if not isinstance(entry, dict):
            raise HandError(f"{label}: expected a mapping")
        kind = entry.get("kind")
        question = entry.get("question")
        if kind not in KINDS:
            raise HandError(f"{label}: kind must be one of {', '.join(KINDS)}")
        if not isinstance(question, str) or not question.strip():
            raise HandError(f"{label}: question is required")
        required = _strings(entry.get("required_files"), f"{label} required_files")
        acceptable = _strings(entry.get("acceptable_files"), f"{label} acceptable_files")
        if kind == "unanswerable" and (required or acceptable):
            raise HandError(f"{label}: an unanswerable item has no files")
        if kind != "unanswerable" and not required:
            raise HandError(f"{label}: required_files is empty")
        tags = _strings(entry.get("tags"), f"{label} tags")
        if kind == "unanswerable" and "unanswerable" not in tags:
            tags = (*tags, "unanswerable")
        items.append(
            make_item(
                repo=repo_name,
                base_commit=base_commit,
                family="hand",
                template=f"hand.{kind}",
                question=question.strip(),
                question_seed=question.strip(),
                gold_files=required,
                gold_test_files=tuple(p for p in required if is_test_path(p)),
                acceptable_files=acceptable,
                gold_answer_notes=_strings(entry.get("notes"), f"{label} notes"),
                tags=tags,
            )
        )
    return items
