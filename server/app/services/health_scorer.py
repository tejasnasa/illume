import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Sequence

from app.models import AstSymbol, Dependency, File, HealthMetric
from sqlalchemy import select
from sqlalchemy.orm import Session

MAX_COMPLEXITY = 10  # avg cyclomatic above this -> full complexity penalty
MAX_FILE_LOC = 500  # file LOC above this -> LOC penalty
MAX_FUNCTION_LOC = 50  # function length above this -> LOC penalty
MAX_COUPLING = 10  # in+out degree above this -> full coupling penalty
HOTSPOT_THRESHOLD = 0.25  # composite hotspot score above this -> flagged


def _complexity_penalty(symbols: Sequence[AstSymbol]) -> tuple[float, float]:
    scored = [
        s.cyclomatic_complexity
        for s in symbols
        if s.kind in ("function", "method") and s.cyclomatic_complexity is not None
    ]
    if not scored:
        return 0.0, 0.0
    avg = sum(scored) / len(scored)
    penalty = min(avg / MAX_COMPLEXITY, 1.0)
    return penalty, avg


def _loc_penalty(file_loc: int, symbols: Sequence[AstSymbol]) -> float:
    file_loc = file_loc or 0

    file_component = min(max(file_loc - MAX_FILE_LOC, 0) / MAX_FILE_LOC, 1.0)

    functions = [s for s in symbols if s.kind in ("function", "method")]
    if functions:
        oversized = sum(
            1
            for s in functions
            if s.start_line is not None
            and s.end_line is not None
            and (s.end_line - s.start_line) > MAX_FUNCTION_LOC
        )
        fn_component = oversized / len(functions)
    else:
        fn_component = 0.0

    return (file_component + fn_component) / 2.0


def _coupling_penalty(
    symbol_ids: set[uuid.UUID],
    dep_rows: Sequence[Dependency],
) -> float:
    if not dep_rows:
        return 0.0

    in_deg = sum(1 for d in dep_rows if d.target_symbol_id in symbol_ids)
    out_deg = sum(1 for d in dep_rows if d.source_symbol_id in symbol_ids)
    total = in_deg + out_deg
    return min(total / MAX_COUPLING, 1.0)


def _duplication_penalty(symbols: Sequence[AstSymbol]) -> float:
    functions = [
        s for s in symbols if s.kind in ("function", "method") and s.source_code
    ]
    if not functions:
        return 0.0

    fingerprints: dict[str, int] = defaultdict(int)
    for s in functions:
        normalized = "".join(s.source_code.split())
        fp = hashlib.md5(normalized.encode("utf-8")).hexdigest()
        fingerprints[fp] += 1

    duplicate_count = sum(count - 1 for count in fingerprints.values() if count > 1)
    return min(duplicate_count / len(functions), 1.0)


def _circular_penalty(
    file_ids: Sequence[uuid.UUID],
    symbol_to_file: dict[uuid.UUID, uuid.UUID],
    dep_rows: Sequence[Dependency],
) -> tuple[float, int, set[uuid.UUID]]:
    if not dep_rows or not file_ids:
        return 0.0, 0, set()

    graph: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for d in dep_rows:
        src_file = symbol_to_file.get(d.source_symbol_id)
        tgt_file = symbol_to_file.get(d.target_symbol_id)
        if src_file and tgt_file and src_file != tgt_file:
            graph[src_file].add(tgt_file)

    index_counter = [0]
    index: dict[uuid.UUID, int] = {}
    lowlink: dict[uuid.UUID, int] = {}
    on_stack: dict[uuid.UUID, bool] = {}
    stack: list[uuid.UUID] = []
    sccs: list[list[uuid.UUID]] = []

    def strongconnect(start: uuid.UUID):
        call_stack = [(start, iter(graph.get(start, set())), [None])]
        index[start] = lowlink[start] = index_counter[0]
        index_counter[0] += 1
        stack.append(start)
        on_stack[start] = True

        while call_stack:
            node, neighbours, parent_slot = call_stack[-1]
            try:
                w = next(neighbours)
                if w not in index:
                    index[w] = lowlink[w] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(w)
                    on_stack[w] = True
                    call_stack.append((w, iter(graph.get(w, set())), [None]))
                elif on_stack.get(w):
                    lowlink[node] = min(lowlink[node], index[w])
            except StopIteration:
                call_stack.pop()
                if call_stack:
                    parent_node = call_stack[-1][0]
                    lowlink[parent_node] = min(lowlink[parent_node], lowlink[node])

                if lowlink[node] == index[node]:
                    scc = []
                    while True:
                        w = stack.pop()
                        on_stack[w] = False
                        scc.append(w)
                        if w == node:
                            break
                    sccs.append(scc)

    for fid in file_ids:
        if fid not in index:
            strongconnect(fid)

    files_in_cycle_set = {fid for scc in sccs if len(scc) > 1 for fid in scc}
    files_in_cycles = len(files_in_cycle_set)
    circular_dep_count = sum(1 for scc in sccs if len(scc) > 1)

    total_files = max(len(file_ids), 1)
    penalty = min(files_in_cycles / total_files, 1.0)
    return penalty, circular_dep_count, files_in_cycle_set


