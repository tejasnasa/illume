"""The gold item schema and its deterministic JSONL form.

An item's id is a content hash of the fields that define it, so rebuilding from the same
inputs yields the same ids. The file format is canonical: items sorted by id, keys sorted,
compact separators, ``\n`` endings and UTF-8, with no timestamps, so two builds from the
same inputs are byte-identical.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Family = Literal["changeset", "rationale", "structural", "hand"]
Verdict = Literal["correct", "wrong", "ambiguous"]

ID_HEX_LENGTH = 16

# The fields that define an item. The question's phrasing and the verification verdict are
# excluded, so rephrasing or verifying an item never changes its id.
ID_FIELDS = (
    "repo",
    "base_commit",
    "family",
    "template",
    "question_seed",
    "gold_files",
    "anchor_file",
    "gold_prs",
    "gold_commits",
)

_CIRCULAR_BY_FAMILY = {"rationale": ("history",), "structural": ("graph",)}


class GoldItem(BaseModel):
    """One question with its answer key.

    Attributes:
        id: Content hash of the defining fields; see ``compute_id``.
        repo: Corpus entry name.
        base_commit: The commit the repository was ingested at.
        family: ``changeset``, ``rationale``, ``structural`` or ``hand``.
        template: The generator, such as ``changeset.anchor`` or ``hand.flow``.
        question: The phrased question; empty until phrasing fills it (hand items carry
            their written question here).
        question_seed: The text the question is phrased from.
        gold_files: The files that are scored, sorted.
        gold_test_files: The subset of ``gold_files`` that are tests.
        acceptable_files: Hand items only: files that are also acceptable but not required.
        anchor_file: ``changeset.anchor`` only: the file named as a starting point. It is
            not in ``gold_files``.
        absent_at_base: Files the pull request touched that did not exist at the base
            commit; kept aside and never scored.
        gold_prs: Pull request numbers the answer rests on.
        gold_commits: Commits the answer rests on.
        gold_answer_notes: Facts quoted from the source, for the judge.
        circular_with: Channels whose data the item was derived from.
        post_cutoff: Whether the source pull request merged after the generator's cutoff.
        merges_since_base: How many mainline merges after the base commit the pull request
            was (0 is the first). Change-set items only.
        cluster: Items sharing a cluster are not independent; ``<repo>#<pr>``.
        tags: Free-form labels.
        verified: The human verdict, or ``None`` before verification.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    repo: str
    base_commit: str
    family: Family
    template: str
    question: str = ""
    question_seed: str
    gold_files: tuple[str, ...] = ()
    gold_test_files: tuple[str, ...] = ()
    acceptable_files: tuple[str, ...] = ()
    anchor_file: str | None = None
    absent_at_base: tuple[str, ...] = ()
    gold_prs: tuple[int, ...] = ()
    gold_commits: tuple[str, ...] = ()
    gold_answer_notes: tuple[str, ...] = ()
    circular_with: tuple[str, ...] = ()
    post_cutoff: bool | None = None
    merges_since_base: int | None = None
    cluster: str | None = None
    tags: tuple[str, ...] = ()
    verified: Verdict | None = None

    @field_validator("gold_files", "gold_test_files", "acceptable_files", "absent_at_base")
    @classmethod
    def _sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not set(self.gold_test_files) <= set(self.gold_files):
            raise ValueError("gold_test_files must be a subset of gold_files")
        if self.anchor_file is not None:
            if self.template != "changeset.anchor":
                raise ValueError("only changeset.anchor items carry an anchor_file")
            if self.anchor_file in self.gold_files:
                raise ValueError("the anchor file must not be in gold_files")
        elif self.template == "changeset.anchor":
            raise ValueError("a changeset.anchor item needs an anchor_file")
        if self.family == "changeset":
            if self.cluster is None or self.merges_since_base is None:
                raise ValueError("change-set items need cluster and merges_since_base")
            if self.circular_with:
                raise ValueError("change-set items are not circular")
        expected = _CIRCULAR_BY_FAMILY.get(self.family)
        if expected is not None and self.circular_with != expected:
            raise ValueError(f"{self.family} items must have circular_with={expected}")
        return self


def compute_id(item_fields: Mapping[str, Any]) -> str:
    """Hash the fields that define an item.

    Args:
        item_fields: Item fields by name. Only the defining fields are read; absent ones
            take their empty default, and ``gold_files`` is compared sorted.

    Returns:
        The first ``ID_HEX_LENGTH`` hex characters of the SHA-256 of the canonical JSON.
    """
    payload: dict[str, Any] = {}
    for name in ID_FIELDS:
        value = item_fields.get(name)
        if name == "gold_files":
            value = sorted(set(value or ()))
        elif name in ("gold_prs", "gold_commits"):
            value = list(value or ())
        payload[name] = value
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:ID_HEX_LENGTH]


def make_item(**fields: Any) -> GoldItem:
    """Build an item and fill its id.

    Args:
        **fields: Every ``GoldItem`` field except ``id``.

    Returns:
        The validated item carrying ``compute_id`` of its defining fields.

    Raises:
        ValueError: If the fields break a schema rule.
    """
    draft = GoldItem(id="", **fields)
    return draft.model_copy(update={"id": compute_id(draft.model_dump())})


def canonical_json(value: Any) -> str:
    """Serialise ``value`` in the canonical form used by every gold file."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def write_jsonl(path: Path, items: Iterable[GoldItem]) -> Path:
    """Write items as canonical JSONL sorted by id.

    Args:
        path: The file to write; parent directories are created.
        items: The items to write.

    Returns:
        The path written.
    """
    ordered = sorted(items, key=lambda item: item.id)
    text = "".join(canonical_json(item.model_dump(mode="json")) + "\n" for item in ordered)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    return target


def read_jsonl(path: Path) -> list[GoldItem]:
    """Read items back from a JSONL file.

    Args:
        path: A file written by ``write_jsonl``.

    Returns:
        The items in file order.
    """
    text = Path(path).read_text(encoding="utf-8")
    return [GoldItem.model_validate_json(line) for line in text.split("\n") if line.strip()]
