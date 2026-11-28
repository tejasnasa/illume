/**
 * The decorative constellation behind onboarding and sign-in.
 *
 * @module pixelConstellation
 *
 * A light take on the web client's pixel graph
 * (``client/src/lib/pixelGraph.ts``): a core, one hub per group on a
 * Fibonacci sphere, and the files of each group scattered on a shell around
 * their hub. The scene is built once; each frame only rotates it about the
 * vertical axis and projects it onto a coarse grid, which is cheap enough to
 * drive from a timer on a phone. Nothing here imports React.
 */

import { mulberry } from "@/lib/starfield";
import { THUMB_TINTS } from "@/lib/thumbLayout";

/** One point of the scene. */
export interface ConstellationNode {
  x: number;
  y: number;
  z: number;
  /** 2 for the core, 1 for a hub, 0 for a file. */
  kind: 0 | 1 | 2;
  color: string;
  /** Index into the node list of the node this one is wired to, or -1. */
  parent: number;
}

/** A built scene. */
export interface ConstellationScene {
  nodes: ConstellationNode[];
}

/** One projected, drawable square. */
export interface ProjectedPixel {
  x: number;
  y: number;
  size: number;
  color: string;
  opacity: number;
}

/** One projected edge. */
export interface ProjectedEdge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  opacity: number;
}

/** Depth of the perspective; larger is flatter. */
const DEPTH = 3.2;

/**
 * Build a scene.
 *
 * @param seed - Integer the scatter is seeded from.
 * @param groups - How many hubs.
 * @param filesPerGroup - How many files around each hub.
 * @returns The scene; a core only when either count is below one.
 */
export function buildConstellation(
  seed = 7,
  groups = 7,
  filesPerGroup = 14,
): ConstellationScene {
  const rnd = mulberry(seed);
  const nodes: ConstellationNode[] = [
    { x: 0, y: 0, z: 0, kind: 2, color: "#0078ff", parent: -1 },
  ];
  const g = Math.max(0, Math.floor(groups));
  const f = Math.max(0, Math.floor(filesPerGroup));
  for (let i = 0; i < g; i += 1) {
    // Fibonacci sphere: an even spread of hubs.
    const t = g === 1 ? 0.5 : i / (g - 1);
    const y = 1 - 2 * t;
    const ring = Math.sqrt(Math.max(0, 1 - y * y));
    const phi = i * Math.PI * (3 - Math.sqrt(5));
    const hub = {
      x: Math.cos(phi) * ring * 0.8,
      y: y * 0.8,
      z: Math.sin(phi) * ring * 0.8,
    };
    const color = THUMB_TINTS[i % THUMB_TINTS.length];
    const hubIndex = nodes.length;
    nodes.push({ ...hub, kind: 1, color, parent: 0 });
    for (let j = 0; j < f; j += 1) {
      const a = rnd() * Math.PI * 2;
      const b = Math.acos(2 * rnd() - 1);
      const r = 0.12 + rnd() * 0.22;
      nodes.push({
        x: hub.x + r * Math.sin(b) * Math.cos(a),
        y: hub.y + r * Math.cos(b),
        z: hub.z + r * Math.sin(b) * Math.sin(a),
        kind: 0,
        color,
        parent: hubIndex,
      });
    }
  }
  return { nodes };
}

/**
 * Rotate a scene and project it onto a grid.
 *
 * @param scene - The built scene.
 * @param angle - Rotation about the vertical axis, in radians.
 * @param width - Drawing width.
 * @param height - Drawing height.
 * @param cell - Side of one pixel; positions snap to it.
 * @returns Squares and edges, far to near; empty for a zero-sized box.
 */
export function projectConstellation(
  scene: ConstellationScene,
  angle: number,
  width: number,
  height: number,
  cell = 4,
): { pixels: ProjectedPixel[]; edges: ProjectedEdge[] } {
  if (!(width > 0) || !(height > 0)) return { pixels: [], edges: [] };
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const scale = Math.min(width, height) * 0.46;
  const snap = (v: number) => Math.round(v / cell) * cell;

  const placed = scene.nodes.map((node) => {
    const x = node.x * cos - node.z * sin;
    const z = node.x * sin + node.z * cos;
    const k = DEPTH / (DEPTH + z);
    return {
      node,
      z,
      sx: snap(width / 2 + x * k * scale),
      sy: snap(height / 2 + node.y * k * scale),
      near: Math.min(1, Math.max(0, (1 - z) / 2)),
      k,
    };
  });

  const edges: ProjectedEdge[] = [];
  for (const p of placed) {
    if (p.node.parent < 0) continue;
    const parent = placed[p.node.parent];
    edges.push({
      x1: parent.sx,
      y1: parent.sy,
      x2: p.sx,
      y2: p.sy,
      opacity: 0.06 + 0.14 * p.near,
    });
  }

  const pixels = [...placed]
    .sort((a, b) => b.z - a.z)
    .map((p) => ({
      x: p.sx,
      y: p.sy,
      size: p.node.kind === 2 ? cell * 3 : p.node.kind === 1 ? cell * 2 : cell,
      color: p.node.color,
      opacity: 0.35 + 0.65 * p.near,
    }));
  return { pixels, edges };
}
