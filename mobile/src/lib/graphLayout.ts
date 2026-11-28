/**
 * Force-directed layout for the dependency graph.
 *
 * @module graphLayout
 *
 * The simulation is deliberately run to a fixed tick count and then
 * stopped, rather than left running beside the renderer. That keeps the two
 * costs apart: the simulation is paid once, up front, and the renderer
 * then draws frozen positions.
 *
 * The simulation is chunked and yields to the event loop between chunks so
 * the progress bar can paint. A large repository is tens of thousands of
 * nodes, and a single synchronous run of that would freeze the screen for
 * the whole duration with nothing to show for it.
 *
 * `d3-force-3d` is the same simulation the web client runs underneath
 * `react-force-graph-3d`, so the layout matches production rather than
 * approximating it.
 */

import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationNodeDatum,
} from "d3-force-3d";

import type { GraphPayload } from "@/lib/graphTypes";

/** A simulation node, carrying its position in three dimensions. */
interface SimNode extends SimulationNodeDatum {
  id: string;
}

/** A link resolved to node indices rather than ids. */
export interface IndexedLink {
  source: number;
  target: number;
}

/** What {@link computeLayout} produces. */
export interface LayoutResult {
  /** `xyz` triples, one per node, in node order. */
  positions: Float32Array;
  /** Links resolved to node indices. */
  links: IndexedLink[];
  /** Radius that contains every node, used to frame the camera. */
  boundingRadius: number;
  /** Wall-clock time spent simulating, in milliseconds. */
  simulationMs: number;
  /** How many ticks were actually run. */
  ticks: number;
  /** How many nodes were laid out; fewer than the payload's when it was capped. */
  nodeCount: number;
  /** True when the payload had more than {@link MAX_LAYOUT_NODES} nodes. */
  truncated: boolean;
}

/**
 * The most nodes the layout will simulate.
 *
 * The endpoint has no node cap. Past this size the simulation and the
 * per-node buffers cost more memory and time than a phone has, and the
 * picture is unreadable anyway, so the payload is cut here and the screen
 * says so.
 */
export const MAX_LAYOUT_NODES = 30_000;

/** The longest a chunk of ticks may run before it yields to the event loop. */
const CHUNK_BUDGET_MS = 24;

/** Tuning for {@link computeLayout}. */
export interface LayoutOptions {
  /** Total simulation ticks. More ticks means a more settled layout and more time. */
  ticks?: number;
  /** Ticks between yields, so progress can paint. Smaller keeps the UI responsive. */
  chunkSize?: number;
  /** Repulsion strength. */
  chargeStrength?: number;
  /** Called after each chunk with ticks completed so far. */
  onProgress?: (done: number, total: number) => void;
  /**
   * Stops the simulation between chunks.
   *
   * A layout of a large repository runs for hundreds of ticks. Without this,
   * leaving the screen only discards the result -- the simulation keeps
   * ticking in the background and a second graph queues behind it.
   */
  signal?: AbortSignal;
}

/**
 * Choose a default tick count for a graph size.
 *
 * Large graphs get fewer ticks: the layout is worse, but spending a minute
 * in the simulation to draw a graph nobody can read is a bad trade. The
 * result is still legible at every size.
 *
 * @param nodeCount - Number of nodes.
 * @returns A tick count.
 */
export function defaultTicks(nodeCount: number): number {
  if (nodeCount <= 1_000) return 300;
  if (nodeCount <= 5_000) return 200;
  if (nodeCount <= 10_000) return 150;
  return 100;
}

/**
 * Yield to the event loop so React can paint progress.
 *
 * `setTimeout(0)` rather than a microtask: a microtask would drain before
 * the renderer got a chance to commit, so the progress bar would never
 * move.
 *
 * @returns A promise resolving on the next macrotask.
 */
