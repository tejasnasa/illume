import json
import logging
from collections import defaultdict, deque
from typing import Any
from uuid import UUID

import openai
from app.core.config import settings
from app.models import AstSymbol, Dependency, File, OnboardingGuide
from sqlalchemy.orm import Session, aliased

logger = logging.getLogger(__name__)

MAX_ANNOTATED_FILES = 100

ANNOTATION_BATCH_SIZE = 10


def _build_file_graph(
    db: Session,
    repo_id: UUID,
) -> tuple[dict[UUID, set[UUID]], dict[UUID, set[UUID]]]:
    TargetSymbol = aliased(AstSymbol, name="tgt_sym")

    repo_file_ids = db.query(File.id).filter(File.repository_id == repo_id).subquery()

    repo_file_ids = (
        db.query(File.id).filter(File.repository_id == repo_id).scalar_subquery()
    )

    rows = (
        db.query(
            AstSymbol.file_id.label("src_file"),
            TargetSymbol.file_id.label("tgt_file"),
        )
        .join(Dependency, Dependency.source_symbol_id == AstSymbol.id)
        .join(TargetSymbol, Dependency.target_symbol_id == TargetSymbol.id)
        .filter(AstSymbol.file_id.in_(repo_file_ids))
        .all()
    )

    deps: dict[UUID, set[UUID]] = defaultdict(set)
    rdeps: dict[UUID, set[UUID]] = defaultdict(set)

    for src_file, tgt_file in rows:
        if src_file == tgt_file:
            continue
        deps[src_file].add(tgt_file)
        rdeps[tgt_file].add(src_file)

    return deps, rdeps


def _topological_sort(
    files: list[File],
    deps: dict[UUID, set[UUID]],
    rdeps: dict[UUID, set[UUID]],
) -> list[list[File]]:
    file_map: dict[UUID, File] = {f.id: f for f in files}
    all_ids: set[UUID] = set(file_map)

    in_degree: dict[UUID, int] = {fid: len(deps.get(fid, set())) for fid in all_ids}

    queue: deque[UUID] = deque(fid for fid in all_ids if in_degree[fid] == 0)

    tiers: list[list[File]] = []
    visited: set[UUID] = set()

    while queue:
        current_tier_ids = list(queue)
        queue.clear()
        visited.update(current_tier_ids)

        current_tier = sorted(
            [file_map[fid] for fid in current_tier_ids if fid in file_map],
            key=lambda f: f.fan_in or 0,
            reverse=True,
        )
        if current_tier:
            tiers.append(current_tier)

        next_candidates: set[UUID] = set()
        for fid in current_tier_ids:
            for importer_id in rdeps.get(fid, set()):
                if importer_id in visited:
                    continue
                deps[importer_id].discard(fid)
                in_degree[importer_id] -= 1
                if in_degree[importer_id] == 0:
                    next_candidates.add(importer_id)
        queue.extend(next_candidates)

    remaining = [file_map[fid] for fid in all_ids - visited if fid in file_map]
    if remaining:
        logger.warning(
            "reading_order: %d files in dependency cycle(s), appending as final tier",
            len(remaining),
        )
        remaining_sorted = sorted(remaining, key=lambda f: f.fan_in or 0, reverse=True)
        tiers.append(remaining_sorted)

    return tiers


def _build_annotation_prompt(batch: list[dict[str, Any]]) -> str:
    items = "\n".join(
        f"{i + 1}. path={item['path']} | fan_in={item['fan_in']} "
        f"| fan_out={item['fan_out']} | tier={item['tier']} "
        f"| language={item['language'] or 'unknown'}"
        for i, item in enumerate(batch)
    )

    return f"""You are an expert software engineer writing an onboarding guide.

For each file below, write a 1-2 sentence explanation of WHY a new engineer should read it at this point in their onboarding journey. Be concrete about what the file does and why understanding it early unlocks the rest of the codebase. Do not use filler phrases like "this file is important". Be direct.

Files (in suggested reading order):
{items}

Respond ONLY with a JSON array, no markdown fences, no preamble:
[
  {{"file_path": "<path>", "annotation": "<1-2 sentence why-read-this>"}},
  ...
]
"""


def _annotate_files(ordered_files: list[dict[str, Any]]) -> dict[str, str]:
    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    annotations: dict[str, str] = {}

    to_annotate = ordered_files[:MAX_ANNOTATED_FILES]

    for i in range(0, len(to_annotate), ANNOTATION_BATCH_SIZE):
        batch = to_annotate[i : i + ANNOTATION_BATCH_SIZE]
        prompt = _build_annotation_prompt(batch)

        try:
            response = client.responses.create(
                model=settings.AI_MODEL,
                reasoning={"effort": "minimal"},
                input=[{"role": "user", "content": prompt}],
                max_output_tokens=1000,
            )
            raw = response.output_text or "[]"
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed: list[dict] = json.loads(raw)
            for entry in parsed:
                path = entry.get("file_path", "")
                annotation = entry.get("annotation", "")
                if path and annotation:
                    annotations[path] = annotation
        except Exception as exc:
            logger.error(
                "reading_order: LLM annotation failed for batch %d-%d: %s",
                i,
                i + ANNOTATION_BATCH_SIZE,
                exc,
            )

    return annotations


def build_reading_order(db: Session, repo_id: UUID) -> OnboardingGuide:
    logger.info("reading_order: starting for repo %s", repo_id)

    files: list[File] = db.query(File).filter(File.repository_id == repo_id).all()

    if not files:
        logger.warning("reading_order: no files found for repo %s", repo_id)
        return _upsert_guide(db, repo_id, [])

    logger.info("reading_order: loaded %d files", len(files))

    deps, rdeps = _build_file_graph(db, repo_id)

    for f in files:
        deps.setdefault(f.id, set())
        rdeps.setdefault(f.id, set())

    tiers: list[list[File]] = _topological_sort(files, deps, rdeps)

    ordered_flat: list[dict[str, Any]] = []
    position = 1

    for tier_index, tier in enumerate(tiers):
        for f in tier:
            ordered_flat.append(
                {
                    "file_id": str(f.id),
                    "path": f.path,
                    "fan_in": f.fan_in or 0,
                    "fan_out": f.fan_out or 0,
                    "language": f.language,
                    "tier": tier_index,
                    "position": position,
                    "annotation": "",
                }
            )
            position += 1

    logger.info(
        "reading_order: %d tiers, %d files total", len(tiers), len(ordered_flat)
    )

    annotations = _annotate_files(ordered_flat)

    for item in ordered_flat:
        item["annotation"] = annotations.get(item["path"], "")

    guide = _upsert_guide(db, repo_id, ordered_flat)
    logger.info("reading_order: done for repo %s", repo_id)
    return guide


def _upsert_guide(
    db: Session,
    repo_id: UUID,
    reading_order: list[dict[str, Any]],
) -> OnboardingGuide:
    guide = (
        db.query(OnboardingGuide)
        .filter(OnboardingGuide.repository_id == repo_id)
        .first()
    )

    if guide is None:
        guide = OnboardingGuide(
            repository_id=repo_id,
            reading_order=reading_order,
            architecture_brief=json.dumps({}),
            critical_files=[],
            pdf_path=None,
        )
        db.add(guide)
    else:
        guide.reading_order = reading_order

    db.commit()
    db.refresh(guide)
    return guide
