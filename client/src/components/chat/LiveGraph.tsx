/**
 * Full-viewport 3D dependency graph that follows an agent run.
 *
 * Atmosphere rather than a tool: it takes no pointer input, lights the files
 * the agent touches, glows the ones its current call is looking at, runs
 * particles along the edge it just followed, and eases the camera towards each
 * tool call. Loaded only on wide screens, since it brings Three.js with it.
 *
 * Node appearance is animated imperatively from one animation frame loop
 * rather than through the engine's colour props: changing those makes the
 * engine rebuild every node, which on a run that lights files ten times a
 * second reads as flicker and costs a frame each time.
 * @module LiveGraph
 */
"use client";

import {
  CITED_COLOR,
  CURRENT_COLOR,
  IDLE_COLOR,
  LINK_IDLE_COLOR,
  LINK_LIT_COLOR,
  MAIN_COLOR,
} from "@/lib/agent/palette";
import type { Highlight } from "@/lib/agent/reducer";
import type Graph from "@/types/graph";
import { useReducedMotion } from "motion/react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

/** The slice of the force-graph instance this component drives. */
interface GraphHandle {
  cameraPosition: (
    position?: { x: number; y: number; z: number },
    lookAt?: { x: number; y: number; z: number },
    ms?: number,
  ) => { x: number; y: number; z: number };
  camera?: () => { fov: number };
  d3Force: (name: string) => {
    strength?: (value: number) => void;
    distance?: (value: number) => void;
  } | null;
}

// The library's generic accessor types are wider than the plain callbacks used
// here, so the component is given a looser props shape.
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
}) as unknown as React.ComponentType<
  Record<string, unknown> & { ref?: React.Ref<GraphHandle> }
>;

/** How often run state is sampled; node events arrive far faster than this. */
const BATCH_MS = 100;
/** Radians per frame of the idle orbit. */
const ORBIT_SPEED = 0.0009;
const CAMERA_EASE_MS = 1400;
const RETURN_EASE_MS = 1800;
/** Ticks after which the layout has spread enough to frame it. */
const FIT_AFTER_TICKS = 60;
/** Per-frame share of the distance to a node's target look that is covered. */
const EASE = 0.12;

const IDLE_OPACITY = 0.75;
const LIT_OPACITY = 1;

/** What the canvas shows, sampled from the run at most ten times a second. */
interface View {
  highlight: Highlight;
  pulsePath: string | null;
  laneColors: Record<string, string>;
  live: boolean;
}

interface Pose {
  center: { x: number; y: number; z: number };
  position: { x: number; y: number; z: number };
}

interface GraphNode {
  id: string;
  path: string;
  loc: number;
  x?: number;
  y?: number;
  z?: number;
}

interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
}

/** The objects behind one node, and the look it is easing towards. */
interface Visual {
  core: THREE.Mesh<THREE.SphereGeometry, THREE.MeshLambertMaterial>;
  halo: THREE.Sprite;
  radius: number;
  color: THREE.Color;
  opacity: number;
  scale: number;
  haloOpacity: number;
}

/** What each node should look like right now. */
interface Target {
  color: string;
  opacity: number;
  scale: number;
  halo: number;
}

/** A soft round glow texture, shared by every halo. */
function glowTexture(): THREE.Texture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const half = size / 2;
    const gradient = ctx.createRadialGradient(half, half, 0, half, half, half);
    gradient.addColorStop(0, "rgba(255,255,255,0.9)");
    gradient.addColorStop(0.25, "rgba(255,255,255,0.35)");
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);
  }
  return new THREE.CanvasTexture(canvas);
}

const endpointId = (end: string | GraphNode) =>
  typeof end === "string" ? end : end.id;

const particleColor = () => LINK_LIT_COLOR;

const pairKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);

