/**
 * Dependency graph payload for file- and symbol-level visualization.
 * @module GraphTypes
 */

/**
 * Graph nodes, weighted edges, and aggregate counts for the canvas.
 */
export default interface Graph {
  nodes: {
    id: string;
    label: string;
    path: string;
    group: string;
    kind: string;
    loc: number;
    criticality: string;
    criticality_score: number;
    language: string;
    fan_in: number;
    fan_out: number;
  }[];
  links: {
    source: string;
    target: string;
    type: string;
    weight: number;
  }[];
  metadata: {
    total_nodes: number;
    total_edges: number;
    clusters: number;
  };
}
