"""Tests for the corpus file loader."""

import pytest

from evals.corpus.corpus import CORPUS_PATH, CorpusError, load_corpus

pytestmark = pytest.mark.unit

SHA = "0123456789abcdef0123456789abcdef01234567"


def _write(tmp_path, body: str):
    path = tmp_path / "corpus.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _entry(**overrides) -> str:
    fields = {
        "name": "demo",
        "url": "https://github.com/owner/demo",
        "language": "Python",
        "licence": "MIT",
        "base_commit": f'"{SHA}"',
    }
    fields.update(overrides)
    lines = [
        f"{'  - ' if i == 0 else '    '}{key}: {value}"
        for i, (key, value) in enumerate(fields.items())
    ]
    return "repos:\n" + "\n".join(lines) + "\n"


def test_a_valid_entry_loads_with_defaults(tmp_path):
    repo = load_corpus(_write(tmp_path, _entry())).get("demo")
    assert repo.base_commit == SHA
    assert str(repo.generator_cutoff) == "2026-10-17"
    assert repo.drift_window == 100
    assert repo.history_prs == 200
    assert repo.slug == "owner/demo"


def test_overrides_and_base_date_are_read(tmp_path):
    body = _entry(base_date="2026-06-01", drift_window=50, history_prs=120)
    repo = load_corpus(_write(tmp_path, body)).repos[0]
    assert (repo.drift_window, repo.history_prs) == (50, 120)
    assert str(repo.base_date) == "2026-06-01"


@pytest.mark.parametrize("licence", ["GPL-3.0", "Proprietary", "mit"])
def test_a_non_permissive_licence_is_rejected(tmp_path, licence):
    with pytest.raises(CorpusError, match="permissive"):
        load_corpus(_write(tmp_path, _entry(licence=licence)))


@pytest.mark.parametrize("licence", ["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"])
def test_every_permissive_licence_is_accepted(tmp_path, licence):
    assert load_corpus(_write(tmp_path, _entry(licence=licence))).repos[0].licence == licence


@pytest.mark.parametrize("sha", ["abc123", "G" * 40, "A" * 40, "0" * 39])
def test_a_bad_base_commit_is_rejected(tmp_path, sha):
    with pytest.raises(CorpusError, match="40"):
        load_corpus(_write(tmp_path, _entry(base_commit=f'"{sha}"')))


def test_an_unquoted_all_digit_sha_is_rejected_not_coerced(tmp_path):
    body = _entry(base_commit="1" * 40)
    with pytest.raises(CorpusError, match="quoted"):
        load_corpus(_write(tmp_path, body))


def test_duplicate_names_are_rejected(tmp_path):
    body = _entry() + _entry().removeprefix("repos:\n")
    with pytest.raises(CorpusError, match="unique"):
        load_corpus(_write(tmp_path, body))


def test_an_unknown_field_is_rejected(tmp_path):
    with pytest.raises(CorpusError):
        load_corpus(_write(tmp_path, _entry(colour="red")))


def test_an_unknown_name_lists_the_known_ones(tmp_path):
    corpus = load_corpus(_write(tmp_path, _entry()))
    with pytest.raises(CorpusError, match="demo"):
        corpus.get("other")


def test_the_shipped_corpus_parses_and_lists_no_repositories():
    assert load_corpus(CORPUS_PATH).repos == []