function yieldToUI(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * A coordinate the simulation produced, or 0 when it is missing or not finite.
 *
 * A NaN position turns every matrix it touches into NaN and the node
 * silently disappears; zero keeps it on screen at the centre.
 *
 * @param value - A coordinate.
 * @returns A finite number.
 */
export function finiteOrZero(value: number | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/**
 * Find the radius that contains every node.
 *
 * Used to frame the camera without hardcoding a distance, so a five-hundred
 * node graph and a twenty-five-thousand node graph both fill the viewport
 * sensibly.
 *
 * @param positions - `xyz` triples.
 * @returns The maximum distance from the origin.
 */
export function boundingRadius(positions: Float32Array): number {
  let maxSq = 0;
  for (let i = 0; i < positions.length; i += 3) {
    const x = positions[i];
    const y = positions[i + 1];
    const z = positions[i + 2];
    const d = x * x + y * y + z * z;
    if (Number.isFinite(d) && d > maxSq) maxSq = d;
  }
  const radius = Math.sqrt(maxSq);
  return Number.isFinite(radius) && radius > 0 ? radius : 1;
}

/**
 * Run a 3D force simulation and freeze the result.
 *
 * @param data - The graph to lay out.
 * @param options - Tick count, chunk size, and progress callback.
 * @returns Positions, indexed links, and timing.
 */
export async function computeLayout(
  data: GraphPayload,
  options: LayoutOptions = {},
): Promise<LayoutResult> {
  // A payload that is missing either list is treated as an empty graph
  // rather than thrown at: the layout runs inside an effect, where a throw
  // is an unhandled rejection and the screen is left loading forever.
  const allNodes = Array.isArray(data?.nodes) ? data.nodes : [];
  const allLinks = Array.isArray(data?.links) ? data.links : [];
  const truncated = allNodes.length > MAX_LAYOUT_NODES;
  const nodes = truncated ? allNodes.slice(0, MAX_LAYOUT_NODES) : allNodes;
  const nodeCount = nodes.length;
  const ticks = options.ticks ?? defaultTicks(nodeCount);
  const chunkSize = Math.max(1, options.chunkSize ?? 10);
  // Repulsion and link length are tuned for a phone-sized viewport: at the
  // web defaults (-30 / 30) a few hundred nodes bunch into one blob and the
  // spheres of neighbouring nodes merge, which reads as a single mass
  // rather than as a network. Spacing them apart is what makes the
  // structure legible at this size.
  const chargeStrength = options.chargeStrength ?? -110;

  const simNodes: SimNode[] = nodes.map((node) => ({ id: node.id }));
  const indexById = new Map<string, number>();
  simNodes.forEach((node, i) => indexById.set(node.id, i));

  const simLinks: IndexedLink[] = [];
  for (const link of allLinks) {
    const source = indexById.get(link.source);
    const target = indexById.get(link.target);
    if (source === undefined || target === undefined || source === target) {
      continue;
    }
    simLinks.push({ source, target });
  }

  // The link force rewrites `source` and `target` from indices into node
  // references, so it gets throwaway copies. Handing it `simLinks` directly
  // would leave the returned array holding objects where the renderer
  // expects numbers.
  //
  // The `id` accessor is deliberately left at its default, which is
  // positional. Overriding it with the node's string id would make d3 try
  // to resolve the numeric indices in these links against that accessor
  // and fail with "node not found".
  const forceLinks = simLinks.map((link) => ({
    source: link.source,
    target: link.target,
  }));

  const started = Date.now();

  if (nodeCount === 0) {
    return {
      positions: new Float32Array(0),
      links: [],
      boundingRadius: 1,
      simulationMs: 0,
      ticks: 0,
      nodeCount: 0,
      truncated,
    };
  }

  const sim = forceSimulation(simNodes, 3)
    .force(
      "link",
      forceLink<SimNode, { source: number; target: number }>(forceLinks)
        .distance(45)
        .strength(0.25),
    )
    .force("charge", forceManyBody().strength(chargeStrength))
    .force("center", forceCenter(0, 0, 0))
    .stop();

  let done = 0;
  while (done < ticks) {
    if (options.signal?.aborted) break;
    // Run ticks until the chunk is full or its time budget is spent, so a
    // very large graph yields after a tick or two instead of after ten.
    const chunkStart = Date.now();
    const end = Math.min(done + chunkSize, ticks);
    while (done < end) {
      sim.tick();
      done += 1;
      if (Date.now() - chunkStart > CHUNK_BUDGET_MS) break;
    }
    options.onProgress?.(done, ticks);
    if (done < ticks) await yieldToUI();
  }

  const simulationMs = Date.now() - started;

  const positions = new Float32Array(nodeCount * 3);
  for (let i = 0; i < nodeCount; i += 1) {
    positions[i * 3] = finiteOrZero(simNodes[i].x);
    positions[i * 3 + 1] = finiteOrZero(simNodes[i].y);
    positions[i * 3 + 2] = finiteOrZero(simNodes[i].z);
  }

  return {
    positions,
    links: simLinks,
    boundingRadius: boundingRadius(positions),
    simulationMs,
    ticks: done,
    nodeCount,
    truncated,
  };
}
