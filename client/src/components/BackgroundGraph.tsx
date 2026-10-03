/**
 * Non-interactive ambient 3D force graph for page backgrounds.
 * @module BackgroundGraph
 */
"use client";
import Graph from "@/types/graph";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
});

const ORBIT_SPEED = 0.001; // radians per frame

// Slack left beyond the tightest fit, as a fraction, so the outermost sphere
// stops just short of the frame edge instead of touching it.
const FIT_MARGIN = 1.04;

// How many simulation ticks a contained graph keeps re-fitting for. The layout
// is only worth tracking while it is spreading; past that the camera is left
// alone, which also keeps a graph that never cools from fitting forever.
const FIT_TICKS = 240;

/**
 * Renders a slowly orbiting, non-interactive graph behind page content.
 *
 * @param graph - Graph payload to visualize; renders nothing when null.
 * @param variant - `"background"` pins the canvas behind the page; `"contained"`
 *   fills the nearest positioned ancestor instead.
 * @param nodeColor - Node colour. Must be a literal three.js can parse: the
 *   colour string reaches tinycolor, which understands neither `var()` nor
 *   `oklch()` and quietly returns black for anything it cannot read.
 * @param linkDistance - Node spacing in graph units. The camera is fitted to
 *   the live layout, so lowering this pulls the camera in and makes every node
 *   read larger. By far the strongest lever on apparent size.
 * @param chargeStrength - Node repulsion, negative. More negative pushes nodes
 *   further apart; combined with `linkDistance` it sets the overall spread.
 * @param nodeRelSize - Sphere size multiplier. Enlarges nodes without moving
 *   them, unlike the two above.
 * @param fitPadding - Camera margin in pixels when fitting a contained graph.
 *   A weak lever: it changes framing far more than zoom.
 * @param cooldownTicks - Simulation ticks before the engine halts, after which
 *   the layout stops moving. A contained graph is revealed on its first tick,
 *   so this no longer delays the hero appearing — it only bounds how long the
 *   page spends animating.
 * @param d3AlphaDecay - How quickly the simulation cools. Higher means the
 *   layout stops moving sooner.
 * @returns Background canvas, or null while graph is unavailable.
 */
