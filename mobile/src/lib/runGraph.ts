/**
 * How the live graph in a chat turn looks for a run, as pure functions.
 *
 * @module runGraph
 *
 * Port of ``lookFor`` in ``client/src/components/chat/LiveGraph.tsx``. The
 * web draws the graph full-viewport and in 3D behind the conversation; the
 * phone draws a still, flat sketch inside the turn. Files the run has
 * touched are lit in the colour of the lane that touched them, the ones the
 * current tool call is looking at are larger, and a finished answer's cited
 * files are gold. Everything else is dim.
 */

import { CITED_COLOR, CURRENT_COLOR, MAIN_COLOR, laneColor } from "@/lib/agent/palette";
import type { Highlight, RunState } from "@/lib/agent/reducer";

/** The colour untouched files are drawn in. */
export const IDLE_DOT = "#3b82f6";

/** How one file is drawn. */
export interface DotLook {
  color: string;
  /** Multiplier on the base square size. */
  scale: number;
  /** Opacity, 0 to 1. */
  opacity: number;
}

/**
 * The colour of each worker lane, by lane id.
 *
 * @param run - The run.
 * @returns Hex colour per lane id.
 */
export function laneColorsOf(run: Pick<RunState, "lanes">): Record<string, string> {
  const colors: Record<string, string> = {};
  for (const [id, lane] of Object.entries(run.lanes)) colors[id] = laneColor(lane.colorIndex);
  return colors;
}

/**
 * Works out each touched or cited file's look.
 *
 * @param highlight - Which files the run touched, is touching and cited.
 * @param laneColors - Hex colour per worker lane id.
 * @param live - Whether the run is in progress.
 * @returns A look per file path; a path with no entry is idle.
 */
export function looksFor(
  highlight: Highlight,
  laneColors: Record<string, string>,
  live: boolean,
): Map<string, DotLook> {
  const looks = new Map<string, DotLook>();
  const tint = (path: string) => {
    const lane = highlight.laneOf[path];
    return (lane != null ? laneColors[lane] : undefined) ?? MAIN_COLOR;
  };
  for (const path of highlight.touched) {
    looks.set(path, { color: tint(path), scale: 1.5, opacity: 1 });
  }
  if (live) {
    for (const path of highlight.current) {
      looks.set(path, { color: CURRENT_COLOR, scale: 2.1, opacity: 1 });
    }
  } else {
    for (const path of highlight.cited) {
      looks.set(path, { color: CITED_COLOR, scale: 1.8, opacity: 1 });
    }
  }
  return looks;
}

/**
 * Every path a run has lit, so the sketch can keep them on the canvas.
 *
 * @param highlight - The run's highlight.
 * @returns The distinct paths.
 */
export function litPaths(highlight: Highlight): Set<string> {
  return new Set([...highlight.touched, ...highlight.current, ...highlight.cited]);
}

/**
 * Whether a run has anything to show on the graph.
 *
 * @param highlight - The run's highlight.
 * @returns True when at least one file was touched or cited.
 */
export function hasLitFiles(highlight: Highlight): boolean {
  return highlight.touched.length > 0 || highlight.cited.length > 0;
}
