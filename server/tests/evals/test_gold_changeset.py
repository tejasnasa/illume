"""Change-set items built from a synthetic repository and hand-made pull requests."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from evals.gold.changeset import (
    IdentifierIndex,
    LeakContext,
    build_changeset_items,
    identifier_tokens,
    is_noise,
    leaked_terms,
)
from evals.gold.schema import write_jsonl
from evals.mining.github_cache import CachedPR, CachedPRFile
from tests.fixtures import sample_repo

pytestmark = pytest.mark.integration

PRICING = "src/pricing.py"
BILLING = "src/billing.py"
OTHER = "src/other.py"
PRICING_TEST = "tests/test_pricing.py"
WINDOW = 4
CUTOFF = date(2026, 6, 1)

BODY = (
    "Rework `compute_total_cents` so that shared_helper_fn rounds half up instead of down. "
    "The InvoiceBuilder and invoice_line_total changes live in src/pricing.py and billing.py, "
    "see https://github.com/acme/shop/blob/main/src/billing.py for the old behaviour. "
    "<!-- internal note about reviewers -->\n"
    "- [x] tests added\n"
    "- [ ] docs updated\n"
    "Customers were being undercharged by a cent on odd totals, which finance noticed."
)


def _write(root, files):
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))


def _empty_commit(root, message):
    sample_repo._git(root, "commit", "--allow-empty", "-m", message)
    return sample_repo.head_sha(root)


def _file(path, status="modified", previous=None):
    return CachedPRFile(path, status, previous, 3, 1)


def _pr(number, sha, files, *, body=BODY, author="ada", user_type="User", merged=None):
    return CachedPR(
        number=number,
        title="Fix rounding of totals",
        body=body,
        author=author,
        merged_at=merged or datetime(2026, 7, 1, tzinfo=UTC),
        merge_commit_sha=sha,
        files=tuple(files),
        labels=(),
        user_type=user_type,
    )


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("changeset-repo")
    sample_repo._git(root, "init", "-b", "main")
    _write(
        root,
        {
            PRICING: (
                "def compute_total_cents(items):\n    return shared_helper_fn(sum(items))\n\n\n"
                "def shared_helper_fn(value):\n    return value\n"
            ),
            BILLING: (
                "class InvoiceBuilder:\n    def invoice_line_total(self):\n        return 0\n"
            ),
            OTHER: "from src.pricing import shared_helper_fn\n\nVALUE = shared_helper_fn(1)\n",
            PRICING_TEST: "def test_total():\n    assert True\n",
            "CHANGELOG.md": "# Changes\n",
            "uv.lock": "lock\n",
            "README.md": "readme\n",
        },
    )
    sample_repo.commit_all(root, "feat: initial")
    base = sample_repo.head_sha(root)

    sample_repo._git(root, "checkout", "-b", "side")
    side = _empty_commit(root, "never merged")
    sample_repo._git(root, "checkout", "main")

    sha = {n: _empty_commit(root, f"merge #{n}") for n in (1, 2, 3, 7, 5)}
    tip = sample_repo.head_sha(root)

    prs = [
        _pr(
            1,
            sha[1],
            [
                _file(PRICING),
                _file(BILLING),
                _file(PRICING_TEST),
                _file("src/new_thing.py", "added"),
                _file("CHANGELOG.md"),
                _file("uv.lock"),
            ],
        ),
        _pr(2, sha[2], [_file(PRICING), _file(BILLING)], author="dependabot[bot]", user_type="Bot"),
        _pr(3, sha[3], [_file("uv.lock")]),
        _pr(4, side, [_file(PRICING), _file(BILLING)]),
        _pr(5, sha[5], [_file(PRICING), _file(BILLING)]),
        _pr(7, sha[7], [_file("README.md"), _file("docs/guide.md", "added")]),
    ]
    build = build_changeset_items(
        repo_name="shop",
        clone=root,
        base_commit=base,
        prs=prs,
        drift_window=WINDOW,
        generator_cutoff=CUTOFF,
        tip=tip,
    )
    return SimpleNamespace(root=root, base=base, tip=tip, prs=prs, build=build)


def _by_template(world, template):
    found = [item for item in world.build.items if item.template == template]
    assert len(found) == 1
    return found[0]


def test_gold_is_the_files_that_existed_at_the_base(world):
    blind = _by_template(world, "changeset.blind")
    assert blind.gold_files == (BILLING, PRICING, PRICING_TEST)
    assert blind.absent_at_base == ("src/new_thing.py",)
    assert blind.gold_test_files == (PRICING_TEST,)
    assert blind.gold_prs == (1,)
    assert blind.post_cutoff is True


def test_changelogs_and_lockfiles_are_stripped(world):
    blind = _by_template(world, "changeset.blind")
    assert "CHANGELOG.md" not in blind.gold_files + blind.absent_at_base
    assert "uv.lock" not in blind.gold_files + blind.absent_at_base
    assert is_noise("pkg/NEWS.rst") and is_noise("a/dist/x.js") and is_noise("x_pb2.py")
    assert not is_noise("src/news_feed.py")


def test_unwanted_pull_requests_are_dropped_with_a_reason(world):
    assert dict(world.build.drops) == {
        2: "bot",
        3: "lockfile_only",
        4: "not_on_mainline",
        5: "beyond_drift_window",
        7: "docs_only",
    }


def test_variants_share_a_cluster_and_the_anchor_is_outside_the_gold(world):
    blind = _by_template(world, "changeset.blind")
    anchor = _by_template(world, "changeset.anchor")
    assert blind.cluster == anchor.cluster == "shop#1"
    assert anchor.anchor_file == BILLING
    assert anchor.gold_files == (PRICING, PRICING_TEST)
    assert anchor.gold_test_files == (PRICING_TEST,)
    assert anchor.question_seed == f"{blind.question_seed}\n\nStart from `{BILLING}`."


def test_every_item_carries_drift_and_test_marks_and_stays_inside_the_window(world):
    assert world.build.items
    for item in world.build.items:
        assert item.merges_since_base is not None
        assert 0 <= item.merges_since_base < WINDOW
        assert isinstance(item.gold_test_files, tuple)
        assert item.circular_with == ()
        assert item.family == "changeset"


def test_no_gold_path_basename_or_unique_identifier_survives_in_a_seed(world):
    blind = _by_template(world, "changeset.blind")
    anchor = _by_template(world, "changeset.anchor")
    index = IdentifierIndex(world.root, world.base, (BILLING, PRICING, PRICING_TEST))
    context = LeakContext((BILLING, PRICING, PRICING_TEST), index.is_gold_unique)
    anchor_text = anchor.question_seed.split("\n\nStart from")[0]
    for text in (blind.question_seed, anchor_text):
        assert leaked_terms(text, context) == []
        for banned in (
            "pricing",
            "billing.py",
            "compute_total_cents",
            "InvoiceBuilder",
            "invoice_line_total",
            "github.com",
            "internal note",
            "docs updated",
        ):
            assert banned not in text
    assert leaked_terms("see `src/pricing.py` and compute_total_cents", context) == [
        "compute_total_cents",
        "pricing",
        "pricing.py",
        "src/pricing.py",
    ]


def test_an_identifier_shared_with_a_non_gold_file_is_kept(world):
    blind = _by_template(world, "changeset.blind")
    assert "shared_helper_fn" in blind.question_seed
    index = IdentifierIndex(world.root, world.base, (BILLING, PRICING, PRICING_TEST))
    assert index.is_gold_unique("compute_total_cents")
    assert not index.is_gold_unique("shared_helper_fn")
    assert not index.is_gold_unique("not_anywhere_at_all")


def test_identifier_shapes():
    tokens = identifier_tokens("Use snake_case, CamelCase, a.b.c and `plain` but not words or ab")
    assert {"snake_case", "CamelCase", "a.b.c", "plain"} <= set(tokens)
    assert not {"words", "but", "ab"} & set(tokens)


def test_building_twice_gives_byte_identical_files(world, tmp_path):
    again = build_changeset_items(
        repo_name="shop",
        clone=world.root,
        base_commit=world.base,
        prs=world.prs,
        drift_window=WINDOW,
        generator_cutoff=CUTOFF,
        tip=world.tip,
    )
    first = write_jsonl(tmp_path / "a.jsonl", world.build.items).read_bytes()
    second = write_jsonl(tmp_path / "b.jsonl", again.items).read_bytes()
    assert first == second
    assert first.count(b"\n") == len(world.build.items) == 2
