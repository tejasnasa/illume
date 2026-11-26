/**
 * Interactive 3D dependency graph with search and reading-order tour.
 * @module GraphClient
 */
"use client";

import Graph from "@/types/graph";
import Guide from "@/types/guide";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import GraphCard, { InspectedNode, Neighbour } from "./ui/GraphCard";

// `dynamic` erases the component's node/link generics; restore them so the
// accessors below are checked against this graph's own node shape.
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
}) as unknown as typeof import("react-force-graph-3d").default;

type GraphNode = Graph["nodes"][number] & { complexity?: number };
type GraphLink = Graph["links"][number];

/** The library's default `nodeRelSize`; node radius is `cbrt(val) * this`. */
const NODE_REL_SIZE = 4;

/** The smallest a selection or search bracket is drawn, in screen pixels. */
const BRACKET_MIN_PX = 28;

/** How long the tour lingers on each file while playing. */
const TOUR_STEP_MS = 4000;

const COLORS = {
  critical: "#ef4444",
  caution: "#facc15",
  safe: "#22c55e",
  selected: "#0078ff",
  match: "#a855f7",
  bracket: "#f6339a",
} as const;

const LEGEND = [
  { label: "Critical", color: COLORS.critical },
  { label: "Caution", color: COLORS.caution },
  { label: "Safe", color: COLORS.safe },
  { label: "Selected", color: COLORS.selected },
  { label: "Search match", color: COLORS.match },
];

/**
 * Node size from lines of code, floored at 10 so an empty file stays visible.
 *
 * @param node - A graph node.
 * @returns The library's `nodeVal`.
 */
export function nodeValue(node: { loc?: number }): number {
  return Math.sqrt(node.loc || 10) * 0.5;
}

/**
 * Reads a link endpoint's id. The library replaces the string ids in the
 * payload with node objects once the simulation starts, so both shapes occur.
 *
 * @param end - The link's `source` or `target`.
 * @returns The endpoint node's id.
 */
function endId(end: unknown): string {
  if (end && typeof end === "object" && "id" in end) {
    return String((end as { id: unknown }).id);
  }
  return String(end);
}

const bracketTextures = new Map<string, THREE.CanvasTexture>();

/**
 * The pixel corner-bracket texture drawn around the selected node and around
 * search matches, built once per colour and shared. Nearest-neighbour
 * filtering keeps its edges hard at any zoom, matching the rest of the pixel
 * interface.
 *
 * @param color - The brackets' colour.
 * @returns The shared texture for that colour.
 */
function getBracketTexture(color: string): THREE.CanvasTexture {
  const cached = bracketTextures.get(color);
  if (cached) return cached;
  const size = 64;
  const arm = 18;
  const th = 5;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.fillStyle = color;
    const far = size - th;
    const reach = size - arm;
    ctx.fillRect(0, 0, arm, th);
    ctx.fillRect(0, 0, th, arm);
    ctx.fillRect(reach, 0, arm, th);
    ctx.fillRect(far, 0, th, arm);
    ctx.fillRect(0, far, arm, th);
    ctx.fillRect(0, reach, th, arm);
    ctx.fillRect(reach, far, arm, th);
    ctx.fillRect(far, reach, th, arm);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  bracketTextures.set(color, texture);
  return texture;
}

/**
 * A corner-bracket sprite sized to frame a node. It ignores depth, so it
 * stays visible through any node in front.
 *
 * @param node - The node to frame.
 * @param color - The brackets' colour.
 * @returns The sprite and its resting scale.
 */
function bracketSprite(node: { loc?: number }, color: string) {
  const radius = Math.cbrt(nodeValue(node)) * NODE_REL_SIZE;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: getBracketTexture(color),
      transparent: true,
      depthTest: false,
      depthWrite: false,
    }),
  );
  const base = (radius + 5) * 2;
  sprite.scale.setScalar(base);
  sprite.renderOrder = 1000;
  return { sprite, base };
}

