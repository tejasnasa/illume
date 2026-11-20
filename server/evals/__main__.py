"""Command line entry point: ``python -m evals <command>``."""

# This import must stay first. It points the process environment at the isolated eval
# stack before anything under ``app`` can read its settings.
import evals.settings as eval_settings  # isort: skip  # noqa: I001

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from evals import selftest_registry
from evals.envcheck import assert_eval_url, mask_url

SERVER_ROOT = Path(__file__).resolve().parents[1]

NOT_BUILT_EXIT = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser with every subcommand registered.
    """
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    db = commands.add_parser("db", help="eval database migrations and status")
    db.add_argument("action", choices=["migrate", "status"])

    corpus = commands.add_parser("corpus", help="pinned corpus ingestion and snapshots")
    corpus.add_argument("action", choices=["ingest", "snapshot", "restore", "report"])
    corpus.add_argument("--repo", help="corpus entry to ingest")
    corpus.add_argument("--corpus", type=Path, help="corpus file (default: the shipped one)")
    corpus.add_argument("--name", help="snapshot name")

    mine = commands.add_parser("mine", help="clone a corpus repository and cache its pull requests")
    mine.add_argument("--repo", help="corpus entry to mine")
    mine.add_argument("--corpus", type=Path, help="corpus file (default: the shipped one)")
    mine.add_argument("--refresh", action="store_true", help="fetch again even if cached")

    gold = commands.add_parser("gold", help="build and verify the gold set")
    gold.add_argument("action", choices=["build", "phrase", "check", "verify", "split"])
    gold.add_argument("--repo", help="corpus entry to build gold items for")
    gold.add_argument("--corpus", type=Path, help="corpus file (default: the shipped one)")
    gold.add_argument("--seed", type=int, default=0, help="sampling seed (default 0)")
    gold.add_argument("--annotator", help="verify: use labels.<annotator>.jsonl")
    gold.add_argument(
        "--report", action="store_true", help="verify: print the error report, write verified items"
    )
    gold.add_argument("--all", action="store_true", help="split: use every repository")
    gold.add_argument(
        "--pilot",
        action="store_true",
        help="split: one pilot slice with no test split (the default; kept for older scripts)",
    )
    gold.add_argument(
        "--tuning-test-split",
        action="store_true",
        help="split: make the tuning/test split, which generation then guards with a "
        "pre-registration, instead of the single pilot slice",
    )
    gold.add_argument(
        "--include-anchor",
        action="store_true",
        help="build: also build the change questions that name a starting file",
    )
    gold.add_argument(
        "--include-rationale", action="store_true", help='build: also build the "why" questions'
    )
    gold.add_argument(
        "--include-structural",
        action="store_true",
        help="build: also build the import-graph questions",
    )
    gold.add_argument(
        "--include-unanswerable",
        action="store_true",
        help="build: keep the hand items marked unanswerable",
    )
    gold.add_argument(
        "--checker-model", help="check: the checking model (default: the judge model)"
    )
    gold.add_argument("--checker-base-url", help="check: the checker's OpenAI-compatible base URL")
    gold.add_argument(
        "--checker-api-style", choices=["responses", "chat"], help="check: the transport"
    )
    gold.add_argument("--concurrency", type=int, default=4, help="check: items at once")
    _add_budget_arguments(gold)

    run = commands.add_parser("run", help="generate answers or judge them")
    run.add_argument("action", choices=["generate", "judge", "judge-label", "judge-agreement"])
    run.add_argument(
        "--slice",
        choices=["pilot", "tuning", "test"],
        default="pilot",
        help="generate: the slice to run (default pilot)",
    )
    run.add_argument("--arms", default="starter", help="generate: 'starter' or a,b,c")
    run.add_argument("--run", dest="run_name", help="the run's name; an existing run resumes")
    run.add_argument(
        "--subset",
        action="append",
        default=[],
        metavar="ARM=N",
        help="generate: restrict an arm to N items (repeatable)",
    )
    run.add_argument("--repeats", type=int, default=1, help="generate: runs per agent item")
    run.add_argument(
        "--repeats-subset", type=int, default=0, help="generate: items the repeats cover"
    )
    run.add_argument(
        "--off-peak-only", action="store_true", help="generate: wait for the off-peak window"
    )
    run.add_argument("--seed", type=int, default=0, help="generate: shuffle and subset seed")
    run.add_argument("--concurrency", type=int, default=4, help="generate: pairs at once")
    _add_budget_arguments(run)
    run.add_argument("--judge-model", help="judge: the judge model (default JUDGE_MODEL or Luna)")
    run.add_argument("--judge-base-url", help="judge: the judge's OpenAI-compatible base URL")
    run.add_argument(
        "--judge-api-style", choices=["responses", "chat"], help="judge: the transport"
    )
    run.add_argument("--compare-judge-model", help="judge-agreement: a second judge's model")
    run.add_argument("--compare-judge-base-url", help="judge-agreement: a second judge's base URL")
    run.add_argument(
        "--sample-only", action="store_true", help="judge: draw the labelling sample, no calls"
    )
    run.add_argument("--sample-size", type=int, default=30, help="judge: answers to label")
    run.add_argument(
        "--include-unanswerable",
        action="store_true",
        help="judge: also grade the items marked unanswerable",
    )
    run.add_argument("--annotator", help="judge-label, judge-agreement: whose labels")

    report = commands.add_parser("report", help="build a report from a run directory")
    report.add_argument("--run", dest="run_name", required=True, help="the run to report on")
    report.add_argument(
        "--mode",
        choices=["simple", "full", "pilot"],
        default="simple",
        help="simple: the default tables and comparisons; full: the pre-registered analysis; "
        "pilot: the older pilot report",
    )
    report.add_argument("--out", type=Path, help="output directory (default: by mode)")
    report.add_argument("--judge-slug", help="read this judge's judgments instead of the default")
    commands.add_parser("selftest", help="run the metric self-tests")
    budget = commands.add_parser("budget", help="show spend against the budget")
    budget.add_argument("--run", dest="run_name", help="the run to read (default: every run)")
    budget.add_argument(
        "--project", action="store_true", help="project a planned run from measured cost"
    )
    budget.add_argument("--items", type=int, help="project: items in the planned run")
    budget.add_argument("--arms", default="starter", help="project: 'starter' or a,b,c")
    budget.add_argument("--repeats", type=int, default=1, help="project: runs per agent item")
    budget.add_argument(
        "--repeats-subset", type=int, default=0, help="project: items the repeats cover"
    )
    _add_budget_arguments(budget)
    return parser


def _add_budget_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the spending cap and stop threshold, defaulting to the starter run's."""
    parser.add_argument(
        "--budget",
        type=float,
        default=eval_settings.STARTER_BUDGET_USD,
        help="the spending cap in US dollars",
    )
    parser.add_argument(
        "--stop",
        type=float,
        default=eval_settings.STARTER_STOP_USD,
        help="the spend at which the run stops cleanly",
    )


