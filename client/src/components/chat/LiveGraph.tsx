/**
 * Full-viewport pixel dependency graph that follows an agent run.
 *
 * Atmosphere rather than a tool: it takes no pointer input, lights the files
 * the agent touches in the colour of the lane that touched them, glows the
 * ones its current call is looking at, runs a particle along the edges it
 * just followed, and turns to face each file a tool call lands on.
 *
 * Styling is read once per animation frame from a ref, so a run that lights
 * files ten times a second never re-renders the canvas or rebuilds its scene.
 * @module LiveGraph
 */
"use client";

import PixelGraph, { type PixelDecoration } from "@/components/PixelGraph";
import { CITED_COLOR, CURRENT_COLOR, MAIN_COLOR } from "@/lib/agent/palette";
import type { Highlight } from "@/lib/agent/reducer";
import type { NodeStyle, PixelNode, PixelScene } from "@/lib/pixelGraph";
import type Graph from "@/types/graph";
import { useCallback, useLayoutEffect, useMemo, useRef } from "react";

/** How many of the most recent moves between files keep their particle. */
const FOLLOWED_EDGES = 6;

/**
 * Converts `#rrggbb` to the `"r,g,b"` triple the renderer takes.
 *
 * @param hex - A six-digit hex colour.
 * @returns The triple, or white for anything unreadable.
 */
export function hexToRgb(hex: string): string {
  const match = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!match) return "250,250,250";
  return match
    .slice(1)
    .map((part) => parseInt(part, 16))
    .join(",");
}

/** What the canvas should show for the run as it stands. */
interface Look {
  /** Style per file path. */
  styles: Map<string, NodeStyle>;
  /** Unordered path pairs, joined with a newline, the agent just moved along. */
  followed: Set<string>;
  /** The file to box and name. */
  pinned: string | null;
}

const pairKey = (a: string, b: string) => (a < b ? `${a}\n${b}` : `${b}\n${a}`);

/**
 * Works out each file's look from the run.
 *
 * @param highlight - Which files the run touched, is touching, and cited.
 * @param laneColors - Hex colour per worker lane id.
 * @param live - Whether a run is in progress.
 * @param pulsePath - A file to pulse, as while its citation chip is hovered.
 * @returns The look.
 */
export function lookFor(
  highlight: Highlight,
  laneColors: Record<string, string>,
  live: boolean,
  pulsePath: string | null,
): Look {
  const styles = new Map<string, NodeStyle>();
  const laneTint = (path: string) => {
    const lane = highlight.laneOf[path];
    return hexToRgb((lane != null ? laneColors[lane] : undefined) ?? MAIN_COLOR);
  };
  for (const path of highlight.touched) {
    styles.set(path, { tint: laneTint(path), glow: live ? 0.4 : 0.2, scale: 1.4 });
  }
  if (!live) {
    for (const path of highlight.cited) {
      styles.set(path, { tint: hexToRgb(CITED_COLOR), glow: 0.7, scale: 1.5 });
    }
  } else {
    for (const path of highlight.current) {
      styles.set(path, { tint: laneTint(path), glow: 1, scale: 1.7 });
    }
  }
  if (pulsePath) styles.set(pulsePath, { tint: hexToRgb(CURRENT_COLOR), glow: 1, scale: 1.9 });

  const followed = new Set<string>();
  for (const [from, to] of highlight.edges.slice(-FOLLOWED_EDGES)) followed.add(pairKey(from, to));

  return {
    styles,
    followed,
    pinned: pulsePath ?? (live ? highlight.focus : null),
  };
}

/**
 * Renders the live graph behind the conversation.
 *
 * @param graph - File-level graph from the repository layout.
 * @param highlight - Which files the run touched, is touching, and cited.
 * @param laneColors - Hex colour per worker lane id.
 * @param live - Whether a run is in progress.
 * @param pulsePath - A file to pulse, as while its citation chip is hovered.
 * @returns A canvas that ignores the pointer.
 */
export default function LiveGraph({
  graph,
  highlight,
  laneColors,
  live,
  pulsePath,
}: {
  graph: Graph;
  highlight: Highlight;
  laneColors: Record<string, string>;
  live: boolean;
  pulsePath: string | null;
}) {
  const look = useMemo(
    () => lookFor(highlight, laneColors, live, pulsePath),
    [highlight, laneColors, live, pulsePath],
  );
  const lookRef = useRef(look);
  useLayoutEffect(() => {
    lookRef.current = look;
  }, [look]);

  // Stable, so the canvas never restarts; it reads the newest look each frame.
  const decorate = useCallback((scene: PixelScene): PixelDecoration => {
    const current = lookRef.current;
    const pinned = current.pinned ? (scene.byPath.get(current.pinned) ?? null) : null;
    return {
      style: (n: PixelNode) => (n.kind === 0 ? (current.styles.get(n.label) ?? null) : null),
      pinned,
      dimUnstyled: true,
      followed:
        current.followed.size > 0
          ? (a: PixelNode, b: PixelNode) => current.followed.has(pairKey(a.label, b.label))
          : undefined,
    };
  }, []);

  return (
    <PixelGraph
      source={graph}
      focusLabel={false}
      turnTo={look.pinned}
      decorate={decorate}
    />
  );
}
