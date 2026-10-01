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

// Fallback for a contained graph whose simulation never reports itself settled.
const FIT_TIMEOUT_MS = 3000;

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
 *   the settled layout, so lowering this pulls the camera in and makes every
 *   node read larger. By far the strongest lever on apparent size.
 * @param chargeStrength - Node repulsion, negative. More negative pushes nodes
 *   further apart; combined with `linkDistance` it sets the overall spread.
 * @param nodeRelSize - Sphere size multiplier. Enlarges nodes without moving
 *   them, unlike the two above.
 * @param fitPadding - Camera margin in pixels when fitting a contained graph.
 *   A weak lever: it changes framing far more than zoom.
 * @param cooldownTicks - Simulation ticks before the engine halts. The engine
 *   otherwise runs to `cooldownTime` — fifteen seconds — and a contained graph
 *   is not revealed until it stops, so this is the main control on how long the
 *   hero takes to appear.
 * @param d3AlphaDecay - How quickly the simulation cools. Higher means the
 *   layout stops moving sooner, which matters because the reveal waits on the
 *   engine stopping.
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
  const fitted = useRef(false);
  const observerRef = useRef<ResizeObserver | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [settled, setSettled] = useState(false);

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

  // Pull the camera back until the graph fits its frame. Deliberately instant
  // and one-shot: an animated fit lands after the graph is already on screen
  // and reads as it shrinking mid-orbit. The frame stays transparent until
  // this has run, so the correction is never visible.
  const fitOnce = useCallback(() => {
    if (fitted.current) return;
    fitted.current = true;
    fgRef.current?.zoomToFit(0, fitPadding);
    setSettled(true);
  }, [fitPadding]);

  useEffect(() => {
    if (!contained) return;
    const timer = setTimeout(fitOnce, FIT_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [contained, fitOnce]);

  /** Slowly orbits the camera around the graph until unmounted. */
  useEffect(() => {
    let rafId: number;

    /** Advances the camera one frame along its circular orbit. */
    const spin = () => {
      const fg = fgRef.current;
      if (fg) {
        const { x, y, z } = fg.cameraPosition();
        const r = Math.sqrt(x * x + z * z);
        angleRef.current += ORBIT_SPEED;
        fg.cameraPosition({
          x: r * Math.sin(angleRef.current),
          y,
          z: r * Math.cos(angleRef.current),
        });
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
        contained && !settled ? "opacity-0" : "opacity-100"
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
            // Reapply whenever the tuning changes, so editing a value takes
            // effect without a remount. Reheating restarts the layout, which
            // invalidates the fit the camera is currently sitting at.
            const fg = fgRef.current;
            if (!fg) return;
            const key = `${linkDistance}:${chargeStrength}`;
            if (appliedForces.current === key) return;
            const isFirstApply = appliedForces.current === null;
            appliedForces.current = key;
            fg.d3Force("charge")?.strength(chargeStrength);
            fg.d3Force("link")?.distance(linkDistance);
            // Only restart the layout when the tuning actually changed. A
            // reheat on the first tick throws away the simulation the engine
            // has just begun, and the reveal is waiting on it finishing.
            if (!isFirstApply) {
              fg.d3ReheatSimulation();
              fitted.current = false;
            }
          }}
          onEngineStop={contained ? fitOnce : undefined}
        />
      )}
    </div>
  );
}
