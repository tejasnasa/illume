/**
 * Colours shared by the activity block and the live graph.
 *
 * Literal hex values on purpose: Three.js parses node colours itself and
 * returns black for `oklch()` or `var()`, so the DOM and the canvas use the
 * same strings.
 * @module AgentPalette
 */

/** One colour per worker lane, in the order lanes first appear. */
export const LANE_COLORS = [
  "#38bdf8",
  "#f472b6",
  "#facc15",
  "#4ade80",
  "#a78bfa",
  "#fb923c",
] as const;

/** The colour of files the main agent has touched. */
export const MAIN_COLOR = "#7dd3fc";

/**
 * Files nothing has touched yet. The same blue as the ambient graph on the
 * other repository pages, shown translucent so lit files stand out.
 */
export const IDLE_COLOR = "#3b82f6";

/** The core of files the current tool call is looking at. */
export const CURRENT_COLOR = "#e0f2fe";

/** Files the finished answer cites. */
export const CITED_COLOR = "#f5d06b";

/** Links between untouched files: a quiet grey, as on the other pages' graphs. */
export const LINK_IDLE_COLOR = "#94a3b8";

/** Links between two files the run has touched. */
export const LINK_LIT_COLOR = "#7dd3fc";

/**
 * The colour for a lane.
 *
 * @param index - The lane's palette index.
 * @returns A hex colour, wrapping around the palette.
 */
export function laneColor(index: number): string {
  return LANE_COLORS[((index % LANE_COLORS.length) + LANE_COLORS.length) % LANE_COLORS.length];
}