def _alembic_config():
    """Build an Alembic config bound to the eval database.

    Returns:
        A config whose ``sqlalchemy.url`` is the eval sync URL.
    """
    from alembic.config import Config

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", eval_settings.SYNC_DATABASE_URL)
    return config


def cmd_db_migrate() -> int:
    """Apply every migration to the eval database.

    Returns:
        The process exit status.
    """
    from alembic import command

    assert_eval_url(eval_settings.SYNC_DATABASE_URL, kind="database")
    command.upgrade(_alembic_config(), "head")
    return 0


def cmd_db_status() -> int:
    """Print the eval database's current revision against head.

    Returns:
        The process exit status: 0 when at head, 1 otherwise.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    assert_eval_url(eval_settings.SYNC_DATABASE_URL, kind="database")
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    engine = create_engine(eval_settings.SYNC_DATABASE_URL)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    print(f"current: {current}")
    print(f"head:    {head}")
    return 0 if current == head else 1


def cmd_selftest() -> int:
    """Run the registered self-test cases.

    Returns:
        0 when every case passes (or there are none), 1 otherwise.
    """
    import evals.metrics.selftest  # noqa: F401  # registers the metric cases
    import evals.stats_selftest  # noqa: F401  # registers the statistics cases

    passed, failed = selftest_registry.run_all()
    total = len(passed) + len(failed)
    if total == 0:
        print("0 cases")
        return 0
    for name, message in failed:
        print(f"FAIL {name}: {message}")
    print(f"{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


def cmd_corpus(args: argparse.Namespace) -> int:
    """Dispatch a ``corpus`` subcommand against the eval database.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.
    """
    from evals.cli import corpus_commands
    from evals.corpus.corpus import CORPUS_PATH

    assert_eval_url(eval_settings.SYNC_DATABASE_URL, kind="database")
    url = eval_settings.SYNC_DATABASE_URL
    if args.action == "ingest":
        if not args.repo:
            print("corpus ingest needs --repo NAME", file=sys.stderr)
            return 2
        return corpus_commands.cmd_ingest(
            sync_url=url,
            out_dir=eval_settings.OUT_DIR,
            api_key=_generator_key(),
            repo_name=args.repo,
            corpus_path=args.corpus or CORPUS_PATH,
        )
    if args.action == "report":
        return corpus_commands.cmd_report(sync_url=url)
    if not args.name:
        print(f"corpus {args.action} needs --name N", file=sys.stderr)
        return 2
    run = corpus_commands.cmd_snapshot if args.action == "snapshot" else corpus_commands.cmd_restore
    return run(sync_url=url, out_dir=eval_settings.OUT_DIR, name=args.name)


def cmd_mine(args: argparse.Namespace) -> int:
    """Run ``mine`` for one corpus repository.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.
    """
    from evals.cli import mine_commands
    from evals.corpus.corpus import CORPUS_PATH

    if not args.repo:
        print("mine needs --repo NAME", file=sys.stderr)
        return 2
    try:
        token = eval_settings.require_github_token()
    except eval_settings.EvalIsolationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return mine_commands.cmd_mine(
        out_dir=eval_settings.OUT_DIR,
        clones_dir=eval_settings.CLONES_DIR,
        token=token,
        repo_name=args.repo,
        corpus_path=args.corpus or CORPUS_PATH,
        refresh=args.refresh,
    )


def cmd_gold(args: argparse.Namespace) -> int:
    """Run a ``gold`` subcommand against the eval database.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.
    """
    from evals.cli import gold_commands
    from evals.corpus.corpus import CORPUS_PATH

    corpus_path = args.corpus or CORPUS_PATH
    if args.action == "split":
        return gold_commands.cmd_gold_split(
            out_dir=eval_settings.OUT_DIR,
            repo_name=args.repo,
            all_repos=args.all,
            pilot=not args.tuning_test_split,
            seed=args.seed,
        )
    if not args.repo:
        print(f"gold {args.action} needs --repo NAME", file=sys.stderr)
        return 2
    if args.action == "check":
        return cmd_gold_check(args, corpus_path)
    if args.action == "phrase":
        try:
            key = eval_settings.require_key("OPENAI_API_KEY")
        except eval_settings.EvalIsolationError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return gold_commands.cmd_gold_phrase(
            out_dir=eval_settings.OUT_DIR,
            clones_dir=eval_settings.CLONES_DIR,
            api_key=key,
            repo_name=args.repo,
            corpus_path=corpus_path,
        )
    if args.action == "verify":
        return gold_commands.cmd_gold_verify(
            out_dir=eval_settings.OUT_DIR,
            repo_name=args.repo,
            annotator=args.annotator,
            report=args.report,
            corpus_path=corpus_path,
            seed=args.seed,
        )
    assert_eval_url(eval_settings.DATABASE_URL, kind="database")
    return gold_commands.cmd_gold_build(
        async_url=eval_settings.DATABASE_URL,
        out_dir=eval_settings.OUT_DIR,
        clones_dir=eval_settings.CLONES_DIR,
        repo_name=args.repo,
        corpus_path=corpus_path,
        seed=args.seed,
        include_anchor=args.include_anchor,
        include_rationale=args.include_rationale,
        include_structural=args.include_structural,
        include_unanswerable=args.include_unanswerable,
    )


def cmd_gold_check(args: argparse.Namespace, corpus_path: Path) -> int:
    """Run ``gold check``: an independent model checks the hand reference answers.

    The checker defaults to the judge's model, base URL, API style and key; the ``--checker-*``
    options override each in turn.

    Args:
        args: The parsed arguments.
        corpus_path: The corpus file.

    Returns:
        The process exit status.
    """
    from evals.cli import gold_commands
    from evals.run.endpoint import JudgeConfigError

    try:
        endpoint = eval_settings.judge_endpoint(
            model=args.checker_model,
            base_url=args.checker_base_url,
            api_style=args.checker_api_style,
        )
    except JudgeConfigError as failure:
        print(str(failure), file=sys.stderr)
        return 2
    return gold_commands.cmd_gold_check(
        out_dir=eval_settings.OUT_DIR,
        clones_dir=eval_settings.CLONES_DIR,
        repo_name=args.repo,
        endpoint=endpoint,
        budget_usd=args.budget,
        stop_usd=args.stop,
        corpus_path=corpus_path,
        concurrency=args.concurrency,
    )


def _generator_key() -> str:
    """Return the generator API key, or an empty string when it is not configured."""
    try:
        return eval_settings.require_key("AI_API_KEY")
    except eval_settings.EvalIsolationError:
        return ""


def cmd_run(args: argparse.Namespace) -> int:
    """Run ``run generate`` or one of the judge commands.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.
    """
    if args.action != "generate":
        return cmd_judge(args)
    if not args.slice or not args.run_name:
        print("run generate needs --slice and --run", file=sys.stderr)
        return 2
    from evals.cli import run_commands

    assert_eval_url(eval_settings.DATABASE_URL, kind="database")
    return run_commands.cmd_run_generate(
        out_dir=eval_settings.OUT_DIR,
        slice_name=args.slice,
        arms_spec=args.arms,
        run_name=args.run_name,
        budget_usd=args.budget,
        stop_usd=args.stop,
        clones_dir=eval_settings.CLONES_DIR,
        async_url=eval_settings.DATABASE_URL,
        require_key=eval_settings.require_key,
        subsets=args.subset,
        repeats=args.repeats,
        repeats_subset=args.repeats_subset,
        off_peak_only=args.off_peak_only,
        seed=args.seed,
        concurrency=args.concurrency,
        sync_url=eval_settings.SYNC_DATABASE_URL,
    )


def cmd_report(args: argparse.Namespace) -> int:
    """Run ``report``: build ``report.md``, ``report.json`` and figures from a run directory.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.
    """
    from evals.cli.run_commands import run_dir_for
    from evals.report import ReportError, build_report
    from evals.report.load import RunNotFound

    run_dir = run_dir_for(eval_settings.OUT_DIR, args.run_name)
    default = "pilot_v1" if args.mode == "pilot" else f"report_{args.run_name}"
    if args.mode == "full":
        default = f"report_{args.run_name}_full"
    out = args.out or eval_settings.OUT_DIR / default
    try:
        report = build_report(
            run_dir,
            mode=args.mode,
            out_dir=out,
            out_root=eval_settings.OUT_DIR,
            judge_slug=args.judge_slug,
        )
    except (ReportError, RunNotFound, FileNotFoundError) as failure:
        print(str(failure), file=sys.stderr)
        return 1
    print(f"report written to {report.out_dir}")
    print("sections: " + ", ".join(report.data["sections"]))
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    """Run ``run judge``, ``run judge-label`` or ``run judge-agreement``.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.
    """
    from evals.cli import judge_commands
    from evals.run.endpoint import JudgeConfigError, JudgeEndpoint

    if not args.run_name:
        print(f"run {args.action} needs --run", file=sys.stderr)
        return 2
    try:
        endpoint = eval_settings.judge_endpoint(
            model=args.judge_model, base_url=args.judge_base_url, api_style=args.judge_api_style
        )
        compare = (
            JudgeEndpoint(
                model=args.compare_judge_model or endpoint.model,
                base_url=args.compare_judge_base_url,
            )
            if args.compare_judge_model or args.compare_judge_base_url
            else None
        )
    except JudgeConfigError as failure:
        print(str(failure), file=sys.stderr)
        return 2
    if args.action == "judge-label":
        return judge_commands.cmd_judge_label(
            out_dir=eval_settings.OUT_DIR, run_name=args.run_name, annotator=args.annotator
        )
    if args.action == "judge-agreement":
        return judge_commands.cmd_judge_agreement(
            out_dir=eval_settings.OUT_DIR,
            run_name=args.run_name,
            endpoint=endpoint,
            compare=compare,
            annotator=args.annotator,
        )
    return judge_commands.cmd_run_judge(
        out_dir=eval_settings.OUT_DIR,
        run_name=args.run_name,
        endpoint=endpoint,
        budget_usd=args.budget,
        stop_usd=args.stop,
        sample_only=args.sample_only,
        seed=args.seed,
        sample_size=args.sample_size,
        include_unanswerable=args.include_unanswerable,
        concurrency=args.concurrency,
        clones_dir=eval_settings.CLONES_DIR,
    )


def cmd_budget(args: argparse.Namespace) -> int:
    """Run ``budget``: spend against the cap, or a projection from measured cost.

    Args:
        args: The parsed arguments.

    Returns:
        The process exit status.
    """
    from evals.cli import run_commands

    return run_commands.cmd_budget(
        out_dir=eval_settings.OUT_DIR,
        budget_usd=args.budget,
        stop_usd=args.stop,
        run_name=args.run_name,
        project_run=args.project,
        items=args.items,
        arms_spec=args.arms,
        repeats=args.repeats,
        repeats_subset=args.repeats_subset,
    )


def cmd_not_built(label: str) -> int:
    """Report a command whose implementation has not landed yet.

    Args:
        label: The command as typed.

    Returns:
        ``NOT_BUILT_EXIT``.
    """
    print(f"{label}: not built yet", file=sys.stderr)
    return NOT_BUILT_EXIT


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments to parse; ``sys.argv[1:]`` when omitted.

    Returns:
        The process exit status.
    """
    args = build_parser().parse_args(argv)
    print(f"target database: {mask_url(eval_settings.SYNC_DATABASE_URL)}")

    if args.command == "db":
        return cmd_db_migrate() if args.action == "migrate" else cmd_db_status()
    if args.command == "selftest":
        return cmd_selftest()
    if args.command == "corpus":
        return cmd_corpus(args)
    if args.command == "mine":
        return cmd_mine(args)
    if args.command == "gold":
        return cmd_gold(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "budget":
        return cmd_budget(args)
    if args.command == "report":
        return cmd_report(args)
    action = getattr(args, "action", None)
    return cmd_not_built(f"{args.command} {action}" if action else args.command)


if __name__ == "__main__":
    sys.exit(main())