/**
 * Renders the explorable dependency graph and its detail card.
 *
 * The simulation, sizing, link styling and particles are the library's
 * defaults as tuned for this view; the camera never moves on its own, so
 * selecting a node (by click, by the tour or from the inspector) only
 * recolours it, brightens its links and frames it in pink corner brackets.
 * Search matches are framed the same way in purple, so both read as one
 * kind of mark. The brackets ignore depth, so they stay visible through any
 * node in front.
 *
 * @param graphData - Nodes and links for the force-graph canvas.
 * @param currentLevel - Active granularity ("file" or "symbol").
 * @param repoId - Repository number used for level-change navigation.
 * @param github_url - Repository URL for source links in the detail card.
 * @param commitSha - Repository's ingested commit, pinned in source links.
 * @param branch - Repository's ingested branch, used when the commit is missing.
 * @param guide - Guide with reading order and per-file annotations.
 * @returns Full-viewport graph view with search, tour, legend and inspector.
 */
export default function GraphClient({
  graphData,
  currentLevel,
  repoId,
  github_url,
  commitSha,
  branch,
  guide,
}: {
  graphData: Graph;
  guide: Guide | null;
  currentLevel: string;
  repoId: string;
  github_url: string;
  commitSha?: string | null;
  branch?: string | null;
}) {
  const router = useRouter();
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [pageIndex, setPageIndex] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  /** Every bracket on screen, with its resting world size and whether it pulses. */
  const bracketsRef = useRef(
    new Map<THREE.Sprite, { base: number; pulse: boolean }>(),
  );
  const animFrameRef = useRef<number>(0);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null);

  const isFile = currentLevel === "file";
  const query = searchQuery.trim().toLowerCase();

  /**
   * Checks whether a node matches the current search text.
   *
   * @param node - Graph node with label/path fields.
   * @returns True when the label or path contains the query.
   */
  const isMatch = (node: GraphNode) =>
    !!query &&
    (!!node.label?.toLowerCase().includes(query) ||
      !!node.path?.toLowerCase().includes(query));

  const matchCount = query
    ? graphData.nodes.filter((n) => isMatch(n)).length
    : 0;

  const { byId, byPath } = useMemo(
    () => ({
      byId: new Map(graphData.nodes.map((n) => [n.id, n as GraphNode])),
      byPath: new Map(graphData.nodes.map((n) => [n.path, n as GraphNode])),
    }),
    [graphData],
  );

  /**
   * Sizes every bracket each frame and pulses the selected one, until unmounted.
   *
   * A bracket is never drawn smaller than `BRACKET_MIN_PX` on screen: its scale
   * is the larger of the node's own size and that many pixels' worth of world
   * units at its distance from the camera. Zooming out therefore leaves the
   * brackets the same size on screen, while zooming in still lets them grow
   * to frame a large node.
   */
  useEffect(() => {
    const at = new THREE.Vector3();
    const animate = () => {
      const brackets = bracketsRef.current;
      const graph = graphRef.current;
      const camera = graph?.camera?.() as THREE.PerspectiveCamera | undefined;
      const height = graph?.renderer?.()?.domElement?.clientHeight as
        number | undefined;
      // A stepped breath rather than a smooth one, like the rest of the UI.
      const step = Math.round(Math.sin(performance.now() / 333));
      brackets.forEach(({ base, pulse }, sprite) => {
        // A rebuilt node object leaves its old bracket detached; forget it.
        if (!sprite.parent?.parent) {
          brackets.delete(sprite);
          return;
        }
        let size = base;
        if (camera && height) {
          const distance = camera.position.distanceTo(
            sprite.getWorldPosition(at),
          );
          const perPixel =
            (2 *
              distance *
              Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) /
            height;
          size = Math.max(base, BRACKET_MIN_PX * perPixel);
        }
        sprite.scale.setScalar(pulse ? size * (1 + step * 0.06) : size);
      });
      animFrameRef.current = requestAnimationFrame(animate);
    };
    animFrameRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, []);

  /** Rebuilds the node objects when the query changes, so the match brackets follow it. */
  useEffect(() => {
    graphRef.current?.refresh?.();
  }, [searchQuery]);

  const readingOrder = useMemo(() => guide?.reading_order ?? [], [guide]);

  /** Guide reading order resolved to graph nodes, in position order. */
  const orderedNodes = useMemo(
    () =>
      [...readingOrder]
        .sort((a, b) => a.position - b.position)
        .map((entry) => byPath.get(entry.file_path))
        .filter((n): n is GraphNode => !!n),
    [readingOrder, byPath],
  );

  /** Reading-order entries keyed by file path. */
  const readingOrderMap = useMemo(
    () => new Map(readingOrder.map((entry) => [entry.file_path, entry])),
    [readingOrder],
  );

  /**
   * Selects a node and syncs the tour position to it.
   *
   * @param node - The node to select, or null to clear.
   */
  const select = (node: GraphNode | null) => {
    setSelectedNode(node);
    if (!node) {
      setPageIndex(null);
      setPlaying(false);
      return;
    }
    const idx = orderedNodes.findIndex((n) => n.path === node.path);
    setPageIndex(idx === -1 ? null : idx);
  };

  /**
   * Selects the tour node at the given reading-order index, wrapping round.
   *
   * @param index - Position in the ordered node list.
   */
  const navigateToPage = (index: number) => {
    if (orderedNodes.length === 0) return;
    const wrapped =
      ((index % orderedNodes.length) + orderedNodes.length) %
      orderedNodes.length;
    setPageIndex(wrapped);
    setSelectedNode(orderedNodes[wrapped]);
  };

  /** Advances the tour on a timer while it is playing. */
  useEffect(() => {
    if (!playing || orderedNodes.length === 0) return;
    const timer = window.setInterval(() => {
      setPageIndex((current) => {
        const next = current === null ? 0 : (current + 1) % orderedNodes.length;
        setSelectedNode(orderedNodes[next]);
        return next;
      });
    }, TOUR_STEP_MS);
    return () => window.clearInterval(timer);
  }, [playing, orderedNodes]);

  /** Starts or pauses the tour, starting from the first file if none is open. */
  const togglePlay = () => {
    if (!playing && pageIndex === null) navigateToPage(0);
    setPlaying((p) => !p);
  };

  /**
   * Switches graph granularity via a route change with a loading veil.
   *
   * @param level - Target granularity ("file" or "symbol").
   */
  const handleLevelChange = (level: string) => {
    if (level === currentLevel) return;
    select(null);
    setIsLoading(true);
    router.push(`/repo/${repoId}/graph?level=${level}`);
  };

  /** Clears the level-switch veil once fresh graph data arrives. */
  useEffect(() => {
    setIsLoading(false);
  }, [graphData]);

  /** Neighbours of the selected node, split by direction. */
  const neighbours = useMemo(() => {
    const importers: Neighbour[] = [];
    const imports: Neighbour[] = [];
    if (!selectedNode) return { importers, imports };
    const seenIn = new Set<string>();
    const seenOut = new Set<string>();
    for (const link of graphData.links as GraphLink[]) {
      if (link.type === "sibling") continue;
      const s = endId(link.source);
      const t = endId(link.target);
      if (s === t) continue;
      const text = (n: GraphNode) =>
        isFile ? n.path : `${n.label} · ${n.path}`;
      if (t === selectedNode.id && !seenIn.has(s)) {
        const n = byId.get(s);
        if (n) {
          seenIn.add(s);
          importers.push({ id: s, text: text(n) });
        }
      } else if (s === selectedNode.id && !seenOut.has(t)) {
        const n = byId.get(t);
        if (n) {
          seenOut.add(t);
          imports.push({ id: t, text: text(n) });
        }
      }
    }
    return { importers, imports };
  }, [selectedNode, graphData, byId, isFile]);

  if (!graphData) {
    return (
      <div className="flex h-[calc(100dvh-65px)] items-center justify-center p-6 text-center">
        <p className="font-pixel text-(--destructive) uppercase">
          Failed to load graph data
        </p>
      </div>
    );
  }

  const tourEntry =
    pageIndex !== null
      ? readingOrderMap.get(orderedNodes[pageIndex]?.path)
      : undefined;
  const selectedEntry = selectedNode
    ? readingOrderMap.get(selectedNode.path)
    : undefined;

  const isIncident = (link: GraphLink) =>
    !!selectedNode &&
    (endId(link.source) === selectedNode.id ||
      endId(link.target) === selectedNode.id);

  const panelClass =
    "panel flex flex-col gap-3 bg-(--card)/90 p-3.5 backdrop-blur-sm";
  const levelButton = (level: string, label: string) => (
    <button
      type="button"
      onClick={() => handleLevelChange(level)}
      aria-pressed={currentLevel === level}
      className={`flex-1 p-2 font-pixel text-xs tracking-[0.08em] uppercase transition-colors hover:cursor-pointer ${
        currentLevel === level
          ? "bg-(--muted) text-(--foreground)"
          : "text-(--subtle-foreground) hover:text-(--foreground)"
      }`}
    >
      {label}
    </button>
  );

  return (
    <main className="relative h-[calc(100dvh-106px)] min-h-[560px] w-full overflow-hidden bg-[radial-gradient(ellipse_at_55%_45%,#0092b81a,transparent_60%),#060608] md:h-[calc(100dvh-65px)]">
      <h1 className="sr-only">Dependency graph</h1>

      <section className="absolute inset-0 cursor-move">
        <ForceGraph3D
          ref={graphRef}
          graphData={graphData}
          nodeLabel={(node: GraphNode) =>
            `${node.label} (${node.criticality || "safe"})`
          }
          nodeVal={nodeValue}
          nodeColor={(node: GraphNode) => {
            if (isMatch(node)) return COLORS.match;
            if (node.id === selectedNode?.id) return COLORS.selected;
            if (node.criticality === "critical") return COLORS.critical;
            if (node.criticality === "caution") return COLORS.caution;
            return COLORS.safe;
          }}
          linkWidth={(link: GraphLink) => (isIncident(link) ? 2 : 1)}
          linkColor={(link: GraphLink) =>
            isIncident(link) ? "rgba(0,120,255,0.7)" : "rgba(255,255,255,0.3)"
          }
          backgroundColor="#00000000"
          linkDirectionalParticles={1}
          linkDirectionalParticleSpeed={0.005}
          nodeOpacity={0.9}
          nodeResolution={12}
          linkOpacity={1}
          onNodeClick={(node: GraphNode) => select(node)}
          onBackgroundClick={() => select(null)}
          nodeThreeObject={(node: GraphNode) => {
            const group = new THREE.Group();

            // The selection's own pulsing brackets take precedence over a match's.
            if (isMatch(node) && node.id !== selectedNode?.id) {
              const { sprite, base } = bracketSprite(node, COLORS.match);
              group.add(sprite);
              bracketsRef.current.set(sprite, { base, pulse: false });
            }

            if (node.id === selectedNode?.id) {
              const { sprite, base } = bracketSprite(node, COLORS.bracket);
              group.add(sprite);
              bracketsRef.current.set(sprite, { base, pulse: true });
            }

            return group;
          }}
          nodeThreeObjectExtend={true}
        />
      </section>

      {isLoading && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/60">
          <span className="blink font-pixel text-xs tracking-[0.12em] text-(--muted-foreground) uppercase">
            Loading graph
          </span>
        </div>
      )}

      <div className="absolute top-5 left-5 z-10 flex w-[min(300px,calc(100%-40px))] flex-col gap-3">
        <div className={panelClass}>
          <label className="relative block">
            <span
              aria-hidden="true"
              className="absolute top-1/2 left-3 -translate-y-1/2 font-pixel text-sm text-(--faint-foreground)"
            >
              ⌕
            </span>
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={isFile ? "Search files" : "Search symbols"}
              aria-label={isFile ? "Search files" : "Search symbols"}
              className="w-full rounded-sm border border-(--border) bg-(--background) py-2.5 pr-3 pl-8.5 text-sm outline-none focus:border-(--accent)"
            />
          </label>
          {query && (
            <span
              role="status"
              className="font-pixel text-[11px] tracking-[0.08em] text-(--match) uppercase"
            >
              {matchCount === 1 ? "1 match" : `${matchCount} matches`}
            </span>
          )}
          <div
            role="group"
            aria-label="Level"
            className="flex divide-x divide-(--border) overflow-hidden rounded-sm border border-(--border)"
          >
            {levelButton("file", "Files")}
            {levelButton("symbol", "Symbols")}
          </div>
          <span className="font-pixel text-[11px] tracking-[0.08em] text-(--subtle-foreground) uppercase">
            {graphData.nodes.length.toLocaleString("en-US")}{" "}
            {isFile ? "files" : "symbols"} ·{" "}
            {graphData.links.length.toLocaleString("en-US")} edges
          </span>
        </div>

        {/* Hidden rather than disabled when there is no guide: the tour has
            nothing to walk, and an empty counter is not actionable. */}
        {isFile && orderedNodes.length > 0 && (
          <div className={panelClass}>
            <p className="eyebrow m-0 flex items-center justify-between gap-2">
              <span>Reading order tour</span>
              <span className="text-(--accent) tabular-nums">
                {pageIndex === null ? "—" : pageIndex + 1} /{" "}
                {orderedNodes.length}
              </span>
            </p>
            <span className="line-clamp-3 text-[13px] leading-normal text-zinc-400">
              {tourEntry?.annotation ??
                "Step through the files in the order a newcomer should read them."}
            </span>
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={() => navigateToPage((pageIndex ?? 0) - 1)}
                aria-label="Previous file"
                className="ghost rounded-sm border border-(--input) px-3 py-2 font-pixel text-zinc-300 hover:cursor-pointer"
              >
                ◀
              </button>
              <button
                type="button"
                onClick={togglePlay}
                aria-pressed={playing}
                className="cta flex-1 rounded-sm bg-(--primary) px-3 py-2 font-pixel text-xs tracking-[0.08em] text-(--primary-foreground) uppercase hover:cursor-pointer"
              >
                {playing ? "❚❚ Pause" : "▶ Play tour"}
              </button>
              <button
                type="button"
                onClick={() => navigateToPage((pageIndex ?? -1) + 1)}
                aria-label="Next file"
                className="ghost rounded-sm border border-(--input) px-3 py-2 font-pixel text-zinc-300 hover:cursor-pointer"
              >
                ▶
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="panel absolute bottom-5 left-5 z-10 hidden flex-wrap items-center gap-x-4 gap-y-2 bg-(--card)/90 px-3.5 py-3 sm:flex">
        {LEGEND.map(({ label, color }) => (
          <span
            key={label}
            className="flex items-center gap-1.5 font-pixel text-[11px] tracking-[0.08em] text-(--muted-foreground) uppercase"
          >
            <span className="h-2 w-2" style={{ background: color }} />
            {label}
          </span>
        ))}
      </div>

      <span className="absolute right-6 bottom-5.5 z-10 hidden font-pixel text-[11px] tracking-[0.1em] text-(--faint-foreground) uppercase lg:block">
        Drag to rotate · Scroll to zoom · Click a {isFile ? "file" : "symbol"}
      </span>

      {selectedNode && (
        <GraphCard
          key={selectedNode.id}
          selectedNode={selectedNode as InspectedNode}
          onClose={() => select(null)}
          onSelectNode={(id) => {
            const node = byId.get(id);
            if (node) select(node);
          }}
          importers={neighbours.importers}
          imports={neighbours.imports}
          currentLevel={currentLevel}
          repoNumber={repoId}
          github_url={github_url}
          commitSha={commitSha}
          branch={branch}
          annotation={isFile ? (selectedEntry?.annotation ?? null) : null}
          tourPosition={selectedEntry ? selectedEntry.position : null}
        />
      )}
    </main>
  );
}
