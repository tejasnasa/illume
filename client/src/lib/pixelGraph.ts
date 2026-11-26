/**
 * Scene building and drawing for the pixel constellation graph.
 *
 * A scene is a core node, one hub per directory and the files around each
 * hub, laid out on a sphere and drawn at a low resolution so every node and
 * edge snaps to a coarse pixel grid. Nothing here touches React; the
 * component in `components/PixelGraph.tsx` owns the canvas and the loop.
 * @module pixelGraph
 */
import type Graph from "@/types/graph";

/** RGB triples, as `"r,g,b"`, one per directory in turn. */
const TINTS = [
  "0,184,219",
  "246,51,154",
  "83,234,253",
  "0,146,184",
  "236,72,153",
  "0,184,219",
  "246,51,154",
  "83,234,253",
  "0,146,184",
];

/** The most directories a scene shows before smaller ones fold together. */
const MAX_GROUPS = 9;
/** The most files a scene built from a real graph keeps. */
const MAX_FILES = 2000;
/** The most real import edges a scene built from a real graph keeps. */
const MAX_LINKS = 3000;
/** Depth of the perspective; larger is flatter. */
const DEPTH = 3.2;
/** Alpha steps edges are batched into, so a frame strokes a few paths, not thousands. */
const ALPHA_STEPS = 6;

/** One point of the constellation, with the projection the last frame wrote. */
export interface PixelNode {
  x: number;
  y: number;
  z: number;
  /** 2 for the core, 1 for a directory hub, 0 for a file. */
  kind: 0 | 1 | 2;
  /** Full path of a file, or the directory of a hub. */
  label: string;
  /** The hub's last directory segment, with a trailing slash. */
  short: string;
  grp: number;
  /** A file's place in build order, or -1 for the core and hubs. */
  li: number;
  tint: string;
  /** Twinkle phase, 0 to 1. */
  ph: number;
  sz: number;
  // Written by every frame.
  sx: number;
  sy: number;
  k: number;
  z2: number;
  /** Nearness to the viewer, 0 (far) to 1 (near). */
  d: number;
  /** How lit the node is, 0 to 1. */
  g: number;
  /** Drawn size, in low-resolution pixels. */
  s: number;
}

/** An edge between two nodes, with the phase of the particle that runs along it. */
export type PixelEdge = [PixelNode, PixelNode, number];

/** A built constellation. */
export interface PixelScene {
  nodes: PixelNode[];
  edges: PixelEdge[];
  /** File nodes by repository path. */
  byPath: Map<string, PixelNode>;
}

/** A directory and the files under it, as the builder takes them. */
interface GroupSpec {
  dir: string;
  files: { path: string; size: number }[];
}

/** Shape options that differ between the scenes the pages use. */
interface ShapeOptions {
  seed: number;
  /** Whether nodes get a twinkle phase; the twinkle-free scenes skip the draw. */
  phase: boolean;
  /** Shell thickness the files sit in, beyond 0.8. */
  shell: number;
  /** Chance a file is chained to the one before it; 0 for real graphs. */
  chain: number;
  /** Random cross-directory edges to add when there are no real ones. */
  cross: number;
  coreSize: number;
  hubSize: number;
  coreLabel: string;
}

/**
 * A small, seeded, uniform generator, so a scene looks the same on every load.
 *
 * @param seed - Any integer.
 * @returns A function returning numbers in [0, 1).
 */
