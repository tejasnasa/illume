/**
 * Minimal ambient types for `d3-force-3d`.
 *
 * The package ships no declarations and there is no `@types` entry. Only
 * the surface this app actually uses is described, rather than a
 * speculative full transcription.
 */
declare module "d3-force-3d" {
  export interface SimulationNodeDatum {
    index?: number;
    x?: number;
    y?: number;
    z?: number;
    vx?: number;
    vy?: number;
    vz?: number;
  }

  export interface SimulationLinkDatum<N> {
    source: N | string | number;
    target: N | string | number;
    index?: number;
  }

  export interface Simulation<N extends SimulationNodeDatum> {
    tick(iterations?: number): this;
    stop(): this;
    restart(): this;
    nodes(): N[];
    nodes(nodes: N[]): this;
    alpha(): number;
    alpha(value: number): this;
    alphaDecay(value: number): this;
    force(name: string): unknown;
    force(name: string, force: unknown): this;
  }

  export function forceSimulation<N extends SimulationNodeDatum>(
    nodes?: N[],
    numDimensions?: number,
  ): Simulation<N>;

  export function forceLink<N extends SimulationNodeDatum, L>(
    links?: L[],
  ): {
    id(
      accessor: (node: N, i: number, nodes: N[]) => string | number,
    ): ReturnType<typeof forceLink>;
    distance(
      value: number | ((link: L, i: number, links: L[]) => number),
    ): ReturnType<typeof forceLink>;
    strength(
      value: number | ((link: L, i: number, links: L[]) => number),
    ): ReturnType<typeof forceLink>;
    iterations(value: number): ReturnType<typeof forceLink>;
  };

  export function forceManyBody(): {
    strength(
      value:
        | number
        | ((
            node: SimulationNodeDatum,
            i: number,
            nodes: SimulationNodeDatum[],
          ) => number),
    ): ReturnType<typeof forceManyBody>;
    theta(value: number): ReturnType<typeof forceManyBody>;
    distanceMin(value: number): ReturnType<typeof forceManyBody>;
    distanceMax(value: number): ReturnType<typeof forceManyBody>;
  };

  export function forceCenter(x?: number, y?: number, z?: number): unknown;

  export function forceCollide(
    radius?:
      | number
      | ((
          node: SimulationNodeDatum,
          i: number,
          nodes: SimulationNodeDatum[],
        ) => number),
  ): unknown;
}
