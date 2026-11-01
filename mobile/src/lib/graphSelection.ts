/**
 * Picking things out of the dependency graph.
 *
 * @module graphSelection
 *
 * The rules that decide what the reader has selected, what the search
 * matched, and which links belong to the selection. They are pure
 * functions over the graph payload, so the behaviour can be pinned without
 * a renderer -- and the renderer itself is then left with nothing but
 * drawing.
 *
 * Two facts about the graph shape the rules:
 *
 * - A barrel file (``index.ts``, ``__init__.py``) contributes no node: it
 *   holds only re-exports, so the graph lifts its edges onto the files it
 *   re-exports. A path in the guide may therefore name a file that has no
 *   node at all, and the selection must survive that.
 * - The symbol level emits ``sibling`` links between symbols in the same
 *   file. They are not dependencies, but they are links, and the reader
 *   sees them.
 */

import type { IndexedLink } from "@/lib/graphLayout";
import type { GraphNodeMeta } from "@/lib/graphTypes";

/** How many search matches are highlighted at once. */
export const MAX_SEARCH_MATCHES = 24;

/** One step of the reading-order tour. */
export interface GuideStep {
  /** The graph node the step points at, if the graph has one for it. */
  node: GraphNodeMeta;
  /** The guide's own note about the file. */
  annotation: string;
  /** The file's position in the reading order. */
  position: number;
}

/**
 * Whether a node matches the current search text.
 *
 * The search matches on the label *or* the path, case-insensitively, which
 * is what the web client does.
 *
 * @param node - The node to test.
 * @param query - The search text.
 * @returns True when the node matches.
 */
export function isMatch(
  node: GraphNodeMeta,
  query: string,
): boolean {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return false;
  const label = node.label?.toLowerCase() ?? "";
  const path = node.path?.toLowerCase() ?? "";
  return label.includes(trimmed) || path.includes(trimmed);
}

/**
 * The nodes that match a search, capped.
 *
 * The cap matters: the graph has no node limit, and a search that matches
 * ten thousand files would ask the renderer to draw ten thousand haloes.
 * The matches are taken in the order the graph lists them, which is the
 * order the backend produced -- alphabetical by path at the file level.
 *
 * @param nodes - Every node in the graph.
 * @param query - The search text.
 * @param limit - How many matches to return.
 * @returns The matching nodes.
 */
export function matchNodes(
  nodes: readonly GraphNodeMeta[],
  query: string,
  limit = MAX_SEARCH_MATCHES,
): GraphNodeMeta[] {
  if (!query.trim()) return [];
  const matches: GraphNodeMeta[] = [];
  for (const node of nodes) {
    if (!isMatch(node, query)) continue;
    matches.push(node);
    if (matches.length >= limit) break;
  }
  return matches;
}

/**
 * The links that touch a node.
 *
 * @param links - Every link, resolved to node indices.
 * @param nodeIndex - The index of the selected node.
 * @returns The indices of the links that touch it.
 */
export function incidentLinkIndices(
  links: readonly IndexedLink[],
  nodeIndex: number,
): number[] {
  const incident: number[] = [];
  for (let i = 0; i < links.length; i += 1) {
    const { source, target } = links[i];
    if (source === nodeIndex || target === nodeIndex) incident.push(i);
  }
  return incident;
}

/**
 * The reading order, resolved to the nodes it points at.
 *
 * The guide names files by path and the graph knows nodes by path, so the
 * join is by path. A path the graph has no node for is skipped rather than
 * guessed at: a barrel file is in the reading order but contributes no
 * node, and pointing the tour at the wrong file would be worse than
 * skipping it.
 *
 * @param readingOrder - The guide's reading order.
 * @param nodes - Every node in the graph.
 * @returns The steps of the tour, in reading order.
 */
export function guideSteps(
  readingOrder: readonly {
    position: number;
    file_path: string;
    annotation: string;
  }[],
  nodes: readonly GraphNodeMeta[],
): GuideStep[] {
  const nodeByPath = new Map<string, GraphNodeMeta>();
  for (const node of nodes) nodeByPath.set(node.path, node);

  return [...readingOrder]
    .sort((a, b) => a.position - b.position)
    .flatMap((entry) => {
      const node = nodeByPath.get(entry.file_path);
      if (!node) return [];
      return [
        {
          node,
          annotation: entry.annotation,
          position: entry.position,
        },
      ];
    });
}

/**
 * The index of a node in the graph, by its identifier.
 *
 * @param nodes - Every node in the graph.
 * @param nodeId - The node's identifier.
 * @returns The index, or -1 when the graph has no such node.
 */
export function nodeIndexById(
  nodes: readonly GraphNodeMeta[],
  nodeId: string | null,
): number {
  if (!nodeId) return -1;
  for (let i = 0; i < nodes.length; i += 1) {
    if (nodes[i].id === nodeId) return i;
  }
  return -1;
}
