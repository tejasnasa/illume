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

    commands.add_parser("mine", help="mine questions from pull requests")

    gold = commands.add_parser("gold", help="build and verify the gold set")
    gold.add_argument("action", choices=["build", "phrase", "verify", "split"])

    run = commands.add_parser("run", help="generate answers or judge them")
    run.add_argument("action", choices=["generate", "judge"])

    commands.add_parser("report", help="render a report from run outputs")
    commands.add_parser("selftest", help="run the metric self-tests")
    commands.add_parser("budget", help="show spend against the budget")
    return parser


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


def _generator_key() -> str:
    """Return the generator API key, or an empty string when it is not configured."""
    try:
        return eval_settings.require_key("AI_API_KEY")
    except eval_settings.EvalIsolationError:
        return ""


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
    action = getattr(args, "action", None)
    return cmd_not_built(f"{args.command} {action}" if action else args.command)


if __name__ == "__main__":
    sys.exit(main())
