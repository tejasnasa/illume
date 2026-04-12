export default interface Graph {
  nodes: {
    id: string;
    label: string;
    path: string;
    group: string;
    kind: string;
    loc: number;
    health: number;
    language: string;
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
