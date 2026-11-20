"""The independent check of reference answers: prompt, caching, errors, metering and the command."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
import respx

from evals.cli.gold_commands import cmd_gold_check
from evals.gold import check as check_module
from evals.gold.check import (
    CHECKER_PROMPT_VERSION,
    FILE_CHAR_BUDGET,
    CheckRecord,
    apply_checks,
    check_items,
    check_key,
    checks_path,
    final_checks,
    item_content_hash,
    read_checks,
    render_files,
)
from evals.run.budget import Budget
from evals.run.metering import Meter
from tests.evals.judge_helpers import FakeJudge, endpoint, item
from tests.evals.run_helpers import complete_table
from tests.fixtures import sample_repo

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
SUPPORTED = {"verdict": "supported", "faulty_claim": "", "explanation": "The files agree."}
PARTLY = {
    "verdict": "partly_supported",
    "faulty_claim": "It says the token is signed twice.",
    "explanation": "Only one signing step exists.",
}
UNSUPPORTED = {
    "verdict": "unsupported",
    "faulty_claim": "It says the cookie is stored in a database.",
    "explanation": "Nothing stores it.",
}


@pytest.fixture(autouse=True)
def no_network():
    """Any outbound HTTP request from a check test is an error."""
    with respx.mock(assert_all_mocked=True, assert_all_called=False):
        yield


def hand(n: int, **over):
    fields = {
        "reference_answer": f"Feature {n} hashes the password and sets a cookie.",
        "acceptable_files": (f"app/extra{n}.py",),
    }
    fields.update(over)
    return item("hand", n, **fields)


def read_file(_item, path):
    return f"# text of {path}\ndef f(): ..."


def run(items, model, tmp_path, *, chosen=None, read=read_file, budget=None, **kw):
    chosen = chosen or endpoint()
    path = checks_path(tmp_path, chosen)
    result = asyncio.run(
        check_items(
            items,
            endpoint=chosen,
            out_path=path,
            budget=budget or Budget(cap_usd=10.0, stop_usd=9.0),
            table=complete_table(),
            read_file=read,
            client_factory=model.factory,
            clock=lambda: NOW,
            **kw,
        )
    )
    return result, path


class TestWhatTheCheckerIsShown:
    def test_the_prompt_carries_the_question_reference_and_files(self, tmp_path):
        gold = hand(0)
        model = FakeJudge({"CheckVerdict": SUPPORTED})

        run([gold], model, tmp_path)

        (text,) = model.texts()
        assert gold.question in text
        assert gold.reference_answer in text
        assert "# text of app/hand0.py" in text and "# text of app/extra0.py" in text
        assert text.index("app/hand0.py") < text.index("app/extra0.py")

    def test_the_files_are_read_through_the_given_reader_for_that_item(self, tmp_path):
        seen = []

        def reader(gold, path):
            seen.append((gold.id, path))
            return "x = 1"

        gold = hand(0)
        run([gold], FakeJudge({"CheckVerdict": SUPPORTED}), tmp_path, read=reader)

        assert seen == [(gold.id, "app/hand0.py"), (gold.id, "app/extra0.py")]

    def test_a_file_missing_at_the_base_commit_is_said_so(self):
        text = render_files(hand(0), lambda _i, path: None if "extra" in path else "ok")

        assert "=== app/hand0.py ===\nok" in text
        assert "=== app/extra0.py ===\n" + check_module.MISSING_FILE in text

    def test_file_text_is_capped_at_the_named_budget(self):
        gold = hand(0)
        big = "y" * (FILE_CHAR_BUDGET * 3)

        text = render_files(gold, lambda _i, _p: big)

        assert len(text) < FILE_CHAR_BUDGET + 400
        assert "(truncated)" in text

    def test_a_short_file_leaves_its_share_to_the_next_one(self):
        gold = hand(0)
        files = {"app/hand0.py": "short", "app/extra0.py": "z" * 100}

        text = render_files(gold, lambda _i, path: files[path], budget=1000)

        assert "z" * 100 in text and "truncated" not in text


class TestRecordsAndCaching:
    @pytest.mark.parametrize("reply", [SUPPORTED, PARTLY, UNSUPPORTED])
    def test_each_verdict_is_stored_with_its_claim_and_identity(self, tmp_path, reply):
        gold = hand(0)
        chosen = endpoint(base_url="https://llm.example.com/v1")

        result, path = run([gold], FakeJudge({"CheckVerdict": reply}), tmp_path, chosen=chosen)

        (record,) = read_checks(path)
        assert (result.ok, result.errors) == (1, 0)
        assert record.status == "ok" and record.verdict == reply["verdict"]
        assert record.faulty_claim == reply["faulty_claim"]
        assert record.explanation == reply["explanation"]
        assert record.item_id == gold.id
        assert record.content_hash == item_content_hash(gold)
        assert (record.model, record.host) == ("gpt-6-luna", "llm.example.com")
        assert record.prompt_version == CHECKER_PROMPT_VERSION
        assert record.check_key == check_key(gold, chosen)
        assert "k-test" not in path.read_text(encoding="utf-8")

    def test_the_key_names_the_content_prompt_version_model_and_host(self):
        gold = hand(0)
        base = check_key(gold, endpoint())

        assert check_key(gold, endpoint()) == base
        assert check_key(hand(0, reference_answer="Something else."), endpoint()) != base
        assert check_key(gold, endpoint(model="other-model")) != base
        assert check_key(gold, endpoint(base_url="https://llm.example.com")) != base

    def test_a_prompt_version_bump_changes_the_key(self, monkeypatch):
        gold = hand(0)
        before = check_key(gold, endpoint())

        monkeypatch.setattr(check_module, "CHECKER_PROMPT_VERSION", "2")

        assert check_key(gold, endpoint()) != before

    def test_a_finished_item_is_skipped_and_changed_ones_are_rechecked(self, tmp_path):
        first, second = hand(0), hand(1)
        model = FakeJudge({"CheckVerdict": SUPPORTED})
        run([first], model, tmp_path)

        again = FakeJudge({"CheckVerdict": SUPPORTED})
        result, path = run([first, second], again, tmp_path)

        assert (result.skipped, result.ok) == (1, 1)
        assert again.calls == 1
        edited = hand(0, reference_answer="A different claim.")
        third = FakeJudge({"CheckVerdict": SUPPORTED})
        result, _ = run([edited], third, tmp_path)
        assert (result.skipped, result.ok) == (0, 1)
        assert len(read_checks(path)) == 3

    def test_an_error_is_stored_as_an_error_record_never_a_verdict(self, tmp_path):
        gold = hand(0)

        result, path = run([gold], FakeJudge({"CheckVerdict": "not json at all"}), tmp_path)

        (record,) = read_checks(path)
        assert (result.ok, result.errors) == (0, 1)
        assert record.status == "error" and record.verdict is None and record.error
        assert apply_checks([gold], [record]).unchecked == (gold,)

    def test_a_failed_call_is_an_error_record_and_is_retried_next_run(self, tmp_path):
        gold = hand(0)
        failing = FakeJudge(error=RuntimeError("provider down"))
        result, path = run([gold], failing, tmp_path)
        assert result.errors == 1
        assert "provider down" in read_checks(path)[0].error

        working = FakeJudge({"CheckVerdict": PARTLY})
        result, _ = run([gold], working, tmp_path)

        assert (result.ok, result.skipped, result.errors) == (1, 0, 0)
        records = read_checks(path)
        assert [r.status for r in records] == ["error", "ok"]
        (final,) = final_checks(records)
        assert final.verdict == "partly_supported"

    def test_a_half_written_line_is_ignored(self, tmp_path):
        gold = hand(0)
        _, path = run([gold], FakeJudge({"CheckVerdict": SUPPORTED}), tmp_path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"check_key": "cut')

        assert len(read_checks(path)) == 1

    def test_an_ok_record_needs_a_verdict_and_an_error_record_cannot_have_one(self):
        common = dict(
            check_key="k",
            item_id="i",
            content_hash="h",
            repo="r",
            model="m",
            host="h",
            prompt_version="1",
        )
        with pytest.raises(ValueError):
            CheckRecord(**common)
        with pytest.raises(ValueError):
            CheckRecord(**common, status="error", verdict="supported", error="x")


class TestMeteringAndBudget:
    def test_usage_reaches_the_meter_the_record_and_the_budget(self, tmp_path):
        meter = Meter()
        budget = Budget(cap_usd=10.0, stop_usd=9.0)

        result, path = run(
            [hand(0), hand(1)],
            FakeJudge({"CheckVerdict": SUPPORTED}),
            tmp_path,
            budget=budget,
            meter=meter,
        )

        (first, second) = read_checks(path)
        assert len(meter.usages) == 2
        assert first.cost_usd == pytest.approx(0.0011) and first.usages[0].kind == "judge"
        assert budget.spent_usd == pytest.approx(0.0022)
        assert result.spent_usd == pytest.approx(0.0022)
        assert second.reported_model == "reported-judge-model"

    def test_the_run_stops_cleanly_at_the_stop_threshold(self, tmp_path):
        budget = Budget(cap_usd=1.0, stop_usd=0.0015)

        result, path = run(
            [hand(n) for n in range(5)],
            FakeJudge({"CheckVerdict": SUPPORTED}),
            tmp_path,
            budget=budget,
        )

        assert result.stopped and "reached the stop" in result.stopped
        assert 0 < len(read_checks(path)) < 5

    def test_a_model_with_no_price_stops_the_run(self, tmp_path):
        result, _ = run(
            [hand(n) for n in range(3)],
            FakeJudge({"CheckVerdict": SUPPORTED}),
            tmp_path,
            chosen=endpoint(model="unpriced-model"),
        )

        assert result.stopped and "no price" in result.stopped


class TestApplyChecks:
    def _record(self, gold, verdict, key="k", **over):
        return CheckRecord(
            check_key=key,
            item_id=gold.id,
            content_hash=item_content_hash(gold),
            repo=gold.repo,
            verdict=verdict,
            faulty_claim="the claim" if verdict != "supported" else "",
            model="m",
            host="h",
            prompt_version="1",
            **over,
        )

    def test_unsupported_items_are_dropped_and_partly_supported_ones_reported(self):
        ok, partly, bad, new = hand(0), hand(1), hand(2), hand(3)
        records = [
            self._record(ok, "supported", "a"),
            self._record(partly, "partly_supported", "b"),
            self._record(bad, "unsupported", "c"),
        ]

        outcome = apply_checks([ok, partly, bad, new], records)

        assert outcome.kept == (ok, partly, new)
        assert outcome.unsupported == (bad,)
        assert [i for i, _ in outcome.partly_supported] == [partly]
        assert outcome.partly_supported[0][1].faulty_claim == "the claim"
        assert outcome.unchecked == (new,)

    def test_a_verdict_does_not_follow_an_edited_item(self):
        gold = hand(0)
        records = [self._record(gold, "unsupported")]

        outcome = apply_checks([hand(0, reference_answer="Fixed now.")], records)

        assert outcome.unsupported == () and len(outcome.unchecked) == 1

    def test_the_most_severe_verdict_across_checkers_counts(self):
        gold = hand(0)
        records = [self._record(gold, "supported", "a"), self._record(gold, "unsupported", "b")]

        assert apply_checks([gold], records).unsupported == (gold,)

    def test_an_error_record_never_decides(self):
        gold = hand(0)
        error = CheckRecord(
            check_key="k",
            item_id=gold.id,
            content_hash=item_content_hash(gold),
            repo="r",
            status="error",
            error="boom",
            model="m",
            host="h",
            prompt_version="1",
        )

        assert apply_checks([gold], [error]).unchecked == (gold,)


class TestCommand:
    BASE_FILE = "src/app.py"

    @pytest.fixture
    def setup(self, tmp_path):
        """A clone whose base commit holds one file and whose later commit changes it."""
        clones = tmp_path / "clones"
        clone = clones / "octo__demo"
        clone.mkdir(parents=True)
        sample_repo._git(clone, "init", "-q", "-b", "main")
        (clone / "src").mkdir()
        (clone / self.BASE_FILE).write_text("BASE_TEXT = 1\n", encoding="utf-8")
        sample_repo.commit_all(clone, "base")
        base = sample_repo.head_sha(clone)
        (clone / self.BASE_FILE).write_text("LATER_TEXT = 2\n", encoding="utf-8")
        sample_repo.commit_all(clone, "later")
        corpus = tmp_path / "corpus.yaml"
        corpus.write_text(
            "repos:\n  - name: demo\n    url: https://github.com/octo/demo\n"
            f'    language: Python\n    licence: MIT\n    base_commit: "{base}"\n',
            encoding="utf-8",
        )
        hand_file = tmp_path / "demo.yaml"
        hand_file.write_text(
            "items:\n"
            "  - kind: explain\n    question: How does the app start?\n"
            "    reference_answer: It sets a constant.\n"
            f"    required_files: [{self.BASE_FILE}]\n"
            "  - kind: flow\n    question: Old style question?\n"
            f"    required_files: [{self.BASE_FILE}]\n"
            "  - kind: unanswerable\n    question: Does it ship?\n",
            encoding="utf-8",
        )
        return tmp_path, clones, corpus, hand_file

    def _run(self, setup, model, lines, **kw):
        out, clones, corpus, hand_file = setup
        return cmd_gold_check(
            out_dir=out,
            clones_dir=clones,
            repo_name="demo",
            endpoint=kw.pop("endpoint", endpoint()),
            budget_usd=10.0,
            stop_usd=9.0,
            corpus_path=corpus,
            hand_file=hand_file,
            table=complete_table(),
            client_factory=model.factory,
            clock=lambda: NOW,
            print_fn=lines.append,
            **kw,
        )

    def test_it_reads_the_files_at_the_base_commit_and_checks_only_items_with_a_reference(
        self, setup
    ):
        model = FakeJudge({"CheckVerdict": SUPPORTED})
        lines: list[str] = []

        status = self._run(setup, model, lines)

        assert status == 0
        (text,) = model.texts()
        assert "BASE_TEXT = 1" in text and "LATER_TEXT" not in text
        assert any(line.startswith("supported 1") for line in lines)
        records = read_checks(checks_path(setup[0] / "gold" / "demo", endpoint()))
        assert len(records) == 1

    def test_a_second_run_costs_nothing_and_a_partly_supported_item_is_listed(self, setup):
        lines: list[str] = []
        self._run(setup, FakeJudge({"CheckVerdict": PARTLY}), lines)
        again = FakeJudge({"CheckVerdict": PARTLY})
        lines.clear()

        status = self._run(setup, again, lines)

        assert status == 0 and again.calls == 0
        assert any("1 already done" in line for line in lines)
        assert any("partly supported, fix" in line and "signed twice" in line for line in lines)

    def test_an_unsupported_item_is_reported_and_an_error_gives_a_failing_status(self, setup):
        lines: list[str] = []
        status = self._run(setup, FakeJudge({"CheckVerdict": UNSUPPORTED}), lines)
        assert status == 0
        assert any(line.startswith("unsupported, dropped") for line in lines)

        failing = self._run(
            setup,
            FakeJudge(error=RuntimeError("down")),
            lines,
            endpoint=endpoint(model="test-model"),
        )
        assert failing == 1

    def test_it_needs_a_key_and_a_clone(self, setup, tmp_path, capsys):
        model = FakeJudge({"CheckVerdict": SUPPORTED})

        assert self._run(setup, model, [], endpoint=endpoint(api_key="")) == 1
        assert "OPENAI_API_KEY" in capsys.readouterr().err
        out, _, corpus, hand_file = setup
        status = cmd_gold_check(
            out_dir=out,
            clones_dir=tmp_path / "nowhere",
            repo_name="demo",
            endpoint=endpoint(),
            budget_usd=10.0,
            stop_usd=9.0,
            corpus_path=corpus,
            hand_file=hand_file,
        )
        assert status == 1 and "mine" in capsys.readouterr().err
        assert model.calls == 0


def test_the_records_are_plain_json_lines(tmp_path):
    _, path = run([hand(0)], FakeJudge({"CheckVerdict": SUPPORTED}), tmp_path)

    (line,) = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["verdict"] == "supported"
