"""Choosing each repository's questions to match its mix, and the build's defaults."""

from datetime import date
from pathlib import Path

import pytest

from evals.corpus.corpus import CorpusRepo, QuestionMix
from evals.gold import build as build_module
from evals.gold.build import build_gold
from evals.gold.changeset import ChangesetBuild
from evals.gold.check import CheckRecord, checks_path, item_content_hash
from evals.gold.hand import load_hand_items
from evals.gold.mix import select_change_items, select_explain_items
from evals.gold.schema import make_item, read_jsonl
from tests.evals.judge_helpers import endpoint

pytestmark = pytest.mark.unit

BASE = "b" * 40


def _change(pr: int, *, anchor: bool = False):
    fields = dict(
        repo="demo",
        base_commit=BASE,
        family="changeset",
        template="changeset.anchor" if anchor else "changeset.blind",
        question_seed=f"Pull request {pr}\n\nIt changes the handler.",
        gold_files=(f"src/f{pr}.py",),
        gold_prs=(pr,),
        merges_since_base=pr,
        cluster=f"demo#{pr}",
    )
    if anchor:
        fields["anchor_file"] = f"src/anchor{pr}.py"
    return make_item(**fields)


def _hand(n: int, kind: str = "explain", **over):
    fields = dict(
        repo="demo",
        base_commit=BASE,
        family="hand",
        template=f"hand.{kind}",
        question=f"How does thing {n} work?",
        question_seed=f"How does thing {n} work?",
        gold_files=(f"src/h{n}.py",),
        reference_answer=f"Thing {n} does a job.",
    )
    if kind == "unanswerable":
        fields.update(gold_files=(), reference_answer="", tags=("unanswerable",))
    fields.update(over)
    return make_item(**fields)


class TestChangeSelection:
    def test_it_takes_the_requested_number_of_blind_items_deterministically(self):
        items = [_change(n) for n in range(30)]
        first = select_change_items(items, 12, seed=3)
        again = select_change_items(list(reversed(items)), 12, seed=3)
        other = select_change_items(items, 12, seed=4)

        assert len(first.items) == 12 and first.shortfall == 0
        assert first.items == again.items
        assert {i.id for i in first.items} != {i.id for i in other.items}

    def test_the_anchor_variants_are_left_out_unless_asked_for(self):
        items = [item for n in range(10) for item in (_change(n), _change(n, anchor=True))]

        blind = select_change_items(items, 10, seed=0)
        both = select_change_items(items, 10, seed=0, include_anchor=True)

        assert {i.template for i in blind.items} == {"changeset.blind"}
        assert len({i.cluster for i in blind.items}) == 10
        assert len(both.items) == 10 and len({i.cluster for i in both.items}) == 5

    def test_a_small_pool_is_reported_as_a_shortfall_not_an_error(self):
        selection = select_change_items([_change(n) for n in range(4)], 10, seed=0)

        assert len(selection.items) == 4
        assert (selection.requested, selection.available, selection.shortfall) == (10, 4, 6)


class TestExplainSelection:
    def test_unanswerable_items_are_excluded_by_default(self):
        items = [_hand(n) for n in range(3)] + [_hand(9, "unanswerable")]

        default = select_explain_items(items, 10, seed=0)
        included = select_explain_items(items, 10, seed=0, include_unanswerable=True)

        assert len(default.items) == 3 and default.shortfall == 7
        assert len(included.items) == 4

    def test_it_is_seeded_and_caps_at_the_request(self):
        items = [_hand(n) for n in range(20)]

        first = select_explain_items(items, 5, seed=1)

        assert len(first.items) == 5
        assert first.items == select_explain_items(list(reversed(items)), 5, seed=1).items
        assert first.items != select_explain_items(items, 5, seed=2).items


class TestQuestionMix:
    def test_the_default_mix_is_thirty_five_and_twenty_five(self):
        mix = QuestionMix()
        assert (mix.change, mix.explain, mix.total) == (35, 25, 60)

    def test_a_negative_count_is_rejected(self):
        with pytest.raises(ValueError):
            QuestionMix(change=-1)