export default function BackgroundGraph({
  graph,
  variant = "background",
  nodeColor = "rgb(59, 130, 246)",
  linkDistance = 200,
  chargeStrength = -250,
  nodeRelSize = 4,
  fitPadding = 40,
  cooldownTicks = Infinity,
  d3AlphaDecay = 0.0228,
}: {
  graph: Graph | null;
  variant?: "background" | "contained";
  nodeColor?: string;
  linkDistance?: number;
  chargeStrength?: number;
  nodeRelSize?: number;
  fitPadding?: number;
  cooldownTicks?: number;
  d3AlphaDecay?: number;
}) {
  const fgRef = useRef<any>(null);
  const angleRef = useRef(0);
  const appliedForces = useRef<string | null>(null);
  const fitTicks = useRef(0);
  const revealedRef = useRef(false);
  const centerRef = useRef({ x: 0, y: 0, z: 0 });
  const distanceRef = useRef(0);
  const observerRef = useRef<ResizeObserver | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [revealed, setRevealed] = useState(false);

  const contained = variant === "contained";

  // Stable identity: the force engine diffs this prop and would otherwise
  // rebuild every node on each render.
  const colorForNode = useCallback(() => nodeColor, [nodeColor]);

  // The engine sizes its canvas from the window unless told otherwise, so a
  // contained instance has to measure its own frame. A callback ref keeps the
  // observer attached only while the frame is mounted.
  const frameRef = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node || typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((prev) =>
        prev.width === width && prev.height === height
          ? prev
          : { width, height },
      );
    });
    observer.observe(node);
    observerRef.current = observer;
  }, []);

  // Places the camera as close as the graph allows without a node leaving the
  // frame. Instant rather than animated, because a tween would land after the
  // graph is already on screen and read as it shrinking mid-orbit. The frame
  // stays transparent until this has run, so the correction is never visible.
  //
  // The distance is solved from the nodes themselves rather than taken from
  // `zoomToFit`, whose axis-aligned box grows and shrinks with the orbit angle
  // and so leaves a graph sitting well inside the space it has.
  const fitToGraph = useCallback(() => {
    const fg = fgRef.current;
    const camera = fg?.camera?.();
    const nodes = graph?.nodes;
    if (!fg || !camera || !nodes?.length) return;

    // The engine positions the very node objects it was handed, so these read
    // back the live layout.
    const positioned = nodes as {
      x?: number;
      y?: number;
      z?: number;
      loc?: number;
    }[];
    let cx = 0,
      cy = 0,
      cz = 0,
      count = 0;
    for (const node of positioned) {
      if (node.x === undefined) continue;
      cx += node.x;
      cy += node.y as number;
      cz += node.z as number;
      count += 1;
    }
    if (!count) return;
    cx /= count;
    cy /= count;
    cz /= count;

    // Camera basis: `forward` runs from the camera to the cloud's centre.
    // Orbiting keeps the camera off the vertical, so it is never parallel to
    // the world up axis and `right` is always well defined.
    const pos = fg.cameraPosition();
    let fx = cx - pos.x,
      fy = cy - pos.y,
      fz = cz - pos.z;
    const viewDistance = Math.hypot(fx, fy, fz) || 1;
    fx /= viewDistance;
    fy /= viewDistance;
    fz /= viewDistance;
    let rx = -fz,
      rz = fx; // forward x up, up = (0, 1, 0)
    const rightLength = Math.hypot(rx, rz) || 1;
    rx /= rightLength;
    rz /= rightLength;
    const ux = -rz * fy,
      uy = rz * fx - rx * fz,
      uz = rx * fy; // right x forward

    // `fitPadding` is claimed off each edge of the frame before fitting.
    const paddedWidth = Math.max(size.width - fitPadding * 2, 1);
    const paddedHeight = Math.max(size.height - fitPadding * 2, 1);
    const tanVertical =
      Math.tan((camera.fov * Math.PI) / 360) * (paddedHeight / size.height);
    const tanHorizontal = tanVertical * (paddedWidth / paddedHeight);

    // Each node needs the camera at `along + lateral` to sit inside the frustum;
    // the largest of those is the distance that fits the whole cloud.
    let distance = 0;
    for (const node of positioned) {
      if (node.x === undefined) continue;
      const dx = node.x - cx,
        dy = (node.y as number) - cy,
        dz = (node.z as number) - cz;
      const radius = Math.cbrt(node.loc || 10) * nodeRelSize;
      const along = dx * fx + dy * fy + dz * fz;
      const lateral = Math.max(
        (Math.abs(dx * rx + dz * rz) + radius) / tanHorizontal,
        (Math.abs(dx * ux + dy * uy + dz * uz) + radius) / tanVertical,
      );
      distance = Math.max(distance, along + lateral);
    }
    distance *= FIT_MARGIN;

    const cameraY = cy - fy * distance;
    fg.cameraPosition(
      { x: cx - fx * distance, y: cameraY, z: cz - fz * distance },
      { x: cx, y: cy, z: cz },
    );
    centerRef.current = { x: cx, y: cy, z: cz };
    // The orbit holds the camera's height, so it travels on a circle whose
    // radius is the fitted distance less that height — otherwise it would sit
    // further from the cloud than the fit asked for.
    const height = cameraY - cy;
    distanceRef.current = Math.max(
      Math.sqrt(Math.max(distance * distance - height * height, 1)),
      1,
    );

    if (!revealedRef.current) {
      revealedRef.current = true;
      setRevealed(true);
    }
  }, [graph, nodeRelSize, fitPadding, size.width, size.height]);

  /** Slowly orbits the camera around the graph until unmounted. */
  useEffect(() => {
    let rafId: number;

    /** Advances the camera one frame along its circular orbit. */
    const spin = () => {
      const fg = fgRef.current;
      if (fg) {
        // The camera is aimed explicitly: its position is set one axis at a
        // time here, and the default aim point would otherwise pull an
        // off-centre cloud out of frame.
        const center = centerRef.current;
        const { x, y, z } = fg.cameraPosition();
        const r =
          distanceRef.current || Math.hypot(x - center.x, z - center.z) || 1;
        angleRef.current += ORBIT_SPEED;
        fg.cameraPosition(
          {
            x: center.x + r * Math.sin(angleRef.current),
            y,
            z: center.z + r * Math.cos(angleRef.current),
          },
          center,
        );
      }
      rafId = requestAnimationFrame(spin);
    };

    rafId = requestAnimationFrame(spin);
    return () => cancelAnimationFrame(rafId);
  }, []);

  if (!graph) return null;

  const measured = size.width > 0 && size.height > 0;

  return (
    <div
      ref={frameRef}
      className={`${contained ? "absolute inset-0" : "fixed inset-0 -z-10"} transition-opacity duration-300 ${
        contained && !revealed ? "opacity-0" : "opacity-100"
      }`}
    >
      {measured && (
        <ForceGraph3D
          ref={fgRef}
          width={size.width}
          height={size.height}
          graphData={graph}
          nodeLabel="label"
          nodeVal={(node: any) => node.loc || 10}
          nodeRelSize={nodeRelSize}
          cooldownTicks={cooldownTicks}
          d3AlphaDecay={d3AlphaDecay}
          linkDirectionalParticles={2}
          linkDirectionalParticleSpeed={0.005}
          linkWidth={0.5}
          backgroundColor="#00000000"
          nodeColor={colorForNode}
          enableNodeDrag={false}
          enableNavigationControls={false}
          enablePointerInteraction={false}
          showNavInfo={false}
          onEngineTick={() => {
            const fg = fgRef.current;
            if (!fg) return;
            // Track the layout while it spreads, so a contained graph fills its
            // frame from the first frame rather than only once it has settled.
            if (contained && fitTicks.current < FIT_TICKS) {
              fitTicks.current += 1;
              fitToGraph();
            }
            // Reapply the tuning whenever it changes, so editing a value takes
            // effect without a remount.
            const key = `${linkDistance}:${chargeStrength}`;
            if (appliedForces.current === key) return;
            const isFirstApply = appliedForces.current === null;
            appliedForces.current = key;
            fg.d3Force("charge")?.strength(chargeStrength);
            fg.d3Force("link")?.distance(linkDistance);
            // Only restart the layout when the tuning actually changed. A
            // reheat on the first tick throws away the simulation the engine
            // has just begun.
            if (!isFirstApply) {
              fg.d3ReheatSimulation();
              // The layout is moving again, so it is worth tracking again.
              fitTicks.current = 0;
            }
          }}
          onEngineStop={contained ? fitToGraph : undefined}
        />
      )}
    </div>
  );
}
