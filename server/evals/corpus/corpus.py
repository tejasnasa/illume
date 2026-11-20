"""Load and validate ``corpus.yaml``."""

import re
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

CORPUS_PATH = Path(__file__).with_name("corpus.yaml")
PERMISSIVE_LICENCES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"})
DEFAULT_GENERATOR_CUTOFF = date(2026, 10, 17)

_SHA = re.compile(r"^[0-9a-f]{40}$")


class CorpusError(ValueError):
    """Raised when the corpus file is missing, malformed or names an unknown repository."""


class CorpusRepo(BaseModel):
    """One repository pinned at a base commit.

    Attributes:
        name: Short identifier used on the command line.
        url: The clone URL (a local path is accepted, which tests rely on).
        language: The repository's main language.
        licence: An SPDX id from ``PERMISSIVE_LICENCES``.
        base_commit: The 40-hex commit ``B`` everything is ingested at.
        base_date: When ``B`` was committed; informational.
        generator_cutoff: The generator model's training cutoff; pull requests merged after
            it are tagged post-cutoff.
        drift_window: How many commits after ``B`` the drift check looks at.
        history_prs: How many merged pull requests before ``B`` are ingested as history.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    url: str
    language: str
    licence: str
    base_commit: str
    base_date: date | None = None
    generator_cutoff: date = DEFAULT_GENERATOR_CUTOFF
    drift_window: int = 100
    history_prs: int = 200

    @field_validator("licence")
    @classmethod
    def _permissive_only(cls, value: str) -> str:
        if value not in PERMISSIVE_LICENCES:
            allowed = ", ".join(sorted(PERMISSIVE_LICENCES))
            raise ValueError(f"licence {value!r} is not permissive; use one of: {allowed}")
        return value

    @field_validator("base_commit", mode="before")
    @classmethod
    def _full_sha(cls, value: object) -> str:
        # YAML reads an unquoted all-digit SHA as an integer and drops leading zeros, so a
        # non-string is rejected rather than coerced.
        if not isinstance(value, str) or not _SHA.match(value):
            raise ValueError("base_commit must be a quoted, full 40-character lowercase hex SHA")
        return value

    @property
    def slug(self) -> str:
        """The ``owner/repo`` slug derived from the URL, as the GitHub cache keys it."""
        path = self.url.rstrip("/").removesuffix(".git")
        parts = [p for p in re.split(r"[/\\:]", path) if p]
        return "/".join(parts[-2:]) if len(parts) >= 2 else self.name


class Corpus(BaseModel):
    """The whole corpus file.

    Attributes:
        repos: Every pinned repository.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repos: list[CorpusRepo] = []

    @field_validator("repos")
    @classmethod
    def _unique_names(cls, value: list[CorpusRepo]) -> list[CorpusRepo]:
        names = [repo.name for repo in value]
        if len(set(names)) != len(names):
            raise ValueError("repository names must be unique")
        return value

    def get(self, name: str) -> CorpusRepo:
        """Look a repository up by name.

        Args:
            name: The repository's ``name``.

        Returns:
            The matching entry.

        Raises:
            CorpusError: If no entry has that name.
        """
        for repo in self.repos:
            if repo.name == name:
                return repo
        known = ", ".join(r.name for r in self.repos) or "none"
        raise CorpusError(f"no repository named {name!r} in the corpus (known: {known})")


def load_corpus(path: Path = CORPUS_PATH) -> Corpus:
    """Read and validate a corpus file.

    Args:
        path: The YAML file; the shipped ``corpus.yaml`` by default.

    Returns:
        The validated corpus.

    Raises:
        CorpusError: If the file cannot be read or fails validation.
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CorpusError(f"cannot read {path}: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise CorpusError(f"{path}: expected a mapping at the top level")
    try:
        return Corpus.model_validate(raw)
    except ValueError as exc:
        raise CorpusError(f"{path}: {exc}") from exc