class TestBuild:
    @pytest.fixture
    def wired(self, tmp_path, monkeypatch):
        """``build_gold`` with the clone, the cache and the change-set builder faked."""
        clones = tmp_path / "clones"
        out = tmp_path / "out"
        changes = [item for n in range(8) for item in (_change(n), _change(n, anchor=True))]
        calls: dict[str, int] = {"rationale": 0, "structural": 0}

        def rationale(**kwargs):
            calls["rationale"] += 1
            return []

        async def structural(*args, **kwargs):
            calls["structural"] += 1
            return []

        monkeypatch.setattr(build_module, "clone_dir", lambda *a: clones)
        clones.mkdir()
        monkeypatch.setattr(build_module, "rev_exists", lambda *a: True)
        monkeypatch.setattr(build_module, "default_tip", lambda clone: "tip")
        monkeypatch.setattr(
            build_module,
            "load_index",
            lambda *a: type("Index", (), {"post_base": [], "pre_base": []})(),
        )
        monkeypatch.setattr(build_module, "load_prs", lambda *a: [])
        monkeypatch.setattr(
            build_module, "build_changeset_items", lambda **kw: ChangesetBuild(items=changes)
        )

        async def ready(*args, **kwargs):
            return "repo-id"

        monkeypatch.setattr(build_module, "_ready_repo_id", ready)
        monkeypatch.setattr(build_module, "build_rationale_items", rationale)
        monkeypatch.setattr(build_module, "build_structural_items", structural)
        monkeypatch.setattr(build_module, "files_at", lambda *a: set())
        return out, clones, calls

    def _repo(self, **mix) -> CorpusRepo:
        return CorpusRepo(
            name="demo",
            url="https://github.com/octo/demo",
            language="Python",
            licence="MIT",
            base_commit=BASE,
            generator_cutoff=date(2026, 10, 17),
            questions=QuestionMix(**mix),
        )

    def _hand_file(self, tmp_path: Path, explain: int, unanswerable: int = 1) -> Path:
        lines = ["items:"]
        for n in range(explain):
            lines += [
                "  - kind: explain",
                f"    question: How does thing {n} work?",
                f"    reference_answer: Thing {n} does a job.",
                f"    required_files: [src/h{n}.py]",
            ]
        for n in range(unanswerable):
            lines += ["  - kind: unanswerable", f"    question: Does it do thing {n}?"]
        path = tmp_path / "hand.yaml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    async def _build(self, wired, tmp_path, *, explain=6, mix=None, **options):
        out, clones, _ = wired
        return await build_gold(
            None,
            corpus_repo=self._repo(**(mix or {"change": 5, "explain": 4})),
            out_dir=out,
            clones_dir=clones,
            hand_file=self._hand_file(tmp_path, explain),
            **options,
        )

    async def test_the_defaults_build_blind_change_and_explain_items_only(self, wired, tmp_path):
        outcome = await self._build(wired, tmp_path)

        items = read_jsonl(outcome.items_path)
        assert sorted({i.template for i in items if i.family == "changeset"}) == ["changeset.blind"]
        assert outcome.counts == {"changeset": 5, "hand": 4}
        assert not any("unanswerable" in i.tags for i in items)
        assert wired[2] == {"rationale": 0, "structural": 0}
        assert outcome.log["options"] == {
            "include_anchor": False,
            "include_rationale": False,
            "include_structural": False,
            "include_unanswerable": False,
        }

    async def test_shortfalls_are_reported_in_the_log(self, wired, tmp_path):
        outcome = await self._build(wired, tmp_path, explain=2, mix={"change": 20, "explain": 5})

        assert outcome.log["mix"]["change"] == {
            "requested": 20,
            "available": 8,
            "selected": 8,
            "shortfall": 12,
        }
        assert outcome.log["mix"]["explain"]["shortfall"] == 3
        assert outcome.counts == {"changeset": 8, "hand": 2}

    async def test_the_optional_kinds_and_variants_switch_back_on(self, wired, tmp_path):
        out, clones, calls = wired
        outcome = await build_gold(
            None,
            corpus_repo=self._repo(change=16, explain=4),
            out_dir=out,
            clones_dir=clones,
            hand_file=self._hand_file(tmp_path, 3, unanswerable=1),
            include_anchor=True,
            include_rationale=True,
            include_structural=True,
            include_unanswerable=True,
        )

        items = read_jsonl(outcome.items_path)
        assert {i.template for i in items if i.family == "changeset"} == {
            "changeset.blind",
            "changeset.anchor",
        }
        assert any("unanswerable" in i.tags for i in items)
        assert calls == {"rationale": 1, "structural": 1}

    async def test_unsupported_items_are_dropped_and_partly_supported_ones_reported(
        self, wired, tmp_path
    ):
        out, *_ = wired
        hand_file = self._hand_file(tmp_path, 4)
        hand = load_hand_items(hand_file, repo_name="demo", base_commit=BASE)
        hand.sort(key=lambda i: i.question)
        gone, partly = hand[0], hand[1]
        directory = out / "gold" / "demo"
        checker = endpoint()
        verdicts = [
            (gone, "unsupported", "It names a file that is not there."),
            (partly, "partly_supported", "The second step is wrong."),
        ]
        lines = []
        for item, verdict, claim in verdicts:
            record = CheckRecord(
                check_key=f"k{item.id}",
                item_id=item.id,
                content_hash=item_content_hash(item),
                repo="demo",
                verdict=verdict,
                faulty_claim=claim,
                model=checker.model,
                host=checker.host,
                prompt_version="1",
            )
            lines.append(record.model_dump_json())
        path = checks_path(directory, checker)
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        outcome = await build_gold(
            None,
            corpus_repo=self._repo(change=0, explain=10),
            out_dir=out,
            clones_dir=wired[1],
            hand_file=hand_file,
        )

        kept = {i.id for i in read_jsonl(outcome.items_path)}
        assert gone.id not in kept and partly.id in kept
        assert outcome.log["checks"]["dropped_unsupported"] == [gone.id]
        assert outcome.log["checks"]["partly_supported"] == [
            {"item": partly.id, "faulty_claim": "The second step is wrong."}
        ]