function mulberry(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A node with its per-frame fields zeroed. */
function node(
  fields: Pick<PixelNode, "x" | "y" | "z" | "kind" | "label" | "short" | "grp" | "tint" | "ph" | "sz">,
  li = -1,
): PixelNode {
  return { ...fields, li, sx: 0, sy: 0, k: 1, z2: 0, d: 0, g: 0, s: 1 };
}

/**
 * Lays groups out around a core: hubs on a Fibonacci sphere, files scattered
 * around their hub on an outer shell.
 *
 * @param groups - Directories in the order they are placed.
 * @param links - Real edges between file paths, or null to invent a few.
 * @param shape - Shape options.
 * @param fileSize - Maps a file's size hint and a random draw to its size.
 * @returns The scene.
 */
function buildScene(
  groups: GroupSpec[],
  links: [string, string][] | null,
  shape: ShapeOptions,
  fileSize: (size: number, rnd: () => number) => number,
): PixelScene {
  const rnd = mulberry(shape.seed);
  const nodes: PixelNode[] = [];
  const edges: PixelEdge[] = [];
  const leaves: PixelNode[] = [];
  const byPath = new Map<string, PixelNode>();

  const core = node({
    x: 0,
    y: 0,
    z: 0,
    kind: 2,
    label: shape.coreLabel,
    short: "",
    grp: -1,
    tint: "250,250,250",
    ph: shape.phase ? rnd() : 0,
    sz: shape.coreSize,
  });
  nodes.push(core);

  const K = groups.length;
  groups.forEach((group, gi) => {
    const phi = Math.acos(1 - (2 * (gi + 0.5)) / K);
    const th = Math.PI * (1 + Math.sqrt(5)) * gi;
    const cx = Math.sin(phi) * Math.cos(th);
    const cy = Math.cos(phi);
    const cz = Math.sin(phi) * Math.sin(th);
    const parts = group.dir.split("/").filter(Boolean);
    const tint = TINTS[gi % TINTS.length];
    const hub = node({
      x: cx * 0.5,
      y: cy * 0.5,
      z: cz * 0.5,
      kind: 1,
      label: group.dir,
      short: `${parts.length ? parts[parts.length - 1] : "."}/`,
      grp: gi,
      tint,
      ph: shape.phase ? rnd() : 0,
      sz: shape.hubSize,
    });
    nodes.push(hub);
    edges.push([core, hub, rnd()]);

    let prev: PixelNode | null = null;
    for (const file of group.files) {
      const x = cx + (rnd() - 0.5) * 0.9;
      const y = cy + (rnd() - 0.5) * 0.9;
      const z = cz + (rnd() - 0.5) * 0.9;
      const length = Math.sqrt(x * x + y * y + z * z) || 1;
      const r = 0.8 + rnd() * shape.shell;
      const ph = shape.phase ? rnd() : 0;
      const leaf = node({
        x: (x / length) * r,
        y: (y / length) * r,
        z: (z / length) * r,
        kind: 0,
        label: file.path,
        short: "",
        grp: gi,
        tint,
        ph,
        sz: fileSize(file.size, rnd),
      }, leaves.length);
      nodes.push(leaf);
      leaves.push(leaf);
      byPath.set(file.path, leaf);
      edges.push([hub, leaf, rnd()]);
      if (prev && shape.chain > 0 && rnd() < shape.chain) edges.push([prev, leaf, rnd()]);
      prev = leaf;
    }
  });

  if (links) {
    for (const [from, to] of links) {
      const a = byPath.get(from);
      const b = byPath.get(to);
      if (a && b && a !== b) edges.push([a, b, rnd()]);
    }
  } else {
    for (let i = 0; i < shape.cross; i++) {
      const a = leaves[Math.floor(rnd() * leaves.length)];
      const b = leaves[Math.floor(rnd() * leaves.length)];
      if (a !== b && a.grp !== b.grp) edges.push([a, b, rnd()]);
    }
  }

  return { nodes, edges, byPath };
}

/** The files the landing hero shows: Illume's own layout, by directory. */
const HERO_GROUPS: [string, string[]][] = [
  ["server/app/services/", ["rag.py", "embedder.py", "scanner.py", "parser.py", "cloner.py", "criticality.py", "onboarding.py", "glossary_builder.py", "architecture_brief.py", "git_analyzer.py", "dependency_resolver.py", "import_resolver.py"]],
  ["server/app/api/v1/", ["chat.py", "graph.py", "repository.py", "auth.py", "guide.py", "glossary.py", "push.py"]],
  ["server/app/tasks/", ["ingest.py", "sync.py", "autoupdate.py", "_parallel.py"]],
  ["server/app/models/", ["repository.py", "file.py", "ast_symbol.py", "dependency.py", "embedding.py", "commit.py", "user.py", "chat_message.py"]],
  ["server/app/core/", ["config.py", "database.py", "security.py", "celery.py"]],
  ["client/src/components/", ["GraphClient.tsx", "Chat.tsx", "CitationCard.tsx", "RepoNavbar.tsx", "IngestFlow.tsx", "GitGraph.tsx", "SiteNavbar.tsx", "RepoSettings.tsx", "BackgroundGraph.tsx", "GlossarySearch.tsx"]],
  ["client/src/app/", ["page.tsx", "layout.tsx", "repo/[id]/page.tsx", "repo/[id]/graph/page.tsx", "repo/[id]/glossary/page.tsx", "docs/page.tsx"]],
  ["client/src/hooks/", ["useChat.ts", "useIngest.ts", "useRepoGraph.ts"]],
  ["mobile/src/", ["App.tsx", "api/chat.ts", "components/CitationCard.tsx", "screens/Graph.tsx", "screens/Repo.tsx"]],
];

/**
 * The landing hero's constellation: a hand-picked slice of Illume itself,
 * with labelled directories.
 *
 * @returns A fresh scene.
 */
export function heroScene(): PixelScene {
  return buildScene(
    HERO_GROUPS.map(([dir, files]) => ({
      dir,
      files: files.map((f) => ({ path: dir + f, size: 0 })),
    })),
    null,
    {
      seed: 23,
      phase: true,
      shell: 0.28,
      chain: 0.55,
      cross: 20,
      coreSize: 6,
      hubSize: 4.5,
      coreLabel: "server/app/main.py",
    },
    (_size, rnd) => 2 + rnd() * 2.6,
  );
}

/**
 * A small anonymous constellation for preview cards: seven directories of
 * seven files, with no names to show.
 *
 * @returns A fresh scene.
 */
export function sampleScene(): PixelScene {
  return buildScene(
    Array.from({ length: 7 }, (_, gi) => ({
      dir: `group-${gi}/`,
      files: Array.from({ length: 7 }, (_, j) => ({ path: `group-${gi}/${j}`, size: 0 })),
    })),
    null,
    {
      seed: 5,
      phase: false,
      shell: 0.25,
      chain: 0.5,
      cross: 12,
      coreSize: 5,
      hubSize: 3.6,
      coreLabel: "",
    },
    (_size, rnd) => 1.6 + rnd() * 2,
  );
}

/**
 * Picks how deep into each path a directory is cut, so a repository splits
 * into a handful of groups rather than one, or hundreds.
 *
 * @param dirs - Every file's directory, without a trailing slash.
 * @returns The prefix depth to group by.
 */
function groupDepth(dirs: string[]): number {
  let best = 1;
  let bestCount = 0;
  for (let depth = 1; depth <= 5; depth++) {
    const keys = new Set(dirs.map((d) => d.split("/").slice(0, depth).join("/")));
    // Deeper only helps while it adds groups and stays readable.
    if (keys.size > MAX_GROUPS + 3) break;
    if (keys.size > bestCount) {
      best = depth;
      bestCount = keys.size;
    }
    if (keys.size >= 5) break;
  }
  return best;
}

/**
 * Builds a constellation from a repository's file graph: a hub per directory
 * and its real import edges between files.
 *
 * @param graph - File-level graph payload.
 * @param seed - Layout seed; the same graph and seed give the same picture.
 * @returns The scene.
 */
export function sceneFromGraph(graph: Graph, seed = 23): PixelScene {
  // A very large repository keeps its most imported files.
  const files =
    graph.nodes.length > MAX_FILES
      ? [...graph.nodes].sort((a, b) => (b.fan_in ?? 0) - (a.fan_in ?? 0)).slice(0, MAX_FILES)
      : graph.nodes;

  const dirOf = (path: string) => {
    const slash = path.lastIndexOf("/");
    return slash > 0 ? path.slice(0, slash) : "";
  };
  const depth = groupDepth(files.map((f) => dirOf(f.path)));
  const buckets = new Map<string, GroupSpec>();
  for (const file of files) {
    const key = dirOf(file.path).split("/").slice(0, depth).join("/");
    const dir = key ? `${key}/` : "";
    let bucket = buckets.get(dir);
    if (!bucket) {
      bucket = { dir, files: [] };
      buckets.set(dir, bucket);
    }
    bucket.files.push({ path: file.path, size: file.loc || 10 });
  }

  // The largest directories keep their own hub; the rest share the last one.
  let groups = [...buckets.values()].sort((a, b) => b.files.length - a.files.length);
  if (groups.length > MAX_GROUPS) {
    const kept = groups.slice(0, MAX_GROUPS - 1);
    const rest = groups.slice(MAX_GROUPS - 1);
    kept.push({ dir: "other/", files: rest.flatMap((g) => g.files) });
    groups = kept;
  }
  for (const group of groups) group.files.sort((a, b) => a.path.localeCompare(b.path));

  const idToPath = new Map(files.map((f) => [f.id, f.path]));
  const links: [string, string][] = [];
  for (const link of graph.links) {
    // Another renderer may already have swapped the ids for node objects.
    const source = typeof link.source === "object" ? (link.source as { id: string }).id : link.source;
    const target = typeof link.target === "object" ? (link.target as { id: string }).id : link.target;
    const a = idToPath.get(source);
    const b = idToPath.get(target);
    if (a && b) links.push([a, b]);
    if (links.length >= MAX_LINKS) break;
  }

  // Busy scenes draw smaller files, so the shell does not turn into a wall.
  const shrink = files.length > 400 ? 0.6 : files.length > 150 ? 0.8 : 1;
  return buildScene(
    groups,
    links,
    {
      seed,
      phase: true,
      shell: 0.28,
      chain: 0,
      cross: 0,
      coreSize: 6,
      hubSize: 4.5,
      coreLabel: "",
    },
    (size, rnd) => (1.8 + Math.min(1, Math.log10(Math.max(size, 10)) / 3.3) * 2.4 + rnd() * 0.4) * shrink,
  );
}

/** How a caller restyles one file, as the chat does for files an agent touches. */
export interface NodeStyle {
  /** `"r,g,b"` colour. */
  tint: string;
  /** Halo strength, 0 to 1. */
  glow: number;
  /** Size multiplier. */
  scale?: number;
}

/** Everything one frame needs beyond the scene itself. */
export interface FrameInput {
  /** Milliseconds since the loop started. */
  t: number;
  yaw: number;
  pitch: number;
  /** Where the light sits, in low-resolution pixels, or null for none. */
  light: { x: number; y: number } | null;
  /** Low-resolution pixel size, in device pixels per pixel. */
  cell: number;
  dpr: number;
  /** Horizontal and vertical spread, as fractions of the frame. */
  spreadX: number;
  spreadY: number;
  /** Light radius, as a fraction of the smaller side. */
  lightRadius: number;
  /** Per-frame share of the way a node's glow moves to its target; 1 is instant. */
  glowEase: number;
  /** Whether to letter each directory hub. */
  hubLabels: boolean;
  /** Whether to box and name the file nearest the light. */
  focusLabel: boolean;
  /** Font family for the canvas text. */
  font: string;
  reduce: boolean;
  /** Restyles a file, or returns null to leave it as drawn. */
  style?: (n: PixelNode) => NodeStyle | null;
  /** A node to box and name regardless of the light. */
  pinned?: PixelNode | null;
  /** Fades files no style applies to, so the styled ones stand out. */
  dimUnstyled?: boolean;
  /**
   * How much of the scene has been found so far, as fractions: files shown,
   * and edges between files shown. Absent draws everything.
   */
  reveal?: { files: number; links: number };
  /** Picks out edges to run a bright particle along. */
  followed?: (a: PixelNode, b: PixelNode) => boolean;
}

/** Rounds an alpha into one of the batch steps. */
const step = (alpha: number) => Math.max(0, Math.min(ALPHA_STEPS, Math.round(alpha * ALPHA_STEPS)));

/**
 * Projects and draws one frame.
 *
 * @param canvas - The visible canvas, already sized to the device pixels.
 * @param off - A scratch canvas the frame is drawn into at low resolution.
 * @param scene - The constellation; its nodes' projection fields are rewritten.
 * @param f - The frame's camera, light and options.
 */
export function drawFrame(
  canvas: HTMLCanvasElement,
  off: HTMLCanvasElement,
  scene: PixelScene,
  f: FrameInput,
): void {
  const W = canvas.width;
  const H = canvas.height;
  const cell = f.cell;
  const lw = Math.ceil(W / cell);
  const lh = Math.ceil(H / cell);
  if (off.width !== lw || off.height !== lh) {
    off.width = lw;
    off.height = lh;
  }
  const o = off.getContext("2d");
  const ctx = canvas.getContext("2d");
  if (!o || !ctx) return;

  const { t } = f;
  const R = Math.min(lw, lh) * f.lightRadius;
  const Lx = f.light?.x ?? -1e6;
  const Ly = f.light?.y ?? -1e6;
  o.clearRect(0, 0, lw, lh);

  if (f.light && Lx > -R && Lx < lw + R && Ly > -R && Ly < lh + R) {
    const pool = o.createRadialGradient(Lx, Ly, 0, Lx, Ly, R * 1.3);
    pool.addColorStop(0, "rgba(0,184,219,0.18)");
    pool.addColorStop(0.5, "rgba(0,184,219,0.06)");
    pool.addColorStop(1, "rgba(0,184,219,0)");
    o.fillStyle = pool;
    o.fillRect(0, 0, lw, lh);
  }

  const cyw = Math.cos(f.yaw);
  const syw = Math.sin(f.yaw);
  const cp = Math.cos(f.pitch);
  const sp = Math.sin(f.pitch);
  const Sx = lw * f.spreadX;
  const Sy = lh * f.spreadY;
  const leafCount = scene.byPath.size;
  const fileCut = f.reveal ? Math.ceil(leafCount * f.reveal.files) : Infinity;
  // A directory appears with its first file.
  const found = new Set<number>();
  for (const n of scene.nodes) if (n.kind === 0 && n.li < fileCut) found.add(n.grp);
  const shown = (n: PixelNode) =>
    n.kind === 2 || (n.kind === 1 ? found.has(n.grp) : n.li < fileCut);
  const nodes = f.reveal ? scene.nodes.filter(shown) : scene.nodes;
  let edges = scene.edges;
  if (f.reveal) {
    // Hub edges arrive with their file; links between files arrive in order
    // as the connections are found.
    let links = 0;
    const linkTotal = scene.edges.filter(([a, b]) => a.kind === 0 && b.kind === 0).length;
    const linkCut = Math.floor(linkTotal * f.reveal.links);
    edges = scene.edges.filter(([a, b]) => {
      if (!shown(a) || !shown(b)) return false;
      if (a.kind === 0 && b.kind === 0) return links++ < linkCut;
      return true;
    });
  }
  const styles = new Map<PixelNode, NodeStyle>();

  for (const n of nodes) {
    const x1 = n.x * cyw - n.z * syw;
    const z1 = n.x * syw + n.z * cyw;
    const y2 = n.y * cp - z1 * sp;
    const z2 = n.y * sp + z1 * cp;
    const k = DEPTH / (DEPTH - z2);
    n.sx = lw / 2 + x1 * Sx * k;
    n.sy = lh / 2 + y2 * Sy * k;
    n.k = k;
    n.z2 = z2;
    n.d = Math.max(0, Math.min(1, (z2 + 1.1) / 2.2));
    let g = f.light ? Math.max(0, 1 - Math.hypot(n.sx - Lx, n.sy - Ly) / R) : 0;
    g = g * g * (3 - 2 * g);
    n.g += (g - n.g) * f.glowEase;
    const style = f.style?.(n);
    if (style) styles.set(n, style);
  }
  const dim = f.dimUnstyled && styles.size > 0;

  // Base edges, batched by colour and alpha step.
  o.lineWidth = 1;
  const batches = new Map<string, PixelEdge[]>();
  const litEdges: { e: PixelEdge; lit: number }[] = [];
  for (const e of edges) {
    const [a, b] = e;
    const both = styles.has(a) && styles.has(b);
    const base = (0.1 + 0.25 * ((a.d + b.d) / 2)) * (dim && !both ? 0.45 : 1);
    const tint = both ? styles.get(b)!.tint : b.tint;
    const key = `${tint}|${step(both ? Math.max(base, 0.55) : base)}`;
    let list = batches.get(key);
    if (!list) batches.set(key, (list = []));
    list.push(e);
    const lit = Math.min(a.g, b.g);
    if (lit > 0.03) litEdges.push({ e, lit });
  }
  for (const [key, list] of batches) {
    const [tint, level] = key.split("|");
    o.strokeStyle = `rgba(${tint},${(Number(level) / ALPHA_STEPS).toFixed(3)})`;
    o.beginPath();
    for (const [a, b] of list) {
      o.moveTo(a.sx, a.sy);
      o.lineTo(b.sx, b.sy);
    }
    o.stroke();
  }
  for (const { e, lit } of litEdges) {
    const [a, b, phase] = e;
    o.strokeStyle = `rgba(83,234,253,${(lit * 0.95).toFixed(3)})`;
    o.beginPath();
    o.moveTo(a.sx, a.sy);
    o.lineTo(b.sx, b.sy);
    o.stroke();
    if (!f.reduce) {
      const p = (t * 0.0005 + phase) % 1;
      o.fillStyle = `rgba(255,255,255,${lit.toFixed(3)})`;
      o.fillRect(Math.round(a.sx + (b.sx - a.sx) * p) - 1, Math.round(a.sy + (b.sy - a.sy) * p) - 1, 2, 2);
    }
  }
  if (f.followed) {
    o.fillStyle = "#fafafa";
    for (const e of edges) {
      const [a, b, phase] = e;
      if (!f.followed(a, b)) continue;
      o.strokeStyle = "rgba(250,250,250,0.7)";
      o.beginPath();
      o.moveTo(a.sx, a.sy);
      o.lineTo(b.sx, b.sy);
      o.stroke();
      const p = f.reduce ? 0.5 : (t * 0.0009 + phase) % 1;
      o.fillRect(Math.round(a.sx + (b.sx - a.sx) * p) - 1, Math.round(a.sy + (b.sy - a.sy) * p) - 1, 2, 2);
    }
  }

  // Nodes, far to near. Shadows are costly, so busy scenes keep them for hubs
  // and lit files only.
  const order = nodes.slice().sort((p, q) => p.z2 - q.z2);
  const busy = nodes.length > 400;
  let focus: PixelNode | null = null;
  let best = Infinity;
  for (const n of order) {
    const style = styles.get(n);
    const s = Math.max(1, Math.round(n.sz * 0.6 * n.k * (1 + 0.6 * n.g) * (style?.scale ?? 1)));
    const tw = f.reduce || !n.ph ? 0 : Math.pow(Math.max(0, Math.sin(t * 0.0011 + n.ph * 6.283)), 14);
    const x0 = Math.round(n.sx - s / 2);
    const y0 = Math.round(n.sy - s / 2);
    const tint = style?.tint ?? n.tint;
    o.save();
    const glow = style?.glow ?? 0;
    if (n.kind > 0 || glow > 0 || (!busy && tw > 0.05)) {
      o.shadowBlur = (n.kind > 0 ? 6 : 0) + 8 * tw + 10 * glow;
      o.shadowColor = `rgba(${tint},0.9)`;
    }
    const alpha = style ? 1 : Math.min(1, 0.4 + 0.55 * n.d + 0.4 * tw) * (dim && n.kind === 0 ? 0.4 : 1);
    o.fillStyle = `rgba(${tint},${alpha.toFixed(3)})`;
    o.fillRect(x0, y0, s, s);
    o.restore();
    if (n.g > 0.02) {
      o.save();
      o.shadowBlur = 10 * n.g;
      o.shadowColor = "rgba(0,184,219,1)";
      o.fillStyle = `rgba(200,250,255,${Math.min(1, n.g * 1.1).toFixed(3)})`;
      o.fillRect(x0, y0, s, s);
      o.restore();
    }
    n.s = s;
    if (f.focusLabel && n.kind === 0 && n.g > 0.45) {
      const dd = Math.hypot(n.sx - Lx, n.sy - Ly);
      if (dd < best) {
        best = dd;
        focus = n;
      }
    }
  }
  if (f.pinned) focus = f.pinned;
  if (focus) {
    const fs = focus.s + 4;
    o.strokeStyle = "#f6339a";
    o.lineWidth = 1;
    o.strokeRect(Math.round(focus.sx - fs / 2) + 0.5, Math.round(focus.sy - fs / 2) + 0.5, fs, fs);
  }

  ctx.clearRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, 0, 0, lw * cell, lh * cell);

  const dpr = f.dpr;
  ctx.textBaseline = "middle";
  if (f.hubLabels) {
    ctx.font = `${12 * dpr}px ${f.font}`;
    for (const n of nodes) {
      if (n.kind !== 1) continue;
      ctx.fillStyle = `rgba(212,212,216,${(0.3 + 0.6 * n.d).toFixed(3)})`;
      ctx.fillText(n.short, (n.sx + n.s / 2 + 3) * cell, n.sy * cell);
    }
  }
  if (focus && focus.label) {
    const slash = focus.label.lastIndexOf("/") + 1;
    const dir = focus.label.slice(0, slash);
    const file = focus.label.slice(slash);
    ctx.font = `${13 * dpr}px ${f.font}`;
    const wd = ctx.measureText(dir).width;
    const wf = ctx.measureText(file).width;
    const pad = 10 * dpr;
    const bh = 28 * dpr;
    const bw = wd + wf + pad * 2;
    const fx = focus.sx * cell;
    const fy = focus.sy * cell;
    let bx = fx + 18 * dpr;
    let by = fy - bh - 12 * dpr;
    if (bx + bw > W - 4 * dpr) bx = fx - 18 * dpr - bw;
    if (by < 4 * dpr) by = fy + 16 * dpr;
    ctx.fillStyle = "rgba(9,9,11,0.94)";
    ctx.fillRect(bx, by, bw, bh);
    ctx.strokeStyle = "#f6339a";
    ctx.lineWidth = dpr;
    ctx.strokeRect(bx + 0.5, by + 0.5, bw - 1, bh - 1);
    ctx.fillStyle = "#9f9fa9";
    ctx.fillText(dir, bx + pad, by + bh / 2);
    ctx.fillStyle = "#fafafa";
    ctx.fillText(file, bx + pad + wd, by + bh / 2);
  }
}

/**
 * The yaw that turns a node to face the viewer.
 *
 * @param n - The node.
 * @returns An angle in radians.
 */
export function yawToward(n: Pick<PixelNode, "x" | "z">): number {
  return Math.atan2(n.x, n.z);
}
