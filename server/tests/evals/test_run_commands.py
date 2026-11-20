"""``run generate`` and ``budget`` on the command line, without a real provider."""

import subprocess
from contextlib import asynccontextmanager

import pytest

from evals.arms import STARTER_ARMS
from evals.cli.run_commands import (
    RunSetupError,
    cmd_budget,
    cmd_run_generate,
    keys_needed,
    models_needed,
    parse_subsets,
    resolve_arms,
    run_dir_for,
)
from evals.gold.schema import write_jsonl
from evals.run.generate import GENERATIONS, read_generations
from tests.evals.run_helpers import (
    EMBEDDING,
    GENERATOR,
    ScriptedExecutor,
    complete_table,
    flat_table,
    make_items,
)

pytestmark = pytest.mark.unit


class RecordingRuntime:
    """A runtime that hands out a scripted executor and notes whether it was ever opened."""

    def __init__(self):
        self.opened = False
        self.executor = ScriptedExecutor()

    def __call__(self, items):
        @asynccontextmanager
        async def opened():
            self.opened = True

            async def router(item):
                raise AssertionError("no auto arm was asked for")

            yield self.executor, router

        return opened()


@pytest.fixture
def out_dir(tmp_path):
    items = make_items(3)
    for name in ("tuning", "pilot", "test"):
        write_jsonl(tmp_path / "out" / "gold" / f"{name}.jsonl", items)
    return tmp_path / "out"


def generate(out_dir, **kwargs):
    fields = {
        "out_dir": out_dir,
        "slice_name": "tuning",
        "arms_spec": "classic,hybrid",
        "run_name": "r1",
        "budget_usd": 10.0,
        "stop_usd": 9.5,
        "table": flat_table(),
        "runtime": RecordingRuntime(),
        "concurrency": 1,
        "min_intervals": {},
    }
    fields.update(kwargs)
    return cmd_run_generate(**fields)


class TestArguments:
    def test_starter_stands_for_the_starter_arms(self):
        assert resolve_arms("starter") == list(STARTER_ARMS)
        assert resolve_arms("classic, hybrid") == ["classic", "hybrid"]

    def test_an_unknown_arm_is_named_with_the_arms_that_exist(self):
        with pytest.raises(RunSetupError, match="nonesuch.*classic"):
            resolve_arms("classic,nonesuch")

    def test_subsets_are_arm_equals_n(self):
        assert parse_subsets(["hybrid=5", "agent=10"]) == {"hybrid": 5, "agent": 10}
        for bad in ("hybrid", "hybrid=x", "nonesuch=3"):
            with pytest.raises(RunSetupError):
                parse_subsets([bad])

    def test_the_models_and_keys_a_run_needs_follow_its_arms(self):
        assert models_needed(["classic", "auto"]) == [GENERATOR, EMBEDDING]
        assert keys_needed(["classic", "hybrid"]) == ["AI_API_KEY", "OPENAI_API_KEY"]
        assert "OPENROUTER_API_KEY" in keys_needed(["classic", "hybrid_rerank"])
        assert "OPENROUTER_API_KEY" in keys_needed(["classic", "auto"])
        assert "OPENROUTER_API_KEY" in keys_needed(["agent"])


