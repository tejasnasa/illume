"""``mine``: clone a corpus repository and build its GitHub cache."""

import sys
from pathlib import Path

import httpx

from evals.corpus.corpus import CORPUS_PATH, CorpusError, load_corpus
from evals.mining.clones import ensure_clone
from evals.mining.github_fetch import GitHubError, build_cache, make_client


def cmd_mine(
    *,
    out_dir: Path,
    clones_dir: Path,
    token: str,
    repo_name: str,
    corpus_path: Path = CORPUS_PATH,
    refresh: bool = False,
    client: httpx.Client | None = None,
) -> int:
    """Clone one corpus repository and fetch its pull requests into the cache.

    Args:
        out_dir: The eval output directory; the GitHub cache is ``<out_dir>/github``.
        clones_dir: Where harness clones live.
        token: The GitHub token.
        repo_name: The corpus entry to mine.
        corpus_path: The corpus file.
        refresh: Fetch again even when the cache is current.
        client: Replaces the HTTP client; tests pass a mocked one.

    Returns:
        The process exit status.
    """
    try:
        corpus_repo = load_corpus(corpus_path).get(repo_name)
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    owner, _, repo = corpus_repo.slug.partition("/")
    own_client = client is None
    http = client or make_client(token)
    try:
        clone = ensure_clone(corpus_repo.url, clones_dir, slug=corpus_repo.slug)
        summary = build_cache(
            http,
            owner=owner,
            repo=repo,
            cache_dir=Path(out_dir) / "github",
            clone=clone,
            base_commit=corpus_repo.base_commit,
            history_prs=corpus_repo.history_prs,
            refresh=refresh,
        )
    except (GitHubError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if own_client:
            http.close()

    source = "from cache" if summary.from_cache else "fetched"
    print(f"{corpus_repo.name} at {summary.base_commit[:12]} ({source}, {summary.fetched_at})")
    print(f"pull requests before base: {len(summary.pre_base)}")
    print(f"pull requests after base:  {len(summary.post_base)}")
    print(f"skipped (not on default branch): {len(summary.skipped)}")
    return 0