def _hotspot_reasons(
    complexity_p: float,
    coupling_p: float,
    duplication_p: float,
    loc_p: float,
) -> list[str]:
    THRESHOLD = 0.5
    reasons = []
    if complexity_p > THRESHOLD:
        reasons.append("High cyclomatic complexity")
    if coupling_p > THRESHOLD:
        reasons.append("High coupling (too many dependencies)")
    if duplication_p > THRESHOLD:
        reasons.append("Significant code duplication")
    if loc_p > THRESHOLD:
        reasons.append("File or functions are too large")
    return reasons


def compute_health_metrics(repo_id: uuid.UUID, db: Session) -> None:
    files: Sequence[File] = (
        db.execute(select(File).where(File.repository_id == repo_id)).scalars().all()
    )

    if not files:
        return

    file_ids = [f.id for f in files]

    symbols_all: Sequence[AstSymbol] = (
        db.execute(select(AstSymbol).where(AstSymbol.file_id.in_(file_ids)))
        .scalars()
        .all()
    )

    dep_rows: Sequence[Dependency] = []
    if symbols_all:
        symbol_ids_all = [s.id for s in symbols_all]
        dep_rows = (
            db.execute(
                select(Dependency).where(
                    Dependency.source_symbol_id.in_(symbol_ids_all)
                    | Dependency.target_symbol_id.in_(symbol_ids_all)
                )
            )
            .scalars()
            .all()
        )

    symbols_by_file: dict[uuid.UUID, list[AstSymbol]] = defaultdict(list)
    for s in symbols_all:
        symbols_by_file[s.file_id].append(s)

    symbol_to_file: dict[uuid.UUID, uuid.UUID] = {s.id: s.file_id for s in symbols_all}

    circ_penalty, circular_dep_count, files_in_cycle_set = _circular_penalty(
        file_ids, symbol_to_file, dep_rows
    )

    metric_rows: list[HealthMetric] = []
    weighted_score_sum = 0.0
    total_loc_sum = 0
    all_cyclomatic: list[float] = []

    for f in files:
        symbols = symbols_by_file.get(f.id, [])
        symbol_ids = {s.id for s in symbols}
        file_loc = f.loc or 0

        comp_p, avg_cyc = _complexity_penalty(symbols)
        loc_p = _loc_penalty(file_loc, symbols)
        coup_p = _coupling_penalty(symbol_ids, dep_rows)
        dup_p = _duplication_penalty(symbols)

        penalty = (
            comp_p * 30 + coup_p * 25 + dup_p * 20 + loc_p * 15 + circ_penalty * 10
        )
        file_score = max(0.0, min(100.0, 100.0 - penalty))

        hotspot_score = 0.35 * comp_p + 0.30 * coup_p + 0.15 * dup_p + 0.20 * loc_p
        is_hotspot = hotspot_score > HOTSPOT_THRESHOLD
        reasons = _hotspot_reasons(comp_p, coup_p, dup_p, loc_p) if is_hotspot else []
        file_circular_deps = 1 if f.id in files_in_cycle_set else 0

        breakdown = {
            "complexity_penalty": round(comp_p, 4),
            "coupling_penalty": round(coup_p, 4),
            "duplication_penalty": round(dup_p, 4),
            "loc_penalty": round(loc_p, 4),
            "circular_penalty": round(circ_penalty, 4),
            "hotspot_score": round(hotspot_score, 4),
            "is_hotspot": is_hotspot,
            "hotspot_reasons": reasons,
        }

        metric_rows.append(
            HealthMetric(
                repository_id=repo_id,
                file_id=f.id,
                overall_score=round(file_score, 2),
                complexity_score=round(1.0 - comp_p, 2),
                coupling_score=round(1.0 - coup_p, 2),
                duplication_score=round(1.0 - dup_p, 2),
                total_loc=file_loc,
                avg_cyclomatic=round(avg_cyc, 2),
                circular_deps=file_circular_deps,
                breakdown=breakdown,
                computed_at=datetime.now(timezone.utc),
            )
        )

        weight = max(file_loc, 1)
        weighted_score_sum += file_score * weight
        total_loc_sum += file_loc
        if avg_cyc > 0:
            all_cyclomatic.append(avg_cyc)

    repo_score = weighted_score_sum / max(total_loc_sum, 1)
    repo_avg_cyclomatic = sum(all_cyclomatic) / max(len(all_cyclomatic), 1)

    metric_rows.append(
        HealthMetric(
            repository_id=repo_id,
            file_id=None,
            overall_score=round(repo_score, 2),
            complexity_score=None,
            coupling_score=None,
            duplication_score=None,
            total_loc=total_loc_sum,
            avg_cyclomatic=round(repo_avg_cyclomatic, 2),
            circular_deps=circular_dep_count,
            breakdown={
                "total_files": len(files),
                "hotspot_count": sum(
                    1
                    for m in metric_rows
                    if m.breakdown and m.breakdown.get("is_hotspot")
                ),
                "circular_dep_count": circular_dep_count,
            },
            computed_at=datetime.now(timezone.utc),
        )
    )

    db.add_all(metric_rows)
    db.commit()