class TestRefusals:
    def test_a_bad_arm_or_subset_is_a_usage_error(self, out_dir, capsys):
        assert generate(out_dir, arms_spec="nonesuch") == 2
        assert generate(out_dir, subsets=["classic"]) == 2
        assert generate(out_dir, repeats=0) == 2

    def test_a_missing_slice_says_to_split_first(self, tmp_path, capsys):
        assert generate(tmp_path / "empty") == 1
        assert "gold split" in capsys.readouterr().err

    @pytest.mark.parametrize("slice_name", ["test", "pilot"])
    def test_a_frozen_slice_is_refused_without_a_frozen_preregistration(
        self, out_dir, tmp_path, capsys, slice_name
    ):
        runtime = RecordingRuntime()

        status = generate(
            out_dir,
            slice_name=slice_name,
            runtime=runtime,
            prereg_dir=tmp_path / "prereg",
            repo_root=tmp_path,
        )

        assert status == 1 and not runtime.opened
        assert "frozen" in capsys.readouterr().err
        assert not (out_dir / "runs").exists()

    def test_a_frozen_preregistration_lets_the_pilot_run(self, out_dir, tmp_path):
        repo = tmp_path / "repo"
        (repo / "prereg").mkdir(parents=True)
        (repo / "prereg" / "pilot.md").write_text("pilot plan\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "prereg/pilot.md"]):
            subprocess.run(["git", *args], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x"],
            cwd=repo,
            check=True,
        )
        runtime = RecordingRuntime()

        status = generate(
            out_dir, slice_name="pilot", runtime=runtime, prereg_dir=repo / "prereg", repo_root=repo
        )

        assert status == 0 and runtime.opened

    def test_the_tuning_slice_needs_no_preregistration(self, out_dir, tmp_path):
        runtime = RecordingRuntime()

        status = generate(
            out_dir, runtime=runtime, prereg_dir=tmp_path / "none", repo_root=tmp_path
        )

        assert status == 0 and runtime.opened

    def test_an_unverified_price_table_refuses_a_paid_run_before_anything_is_opened(
        self, out_dir, capsys
    ):
        runtime = RecordingRuntime()

        status = generate(out_dir, table=complete_table(verified=False), runtime=runtime)

        assert status == 1 and not runtime.opened
        assert "price table is incomplete" in capsys.readouterr().err

    def test_a_missing_key_fails_clearly_before_the_database_is_touched(self, out_dir, capsys):
        def require_key(name):
            raise RuntimeError(f"{name} is not set in server/evals/.env.eval")

        status = generate(
            out_dir,
            runtime=None,
            require_key=require_key,
            clones_dir=out_dir / "clones",
            async_url="postgresql+asyncpg://invalid.example/none",
        )

        assert status == 1
        assert "AI_API_KEY is not set" in capsys.readouterr().err
        assert not (out_dir / "runs").exists()


class TestGenerate:
    def test_it_writes_the_run_directory_and_reports_the_spend(self, out_dir, capsys):
        status = generate(out_dir)

        run_dir = run_dir_for(out_dir, "r1")
        assert status == 0
        assert len(read_generations(run_dir / GENERATIONS)) == 6
        for name in ("manifest.json", "run_summary.json"):
            assert (run_dir / name).exists()
        assert "6 ok, 0 errors, 0 already done; spent $0.6000 of $10.00" in capsys.readouterr().out

    def test_running_it_again_resumes_and_a_stop_is_reported(self, out_dir, capsys):
        generate(out_dir, budget_usd=1.0, stop_usd=0.25)
        assert "stopped:" in capsys.readouterr().out

        runtime = RecordingRuntime()
        generate(out_dir, runtime=runtime, budget_usd=10.0, stop_usd=9.5)

        assert len(runtime.executor.calls) == 3  # three pairs were done before the stop
        assert len(read_generations(run_dir_for(out_dir, "r1") / GENERATIONS)) == 6

    def test_a_pair_that_ends_as_an_error_makes_the_exit_status_nonzero(self, out_dir, capsys):
        items = make_items(3)
        runtime = RecordingRuntime()
        runtime.executor = ScriptedExecutor(fail={(items[0].id, "classic"): 99})

        status = generate(out_dir, runtime=runtime)

        assert status == 1 and "retries them" in capsys.readouterr().out


class TestBudgetCommand:
    @pytest.fixture
    def measured(self, out_dir):
        generate(out_dir)
        return out_dir

    def test_spend_is_shown_against_the_budget(self, measured):
        lines = []

        status = cmd_budget(
            out_dir=measured, budget_usd=10.0, stop_usd=9.5, run_name="r1", print_fn=lines.append
        )

        assert status == 0
        assert lines[0] == "spent $0.6000 of $10.00 (stop at $9.50)"
        assert any("classic" in line and "3 records" in line for line in lines)

    def test_every_run_is_read_when_none_is_named(self, measured):
        lines = []

        cmd_budget(out_dir=measured, budget_usd=10.0, stop_usd=9.5, print_fn=lines.append)

        assert lines[0].startswith("spent $0.6000")

    def test_projection_scales_the_measured_cost_to_a_planned_run(self, measured):
        lines = []

        status = cmd_budget(
            out_dir=measured,
            budget_usd=10.0,
            stop_usd=9.5,
            run_name="r1",
            project_run=True,
            items=100,
            arms_spec="classic,hybrid,agent",
            print_fn=lines.append,
        )

        assert status == 0
        assert any(line.startswith("projected $20.00") for line in lines)
        assert any("no measurements for: agent" in line for line in lines)

    def test_projection_needs_the_item_count(self, measured, capsys):
        status = cmd_budget(
            out_dir=measured, budget_usd=10.0, stop_usd=9.5, project_run=True, print_fn=lambda _: 0
        )

        assert status == 2 and "--items" in capsys.readouterr().err

    def test_no_records_is_reported(self, tmp_path, capsys):
        assert cmd_budget(out_dir=tmp_path, budget_usd=10.0, stop_usd=9.5) == 1
        assert "no records" in capsys.readouterr().err
