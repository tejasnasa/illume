/**
 * Overview tiles drawn from the repository's file graph: the risk spread and
 * a flat map of the graph.
 * @module OverviewGraphTiles
 */
"use client";

import { useRepoGraph } from "@/components/RepoGraphContext";
import type Graph from "@/types/graph";
import Link from "next/link";
import { useMemo } from "react";

const RISK = [
  { key: "critical", label: "Critical", color: "#ef4444" },
  { key: "caution", label: "Caution", color: "#facc15" },
  { key: "safe", label: "Safe", color: "#22c55e" },
] as const;

type RiskKey = (typeof RISK)[number]["key"];

/**
 * Buckets a stored criticality into one of the three risk levels.
 *
 * Anything other than `critical` or `caution` counts as safe, matching how the
 * graph colours nodes.
 *
 * @param value The node's criticality column.
 * @returns The bucket.
 */
function riskOf(value: string | null | undefined): RiskKey {
  const v = (value ?? "").toLowerCase().trim();
  return v === "critical" || v === "caution" ? v : "safe";
}

/**
 * The header tile: how many files fall in each risk level, linking to the graph.
 *
 * Renders nothing until the layout has the graph, so a failed graph fetch
 * leaves the header without the tile rather than showing zeros.
 *
 * @param repoNumber The repository's user-scoped number, for the graph link.
 * @returns The tile, or null.
 */
export function RiskSpread({ repoNumber }: { repoNumber: number }) {
  const graph = useRepoGraph();
  const counts = useMemo(() => {
    const c: Record<RiskKey, number> = { critical: 0, caution: 0, safe: 0 };
    for (const node of graph?.nodes ?? []) c[riskOf(node.criticality)]++;
    return c;
  }, [graph]);

  if (!graph || graph.nodes.length === 0) return null;
  const total = graph.nodes.length;
  const summary = RISK.map((r) => `${counts[r.key]} ${r.label.toLowerCase()}`).join(", ");

  return (
    <Link
      href={`/repo/${repoNumber}/graph`}
      aria-label={`Risk spread across ${total} files: ${summary}. Open the graph.`}
      className="ghost flex w-full flex-col gap-2.5 rounded-sm border border-(--border) bg-(--card) px-4 py-3.5 text-(--muted-foreground) sm:w-115"
    >
      <span className="flex justify-between font-pixel text-[11px] tracking-[0.12em] uppercase">
        <span>Risk spread · {total.toLocaleString()} files</span>
        <span className="text-(--subtle-foreground)">Graph →</span>
      </span>
      <span aria-hidden="true" className="flex h-2.5 gap-0.5">
        {RISK.map(
          (r) =>
            counts[r.key] > 0 && (
              <span
                key={r.key}
                className="min-w-1.5"
                style={{ flex: `${counts[r.key]} 1 0`, background: r.color }}
              />
            ),
        )}
      </span>
      <span className="flex flex-wrap gap-x-4 gap-y-1.5 font-pixel text-xs text-zinc-300 uppercase">
        {RISK.map((r) => (
          <span key={r.key} className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5" style={{ background: r.color }} />
            {counts[r.key].toLocaleString()} {r.label}
          </span>
        ))}
      </span>
    </Link>
  );
}

const MAP_W = 360;
const MAP_H = 210;
const MAX_NODES = 240;
const GOLDEN = Math.PI * (3 - Math.sqrt(5));

/**
 * Lays the graph out flat: the busiest files, clustered by directory.
 *
 * Each directory gets a centre on an ellipse, larger directories first, and
 * its files spiral out from that centre. It is a quick sketch of the real
 * graph's shape for the tile, not a force layout.
 *
 * @param graph The file graph.
 * @returns Positioned nodes and the links between them.
 */
