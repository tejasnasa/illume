/**
 * The shapes and colour rules of the dependency graph.
 *
 * @module graphTypes
 *
 * The colours are the web client's, unchanged: the graph is the one place
 * where a colour carries meaning that the reader has to learn, and a
 * different palette on the phone would make the two clients disagree about
 * the same repository.
 */

import type Graph from "@/types/graph";

/** One node of the graph, as the renderer sees it. */
export type GraphNodeMeta = Graph["nodes"][number];

/** One edge of the graph, as the renderer sees it. */
export type GraphLinkMeta = Graph["links"][number];

/** The graph at one level of granularity. */
export type GraphPayload = Graph;

/** A node that has been picked out of the graph. */
export const NODE_COLOR_SELECTED = "#0078ff";

/** A node that matches the current search. */
export const NODE_COLOR_MATCH = "#a855f7";

/** A node the backend marked as critical. */
export const NODE_COLOR_CRITICAL = "#ef4444";

/** A node the backend marked as needing caution. */
export const NODE_COLOR_CAUTION = "#facc15";

/** A node with no criticality of its own. */
export const NODE_COLOR_SAFE = "#22c55e";

/** The colour of every link that is not incident to the selection. */
export const LINK_COLOR_DIM = 0.6;

/** The colour of a link incident to the selection. */
export const LINK_COLOR_FOCUSED = 0xa8c8ff;

/**
 * Colour a node by its criticality, matching the web client's mapping.
 *
 * @param criticality - Bucket name from the backend.
 * @returns A hex colour.
 */
export function criticalityColor(criticality: string | null | undefined): string {
  switch (criticality) {
    case "critical":
      return NODE_COLOR_CRITICAL;
    case "caution":
      return NODE_COLOR_CAUTION;
    default:
      return NODE_COLOR_SAFE;
  }
}

/**
 * Node radius from lines of code, matching the web client's formula.
 *
 * @param loc - Lines of code for the node.
 * @param scale - View scale, so the same data reads well in 3D and in 2D.
 * @returns Radius in world units.
 */
export function nodeRadius(loc: number, scale = 1): number {
  return Math.sqrt(Math.max(loc || 0, 10)) * 0.5 * scale;
}
