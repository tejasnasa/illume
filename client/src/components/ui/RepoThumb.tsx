/**
 * The picture at the top of each repository card: a still frame of the
 * repository's own graph, condensed to its busiest files.
 * @module RepoThumb
 */
"use client";

import PixelGraph from "@/components/PixelGraph";
import type Graph from "@/types/graph";
import { useEffect, useState } from "react";

/**
 * A small deterministic PRNG, so a repository always gets the same picture.
 *
 * @param seed Any 32-bit integer.
 * @returns A function yielding numbers in [0, 1).
 */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Hashes a string to a 32-bit seed.
 *
 * @param text The input.
 * @returns The seed.
 */
function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h;
}

const WIDTH = 360;
const HEIGHT = 128;

/**
 * Renders a ready repository's own graph as one still pixel frame, and the
 * seeded placeholder for anything else: a card that is still ingesting or
 * failed, the moment before the graph arrives, or a graph that could not be
 * fetched or has no files.
 *
 * The frame is drawn once rather than animated, so a dashboard full of
 * cards costs no more per frame than an empty one.
 *
 * @param repoId The repository whose graph to draw.
 * @param tone `ready` fetches and draws the graph; `muted` keeps the dimmed placeholder.
 * @returns The picture.
 */
export default function RepoThumb({
  repoId,
  tone = "ready",
}: {
  repoId: string;
  tone?: "ready" | "muted";
}) {
  const [graph, setGraph] = useState<{ id: string; graph: Graph } | null>(null);

  useEffect(() => {
    if (tone !== "ready") return;
    const controller = new AbortController();
    fetch(
      `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository/${repoId}/graph/thumbnail`,
      {
        credentials: "include",
        signal: controller.signal,
      },
    )
      .then((res) => (res.ok ? res.json() : null))
      .then((data: Pick<Graph, "nodes" | "links"> | null) => {
        if (data && data.nodes.length > 0) {
          setGraph({ id: repoId, graph: data as Graph });
        }
      })
      // A missing picture is not worth an error: the placeholder stays.
      .catch(() => {});
    return () => controller.abort();
  }, [repoId, tone]);

  if (tone === "ready" && graph?.id === repoId) {
    return (
      <PixelGraph
        source={graph.graph}
        still
        cell={3}
        hubLabels={false}
        focusLabel={false}
        spreadX={0.4}
        spreadY={0.42}
        lightRadius={0.45}
      />
    );
  }
  return <Placeholder seed={repoId} tone={tone} />;
}

/**
 * A few seeded clusters of pixel nodes joined to their hubs, so each card
 * has a stable picture before, or instead of, its real graph.
 *
 * @param seed The repository id.
 * @param tone `ready` for full colour, `muted` for an in-progress or failed card.
 * @returns The SVG.
 */
function Placeholder({
  seed,
  tone,
}: {
  seed: string;
  tone: "ready" | "muted";
}) {
  const rnd = mulberry32(hash(seed));
  const clusters = 3 + Math.floor(rnd() * 2);
  const nodes: { x: number; y: number; s: number; hub: boolean }[] = [];
  const edges: [number, number][] = [];

  for (let c = 0; c < clusters; c++) {
    const cx = 40 + ((c + 0.5) / clusters) * (WIDTH - 80) + (rnd() - 0.5) * 30;
    const cy = 30 + rnd() * (HEIGHT - 60);
    const hub = nodes.push({ x: cx, y: cy, s: 6, hub: true }) - 1;
    if (c > 0) edges.push([hub, nodes.findIndex((n) => n.hub)]);
    const leaves = 4 + Math.floor(rnd() * 5);
    for (let l = 0; l < leaves; l++) {
      const angle = rnd() * Math.PI * 2;
      const r = 14 + rnd() * 26;
      const x = Math.max(
        6,
        Math.min(WIDTH - 6, cx + Math.cos(angle) * r * 1.4),
      );
      const y = Math.max(6, Math.min(HEIGHT - 6, cy + Math.sin(angle) * r));
      const leaf = nodes.push({ x, y, s: rnd() < 0.3 ? 4 : 3, hub: false }) - 1;
      edges.push([hub, leaf]);
    }
  }

  const colors =
    tone === "ready"
      ? ["#22c55e", "#22c55e", "#facc15", "#ef4444"]
      : ["#3f3f46", "#3f3f46", "#52525b", "#52525b"];

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="xMidYMid slice"
      shapeRendering="crispEdges"
      aria-hidden="true"
      className="absolute inset-0 h-full w-full"
    >
      {edges.map(([a, b], i) => (
        <line
          key={i}
          x1={nodes[a].x}
          y1={nodes[a].y}
          x2={nodes[b].x}
          y2={nodes[b].y}
          stroke="#ffffff"
          strokeOpacity={tone === "ready" ? 0.14 : 0.07}
          strokeWidth={1}
        />
      ))}
      {nodes.map((n, i) => (
        <rect
          key={i}
          x={Math.round(n.x - n.s / 2)}
          y={Math.round(n.y - n.s / 2)}
          width={n.s}
          height={n.s}
          fill={
            n.hub
              ? tone === "ready"
                ? "#53eafd"
                : "#52525b"
              : colors[i % colors.length]
          }
        />
      ))}
    </svg>
  );
}
