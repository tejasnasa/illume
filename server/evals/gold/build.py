"""Build one repository's gold items and write them with a build log."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Repository
from evals.corpus.corpus import CorpusRepo
from evals.gold.changeset import build_changeset_items
from evals.gold.check import all_checks, apply_checks
from evals.gold.hand import hand_path, load_hand_items
from evals.gold.mix import Selection, select_change_items, select_explain_items
from evals.gold.rationale import build_rationale_items
from evals.gold.schema import GoldItem, canonical_json, write_jsonl
from evals.gold.structural import build_structural_items
from evals.mining.clones import clone_dir, default_tip, files_at, rev_exists
from evals.mining.github_cache import load_prs
from evals.mining.github_fetch import load_index

# Per-repository targets of the families that are off by default; the change and explain counts
# come from each corpus entry's question mix.
TARGETS = {"rationale": 30, "structural": 10}
RATIONALE_OVERSAMPLE = 1.5
DEFAULT_SEED = 0


class GoldBuildError(RuntimeError):
    """Raised when a gold build is missing an input it needs."""


@dataclass(frozen=True)
class BuildOutcome:
    """What a gold build wrote.

    Attributes:
        items_path: The JSONL file.
        log_path: The build log.
        counts: Items per family.
        log: The build log's content.
    """

    items_path: Path
    log_path: Path
    counts: dict[str, int]
    log: dict


async def _ready_repo_id(db: AsyncSession, name: str, base_commit: str):
    """Find the newest ready eval repository ingested at the base commit."""
    row = (
        await db.execute(
            select(Repository.id)
            .where(
                Repository.name == name,
                Repository.status == "ready",
                Repository.ingested_commit_sha == base_commit,
            )
            .order_by(Repository.created_at.desc())
        )
    ).first()
    if row is None:
        raise GoldBuildError(f"no ready ingested repository {name!r} at {base_commit[:12]}")
    return row.id


def _mix_entry(selection: Selection) -> dict[str, int]:
    """One kind's requested, available, selected and short counts for the build log."""
    return {
        "requested": selection.requested,
        "available": selection.available,
        "selected": len(selection.items),
        "shortfall": selection.shortfall,
    }


async def build_gold(
    db: AsyncSession,
    *,
    corpus_repo: CorpusRepo,
    out_dir: Path,
    clones_dir: Path,
    seed: int = DEFAULT_SEED,
    hand_file: Path | None = None,
    include_anchor: bool = False,
    include_rationale: bool = False,
    include_structural: bool = False,
    include_unanswerable: bool = False,
) -> BuildOutcome:
    """Build one repository's questions to its question mix and write the results.

    Change questions are mined from pull requests merged after the base commit and chosen by
    cluster up to the mix's count; explain questions come from the hand file up to the mix's
    count, minus any the independent check found unsupported. A pool smaller than the request is
    reported in the build log and printed by the command, never an error.

    Args:
        db: A session on the eval database.
        corpus_repo: The pinned repository.
        out_dir: The eval output directory; reads ``<out_dir>/github`` and writes
            ``<out_dir>/gold/<name>/``.
        clones_dir: Where harness clones live.
        seed: The sampling seed.
        hand_file: Overrides where the hand questions are read from.
        include_anchor: Also build the change questions that name a starting file. Off by
            default: only the blind variant is built.
        include_rationale: Also build the "why" questions from blame. Off by default.
        include_structural: Also build the import-graph questions; this needs the ingested
            repository. Off by default.
        include_unanswerable: Keep the hand items marked unanswerable. Off by default.

    Returns:
        Where the files were written and the per-family counts.

    Raises:
        GoldBuildError: If the clone, the pull request cache or the ingested repository is
            missing.
    """
    base = corpus_repo.base_commit
    clone = clone_dir(clones_dir, corpus_repo.slug)
    if not clone.exists() or not rev_exists(clone, base):
        raise GoldBuildError(f"no clone containing {base[:12]}; run `mine` first")
    tip = default_tip(clone)
    cache_dir = Path(out_dir) / "github"
    index = load_index(cache_dir, corpus_repo.slug)
    if tip is None or index is None:
        raise GoldBuildError("no pull request cache; run `mine` first")
    prs = load_prs(cache_dir, corpus_repo.slug)
    post = [pr for pr in prs if pr.number in set(index.post_base)]
    pre = {pr.merge_commit_sha: pr for pr in prs if pr.number in set(index.pre_base)}

    changeset = build_changeset_items(
        repo_name=corpus_repo.name,
        clone=clone,
        base_commit=base,
        prs=post,
        drift_window=corpus_repo.drift_window,
        generator_cutoff=corpus_repo.generator_cutoff,
        tip=tip,
    )
    rationale: list[GoldItem] = []
    if include_rationale:
        rationale = build_rationale_items(
            repo_name=corpus_repo.name,
            clone=clone,
            base_commit=base,
            prs_by_merge_sha=pre,
            tip=tip,
            files=files_at(clone, base),
            seed=seed,
            per_repo_target=round(TARGETS["rationale"] * RATIONALE_OVERSAMPLE),
            generator_cutoff=corpus_repo.generator_cutoff,
        )
    structural: list[GoldItem] = []
    if include_structural:
        repo_id = await _ready_repo_id(db, corpus_repo.name, base)
        structural = await build_structural_items(
            db, repo_name=corpus_repo.name, repo_id=repo_id, base_commit=base, seed=seed
        )
    hand = load_hand_items(
        hand_file or hand_path(corpus_repo.name), repo_name=corpus_repo.name, base_commit=base
    )

    target_dir = Path(out_dir) / "gold" / corpus_repo.name
    mix = corpus_repo.questions
    change = select_change_items(
        changeset.items, mix.change, seed=seed, include_anchor=include_anchor
    )
    outcome = apply_checks(hand, all_checks(target_dir))
    explain = select_explain_items(
        outcome.kept, mix.explain, seed=seed, include_unanswerable=include_unanswerable
    )

    items: dict[str, GoldItem] = {
        item.id: item for item in [*change.items, *rationale, *structural, *explain.items]
    }
    counts = dict(sorted(Counter(item.family for item in items.values()).items()))
    templates = dict(sorted(Counter(item.template for item in items.values()).items()))
    log = {
        "repo": corpus_repo.name,
        "base_commit": base,
        "tip": tip,
        "seed": seed,
        "counts": counts,
        "templates": templates,
        "mix": {"change": _mix_entry(change), "explain": _mix_entry(explain)},
        "checks": {
            "dropped_unsupported": sorted(item.id for item in outcome.unsupported),
            "partly_supported": [
                {"item": item.id, "faulty_claim": record.faulty_claim}
                for item, record in outcome.partly_supported
            ],
            "unchecked": len(outcome.unchecked),
        },
        "options": {
            "include_anchor": include_anchor,
            "include_rationale": include_rationale,
            "include_structural": include_structural,
            "include_unanswerable": include_unanswerable,
        },
        "drops": dict(sorted(Counter(reason for _, reason in changeset.drops).items())),
        "dropped_prs": [{"pr": number, "reason": why} for number, why in changeset.drops],
    }
    items_path = write_jsonl(target_dir / "items.jsonl", items.values())
    log_path = target_dir / "build_log.json"
    log_path.write_bytes((canonical_json(log) + "\n").encode("utf-8"))
    return BuildOutcome(items_path, log_path, counts, log)