function sketch(graph: Graph) {
  const nodes = [...graph.nodes]
    .sort((a, b) => b.fan_in + b.fan_out - (a.fan_in + a.fan_out))
    .slice(0, MAX_NODES);

  const groups = new Map<string, typeof nodes>();
  for (const n of nodes) {
    const list = groups.get(n.group) ?? [];
    list.push(n);
    groups.set(n.group, list);
  }
  const ordered = [...groups.values()].sort((a, b) => b.length - a.length);

  const placed = new Map<string, { x: number; y: number; color: string; size: number }>();
  ordered.forEach((members, gi) => {
    const angle = (gi / ordered.length) * Math.PI * 2 - Math.PI / 2;
    const ring = ordered.length === 1 ? 0 : gi === 0 ? 0.15 : 0.62;
    const cx = MAP_W / 2 + Math.cos(angle) * ring * (MAP_W / 2 - 30);
    const cy = MAP_H / 2 + Math.sin(angle) * ring * (MAP_H / 2 - 22);
    members.forEach((n, i) => {
      const r = 3.2 * Math.sqrt(i);
      const a = i * GOLDEN;
      placed.set(n.id, {
        x: Math.max(4, Math.min(MAP_W - 4, cx + Math.cos(a) * r * 1.4)),
        y: Math.max(4, Math.min(MAP_H - 4, cy + Math.sin(a) * r)),
        color: RISK.find((k) => k.key === riskOf(n.criticality))!.color,
        size: n.fan_in > 8 ? 4 : 3,
      });
    });
  });

  // The 3D renderer swaps link endpoints for node objects in place, so accept both.
  const endpoint = (end: unknown) =>
    typeof end === "object" && end !== null ? (end as { id: string }).id : (end as string);
  const links = graph.links.flatMap((l) => {
    const a = placed.get(endpoint(l.source));
    const b = placed.get(endpoint(l.target));
    return a && b ? [[a, b] as const] : [];
  });

  return { points: [...placed.values()], links };
}

/**
 * The dependency-graph tile: a flat sketch of the graph and its size.
 *
 * @param repoNumber The repository's user-scoped number, for the graph link.
 * @returns The tile, or null when there is no graph.
 */
export function GraphTile({
  repoNumber,
  className = "",
}: {
  repoNumber: number;
  className?: string;
}) {
  const graph = useRepoGraph();
  const drawn = useMemo(() => (graph ? sketch(graph) : null), [graph]);
  if (!graph || !drawn || graph.nodes.length === 0) return null;

  return (
    <Link
      href={`/repo/${repoNumber}/graph`}
      className={`panel group flex flex-col overflow-hidden text-(--foreground) hover:border-(--border-strong) ${className}`}
    >
      <div className="relative h-52.5 bg-[#060608]">
        <svg
          viewBox={`0 0 ${MAP_W} ${MAP_H}`}
          preserveAspectRatio="xMidYMid meet"
          shapeRendering="crispEdges"
          aria-hidden="true"
          className="absolute inset-0 h-full w-full"
        >
          {drawn.links.map(([a, b], i) => (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="#ffffff"
              strokeOpacity={0.08}
              strokeWidth={1}
            />
          ))}
          {drawn.points.map((p, i) => (
            <rect
              key={i}
              x={Math.round(p.x - p.size / 2)}
              y={Math.round(p.y - p.size / 2)}
              width={p.size}
              height={p.size}
              fill={p.color}
            />
          ))}
        </svg>
        <span className="absolute top-3.5 left-4 font-pixel text-xs tracking-[0.12em] text-(--muted-foreground) uppercase">
          Dependency graph
        </span>
      </div>
      <div className="flex items-center justify-between border-t border-white/8 px-4.5 py-3.5 font-pixel text-xs tracking-[0.06em] text-(--muted-foreground) uppercase">
        <span>
          {graph.metadata.total_nodes.toLocaleString()} files ·{" "}
          {graph.metadata.total_edges.toLocaleString()} edges
        </span>
        <span className="text-(--accent)">Open 3D →</span>
      </div>
    </Link>
  );
}