// Layout and sizing match the ambient graph on the other repository pages, so
// the chat's graph looks the same at rest and differs only in what it lights up.
const CHARGE_STRENGTH = -250;
const LINK_DISTANCE = 200;
const NODE_REL_SIZE = 4;

const nodeRadius = (loc: number) => Math.cbrt(Math.max(loc || 10, 10)) * NODE_REL_SIZE;

/**
 * Renders the live graph behind the conversation.
 *
 * @param graph - File-level graph from the repository layout.
 * @param highlight - Which files the run touched, is touching, and cited.
 * @param laneColors - Hex colour per worker lane id.
 * @param live - Whether a run is in progress; the camera orbits only when not.
 * @param pulsePath - A file to pulse, as while its citation chip is hovered.
 * @returns A fixed canvas that ignores the pointer.
 */
export default function LiveGraph({
  graph,
  highlight,
  laneColors,
  live,
  pulsePath,
}: {
  graph: Graph;
  highlight: Highlight;
  laneColors: Record<string, string>;
  live: boolean;
  pulsePath: string | null;
}) {
  const reduced = useReducedMotion();
  const fgRef = useRef<GraphHandle | null>(null);
  const frameObserver = useRef<ResizeObserver | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [revealed, setRevealed] = useState(false);
  const overview = useRef<Pose | null>(null);
  const ticks = useRef(0);
  const tweenUntil = useRef(0);
  const wasLive = useRef(false);
  const lastFocusSeq = useRef(0);
  const visuals = useRef<Map<string, Visual>>(new Map());
  const texture = useRef<THREE.Texture | null>(null);

  // Copies, because the engine writes positions and resolves link endpoints in place.
  const data = useMemo(
    () => ({
      nodes: graph.nodes.map((node) => ({
        id: node.id,
        path: node.path,
        loc: node.loc,
      })) as GraphNode[],
      // Another engine may already have swapped these ids for its own node
      // objects, so read the id back rather than copying the reference.
      links: graph.links.map((link) => ({
        source: endpointId(link.source as string | GraphNode),
        target: endpointId(link.target as string | GraphNode),
      })) as GraphLink[],
    }),
    [graph],
  );

  const idByPath = useMemo(() => {
    const map = new Map<string, string>();
    for (const node of data.nodes) map.set(node.path, node.id);
    return map;
  }, [data]);

  // Latest inputs live in a ref; a timer copies them into state in batches.
  const latest = useRef<View>({ highlight, pulsePath, laneColors, live });
  latest.current = { highlight, pulsePath, laneColors, live };
  const [view, setView] = useState<View>(latest.current);
  useEffect(() => {
    const timer = setInterval(() => {
      const next = latest.current;
      setView((current) =>
        current.highlight === next.highlight &&
        current.pulsePath === next.pulsePath &&
        current.laneColors === next.laneColors &&
        current.live === next.live
          ? current
          : next,
      );
    }, BATCH_MS);
    return () => clearInterval(timer);
  }, []);

  const derived = useMemo(() => {
    const touched = new Set<string>();
    const current = new Set<string>();
    const cited = new Set<string>();
    const colorOfId = new Map<string, string>();
    for (const path of view.highlight.touched) {
      const id = idByPath.get(path);
      if (!id) continue;
      touched.add(id);
      const lane = view.highlight.laneOf[path];
      colorOfId.set(
        id,
        (lane != null ? view.laneColors[lane] : undefined) ?? MAIN_COLOR,
      );
    }
    for (const path of view.highlight.current) {
      const id = idByPath.get(path);
      if (id) current.add(id);
    }
    for (const path of view.highlight.cited) {
      const id = idByPath.get(path);
      if (id) cited.add(id);
    }
    const pulse = view.pulsePath ? (idByPath.get(view.pulsePath) ?? null) : null;

    const followed = new Set<string>();
    for (const [from, to] of view.highlight.edges.slice(-6)) {
      const a = idByPath.get(from);
      const b = idByPath.get(to);
      if (a && b) followed.add(pairKey(a, b));
    }
    return { touched, current, cited, colorOfId, pulse, followed };
  }, [view, idByPath]);

  // The frame loop reads the newest targets from here.
  const targetsRef = useRef<(id: string) => Target>(() => ({
    color: IDLE_COLOR,
    opacity: IDLE_OPACITY,
    scale: 1,
    halo: 0,
  }));
  targetsRef.current = (id: string): Target => {
    if (derived.pulse === id) {
      return { color: CURRENT_COLOR, opacity: 1, scale: 1.9, halo: 1 };
    }
    if (view.live && derived.current.has(id)) {
      return {
        color: derived.colorOfId.get(id) ?? CURRENT_COLOR,
        opacity: 1,
        scale: 1.7,
        halo: 1,
      };
    }
    if (!view.live && derived.cited.has(id)) {
      return { color: CITED_COLOR, opacity: 1, scale: 1.5, halo: 0.7 };
    }
    if (derived.touched.has(id)) {
      return {
        color: derived.colorOfId.get(id) ?? MAIN_COLOR,
        opacity: LIT_OPACITY,
        scale: 1.4,
        halo: view.live ? 0.4 : 0.2,
      };
    }
    return { color: IDLE_COLOR, opacity: IDLE_OPACITY, scale: 1, halo: 0 };
  };

  // Stable, so the engine builds each node once; the frame loop restyles it.
  const nodeObject = useCallback((node: GraphNode) => {
    texture.current ??= glowTexture();
    const radius = nodeRadius(node.loc);
    const core = new THREE.Mesh(
      new THREE.SphereGeometry(radius, 14, 14),
      new THREE.MeshLambertMaterial({
        color: IDLE_COLOR,
        transparent: true,
        opacity: IDLE_OPACITY,
      }),
    );
    const halo = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: texture.current,
        color: IDLE_COLOR,
        transparent: true,
        opacity: 0,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    );
    halo.visible = false;
    const group = new THREE.Group();
    group.add(core);
    group.add(halo);
    visuals.current.set(node.id, {
      core,
      halo,
      radius,
      color: new THREE.Color(IDLE_COLOR),
      opacity: IDLE_OPACITY,
      scale: 1,
      haloOpacity: 0,
    });
    return group;
  }, []);

  // Link colour and particles change only when the sets behind them do, so the
  // engine restyles links rarely rather than on every sample.
  const touchedKey = useMemo(
    () => [...derived.touched].sort().join(","),
    [derived.touched],
  );
  const linkColor = useMemo(() => {
    const touched = new Set(touchedKey ? touchedKey.split(",") : []);
    return (link: GraphLink) =>
      touched.has(endpointId(link.source)) && touched.has(endpointId(link.target))
        ? LINK_LIT_COLOR
        : LINK_IDLE_COLOR;
  }, [touchedKey]);
  // Thin lines at rest, as on the other pages; a trail the run walked stands out.
  const linkWidth = useMemo(() => {
    const touched = new Set(touchedKey ? touchedKey.split(",") : []);
    return (link: GraphLink) =>
      touched.has(endpointId(link.source)) && touched.has(endpointId(link.target)) ? 1.2 : 0.5;
  }, [touchedKey]);

  const followedKey = useMemo(
    () => [...derived.followed].sort().join(","),
    [derived.followed],
  );
  const particles = useMemo(() => {
    const followed = new Set(followedKey ? followedKey.split(",") : []);
    return (link: GraphLink) =>
      followed.has(pairKey(endpointId(link.source), endpointId(link.target)))
        ? 3
        : 0;
  }, [followedKey]);

  const frameRef = useCallback((node: HTMLDivElement | null) => {
    frameObserver.current?.disconnect();
    frameObserver.current = null;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((prev) =>
        prev.width === width && prev.height === height ? prev : { width, height },
      );
    });
    observer.observe(node);
    frameObserver.current = observer;
  }, []);

  /**
   * Frames the cloud from slightly above, and remembers that pose.
   *
   * The distance frames the 85th-percentile node, so a few outliers may run
   * past the edges and the graph fills the screen behind the chat, but the
   * camera always stays outside the cloud.
   */
  const fitOverview = useCallback(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const placed = data.nodes.filter((node) => node.x !== undefined);
    if (placed.length === 0) return;
    let cx = 0;
    let cy = 0;
    let cz = 0;
    for (const node of placed) {
      cx += node.x as number;
      cy += node.y as number;
      cz += node.z as number;
    }
    cx /= placed.length;
    cy /= placed.length;
    cz /= placed.length;
    // How far each node's edge reaches from the centre.
    const reach = placed
      .map(
        (node) =>
          Math.hypot(
            (node.x as number) - cx,
            (node.y as number) - cy,
            (node.z as number) - cz,
          ) + nodeRadius(node.loc),
      )
      .sort((a, b) => a - b);
    // Framed on the median file, like the ambient graph on the other pages:
    // the dense middle fills the screen and the outer files run past its edges.
    const radius = Math.max(reach[Math.floor((reach.length - 1) * 0.5)] ?? 1, 60);
    const fov = fg.camera?.()?.fov ?? 40;
    const halfVertical = (fov * Math.PI) / 360;
    const aspect = size.width > 0 && size.height > 0 ? size.width / size.height : 1;
    const halfHorizontal = Math.atan(Math.tan(halfVertical) * aspect);
    const distance = radius / Math.tan(Math.min(halfVertical, halfHorizontal));
    const pose: Pose = {
      center: { x: cx, y: cy, z: cz },
      position: { x: cx, y: cy + distance * 0.25, z: cz + distance },
    };
    overview.current = pose;
    if (!latest.current.live && Date.now() > tweenUntil.current) {
      fg.cameraPosition(pose.position, pose.center);
    }
    setRevealed(true);
  }, [data, size.width, size.height]);

  // One loop: ease every node towards its target look, breathe the halos, and
  // orbit while idle.
  useEffect(() => {
    let raf = 0;
    const scratch = new THREE.Color();
    const step = (time: number) => {
      const target = targetsRef.current;
      const wave = reduced ? 1 : 1 + 0.18 * Math.sin(time / 280);
      const ease = reduced ? 1 : EASE;
      for (const [id, visual] of visuals.current) {
        const want = target(id);
        scratch.set(want.color);
        visual.color.lerp(scratch, ease);
        visual.opacity += (want.opacity - visual.opacity) * ease;
        visual.scale += (want.scale - visual.scale) * ease;
        visual.haloOpacity += (want.halo - visual.haloOpacity) * ease;

        visual.core.material.color.copy(visual.color);
        visual.core.material.opacity = visual.opacity;
        visual.core.scale.setScalar(visual.scale);

        const glowing = visual.haloOpacity > 0.02;
        visual.halo.visible = glowing;
        if (glowing) {
          const material = visual.halo.material as THREE.SpriteMaterial;
          material.color.copy(visual.color);
          material.opacity = visual.haloOpacity * 0.9;
          const size = visual.radius * 5 * visual.scale * (want.halo >= 1 ? wave : 1);
          visual.halo.scale.set(size, size, 1);
        }
      }

      const fg = fgRef.current;
      const pose = overview.current;
      if (
        !reduced &&
        fg &&
        pose &&
        !latest.current.live &&
        Date.now() > tweenUntil.current
      ) {
        const { x, y, z } = fg.cameraPosition();
        const dx = x - pose.center.x;
        const dz = z - pose.center.z;
        const cos = Math.cos(ORBIT_SPEED);
        const sin = Math.sin(ORBIT_SPEED);
        fg.cameraPosition(
          {
            x: pose.center.x + dx * cos - dz * sin,
            y,
            z: pose.center.z + dx * sin + dz * cos,
          },
          pose.center,
        );
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [reduced]);

  // A new graph means new node objects; the old ones are gone with it.
  useEffect(() => {
    const map = visuals.current;
    return () => {
      for (const visual of map.values()) {
        visual.core.geometry.dispose();
        visual.core.material.dispose();
        (visual.halo.material as THREE.SpriteMaterial).dispose();
      }
      map.clear();
    };
  }, [data]);

  // Ease towards the first file of each tool call, never per event.
  useEffect(() => {
    const fg = fgRef.current;
    const seq = view.highlight.focusSeq;
    if (!fg || seq === lastFocusSeq.current) return;
    lastFocusSeq.current = seq;
    const id = view.highlight.focus
      ? idByPath.get(view.highlight.focus)
      : undefined;
    const node = id ? data.nodes.find((n) => n.id === id) : undefined;
    const pose = overview.current;
    if (!node || node.x === undefined || !pose) return;
    // Shift the view towards the file and come a little closer, keeping the
    // overview's angle: it reads as the graph leaning in, not a fly-through.
    const lean = 0.7;
    const look = {
      x: pose.center.x + (node.x - pose.center.x) * lean,
      y: pose.center.y + ((node.y as number) - pose.center.y) * lean,
      z: pose.center.z + ((node.z as number) - pose.center.z) * lean,
    };
    const closer = 0.6;
    tweenUntil.current = Date.now() + CAMERA_EASE_MS + 100;
    fg.cameraPosition(
      {
        x: look.x + (pose.position.x - pose.center.x) * closer,
        y: look.y + (pose.position.y - pose.center.y) * closer,
        z: look.z + (pose.position.z - pose.center.z) * closer,
      },
      look,
      reduced ? 0 : CAMERA_EASE_MS,
    );
  }, [view.highlight.focusSeq, view.highlight.focus, idByPath, data, reduced]);

  // Back to the overview when the run ends.
  useEffect(() => {
    const fg = fgRef.current;
    if (wasLive.current && !view.live && fg && overview.current) {
      const pose = overview.current;
      tweenUntil.current = Date.now() + RETURN_EASE_MS + 100;
      fg.cameraPosition(pose.position, pose.center, reduced ? 0 : RETURN_EASE_MS);
    }
    wasLive.current = view.live;
  }, [view.live, reduced]);

  const measured = size.width > 0 && size.height > 0;

  return (
    <div
      ref={frameRef}
      aria-hidden="true"
      data-testid="live-graph"
      className={`pointer-events-none absolute inset-0 transition-opacity duration-1000 ${revealed ? "opacity-100" : "opacity-0"}`}
    >
      {measured && (
        <ForceGraph3D
          ref={fgRef}
          width={size.width}
          height={size.height}
          graphData={data}
          nodeLabel=""
          nodeThreeObject={nodeObject}
          nodeThreeObjectExtend={false}
          linkColor={linkColor}
          linkOpacity={0.35}
          linkWidth={linkWidth}
          linkDirectionalParticles={particles}
          linkDirectionalParticleSpeed={0.01}
          linkDirectionalParticleWidth={2.4}
          linkDirectionalParticleColor={particleColor}
          backgroundColor="#00000000"
          showNavInfo={false}
          enableNodeDrag={false}
          enableNavigationControls={false}
          enablePointerInteraction={false}
          cooldownTicks={240}
          d3AlphaDecay={0.0228}
          onEngineTick={() => {
            const fg = fgRef.current;
            if (!fg) return;
            if (ticks.current === 0) {
              fg.d3Force("charge")?.strength?.(CHARGE_STRENGTH);
              fg.d3Force("link")?.distance?.(LINK_DISTANCE);
            }
            ticks.current += 1;
            if (ticks.current === FIT_AFTER_TICKS) fitOverview();
          }}
          onEngineStop={fitOverview}
        />
      )}
    </div>
  );
}
