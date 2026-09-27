/**
 * The ingestion pipeline as a graph, and the pure functions that drive it.
 *
 * Nothing here touches React or the DOM, which is what lets the reducer --
 * the part with the real logic -- be tested in the fast node environment.
 *
 * Two rules shape everything below:
 *
 * - **State is a pure function of the frames received.** No timer advances a
 *   node, so the view cannot claim progress the backend never reported.
 * - **Seeding is pessimistic.** Where a stage's completion cannot be proven
 *   from the coarse repository status, it is left short of `done`.
 *
 * @module utils/ingestFlow
 */

import type {
  IngestFrame,
  NodeState,
  StageState,
  StageStateMap,
} from "@/types/ingest";

/** A point in the canvas coordinate space. */
export type Point = readonly [number, number];

/** One stage box in the flow. */
export interface FlowNode {
  id: string;
  label: string;
  /** Centre of the box. */
  cx: number;
  cy: number;
}

/** One edge between stages, with authored geometry. */
export interface FlowEdge {
  from: string;
  to: string;
  /**
   * Explicit waypoints. Authoring these instead of measuring the DOM keeps
   * the travelling pulse driven by literal numbers -- no layout effect, no
   * reflow on resize, no `getTotalLength()`.
   */
  points: readonly Point[];
  /** `sidecar` marks work that runs alongside the spine rather than in it. */
  kind: "main" | "sidecar";
}

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 52;
export const VIEWBOX = { width: 1180, height: 660 } as const;

/**
 * The pipeline, drawn to match the real execution order.
 *
 * The spine runs top-to-bottom because it is genuinely one sequential chain;
 * the two fork/join pairs sit to its right where their parallelism is
 * visible; `pr_fetch` rides a rail above everything because its future is
 * only joined at the very end, so it can outlive every other stage.
 */
export const NODES: readonly FlowNode[] = [
  { id: "clone", label: "Clone", cx: 150, cy: 90 },
  { id: "parse", label: "Parse files", cx: 150, cy: 170 },
  { id: "resolve_dependencies", label: "Resolve imports", cx: 150, cy: 250 },
  { id: "compute_fan_metrics", label: "Fan metrics", cx: 150, cy: 330 },
  { id: "detect_stack", label: "Detect stack", cx: 150, cy: 410 },
  { id: "git_history", label: "Git history", cx: 150, cy: 490 },
  { id: "criticality", label: "Criticality", cx: 150, cy: 570 },
  { id: "glossary", label: "Glossary", cx: 450, cy: 300 },
  { id: "reading_order", label: "Reading order", cx: 450, cy: 460 },
  { id: "generate_embeddings", label: "Embeddings", cx: 750, cy: 300 },
  { id: "brief", label: "Architecture brief", cx: 750, cy: 460 },
  { id: "ready", label: "Ready", cx: 1050, cy: 380 },
  { id: "pr_fetch", label: "Pull requests", cx: 450, cy: 90 },
];

export const NODES_BY_ID: Record<string, FlowNode> = Object.fromEntries(
  NODES.map((node) => [node.id, node]),
);

/** Every stage id the graph can render. */
export const STAGE_IDS: readonly string[] = NODES.map((node) => node.id);

export const EDGES: readonly FlowEdge[] = [
  // The spine.
  {
    from: "clone",
    to: "parse",
    points: [
      [150, 116],
      [150, 144],
    ],
    kind: "main",
  },
  {
    from: "parse",
    to: "resolve_dependencies",
    points: [
      [150, 196],
      [150, 224],
    ],
    kind: "main",
  },
  {
    from: "resolve_dependencies",
    to: "compute_fan_metrics",
    points: [
      [150, 276],
      [150, 304],
    ],
    kind: "main",
  },
  {
    from: "compute_fan_metrics",
    to: "detect_stack",
    points: [
      [150, 356],
      [150, 384],
    ],
    kind: "main",
  },
  {
    from: "detect_stack",
    to: "git_history",
    points: [
      [150, 436],
      [150, 464],
    ],
    kind: "main",
  },
  {
    from: "git_history",
    to: "criticality",
    points: [
      [150, 516],
      [150, 544],
    ],
    kind: "main",
  },

  // The sidecar branch: dispatched alongside the spine, joined last.
  {
    from: "clone",
    to: "pr_fetch",
    points: [
      [240, 90],
      [360, 90],
    ],
    kind: "sidecar",
  },
  {
    from: "pr_fetch",
    to: "ready",
    points: [
      [540, 90],
      [1050, 90],
      [1050, 354],
    ],
    kind: "sidecar",
  },

  // Fork: two LLM stages run side by side.
  {
    from: "criticality",
    to: "glossary",
    points: [
      [240, 558],
      [290, 558],
      [290, 300],
      [360, 300],
    ],
    kind: "main",
  },
  {
    from: "criticality",
    to: "reading_order",
    points: [
      [240, 582],
      [320, 582],
      [320, 460],
      [360, 460],
    ],
    kind: "main",
  },

  // Join: both of the pair must finish before either of the next starts,
  // which is why this is four edges and not two.
  {
    from: "glossary",
    to: "generate_embeddings",
    points: [
      [540, 300],
      [660, 300],
    ],
    kind: "main",
  },
  {
    from: "reading_order",
    to: "brief",
    points: [
      [540, 460],
      [660, 460],
    ],
    kind: "main",
  },
  {
    from: "glossary",
    to: "brief",
    points: [
      [540, 314],
      [615, 314],
      [615, 510],
      [750, 510],
      [750, 486],
    ],
    kind: "main",
  },
  {
    from: "reading_order",
    to: "generate_embeddings",
    points: [
      [360, 446],
      [330, 446],
      [330, 250],
      [700, 250],
      [700, 274],
    ],
    kind: "main",
  },

  // Converge.
  {
    from: "generate_embeddings",
    to: "ready",
    points: [
      [840, 300],
      [915, 300],
      [915, 380],
      [960, 380],
    ],
    kind: "main",
  },
  {
    from: "brief",
    to: "ready",
    points: [
      [840, 460],
      [925, 460],
      [925, 380],
      [960, 380],
    ],
    kind: "main",
  },
];

/** Higher rank means further along. A frame can only ever move a node up. */
const RANK: Record<NodeState, number> = {
  pending: 0,
  active: 1,
  done: 2,
  failed: 2,
};

/** Build an all-pending map, so every stage is addressable from the start. */
export function emptyStateMap(): StageStateMap {
  return Object.fromEntries(
    STAGE_IDS.map((id) => [id, { state: "pending" as NodeState }]),
  );
}

/**
 * The stages a repository status of `embedding` proves have already finished.
 *
 * The chain is sequential, so the embedding status -- written once the
 * glossary/reading-order join has returned -- proves every stage before it.
 */
const DONE_ONCE_EMBEDDING = [
  "clone",
  "parse",
  "resolve_dependencies",
  "compute_fan_metrics",
  "detect_stack",
  "git_history",
  "criticality",
  "glossary",
  "reading_order",
] as const;

/**
 * Seed node states from the coarse repository status.
 *
 * The socket only delivers frames published after it connects, so without
 * this a page opened two minutes into an ingest would replay the animation
 * from the clone. The status is monotonic along a sequential chain, so each
 * value proves a prefix of it -- and only a prefix.
 *
 * This is deliberately pessimistic. `parsing` spans parse through
 * reading-order, so it can only prove that the clone finished; the animation
 * may show a stage as pending that has actually completed, which is the
 * correct direction to be wrong in. `pr_fetch` is never seeded as done,
 * because its future is joined at the very end and no status proves it.
 *
 * @param status - The repository status as rendered by the server.
 * @returns Seeded node states.
 */
export function seedFromStatus(status: string): StageStateMap {
  const map = emptyStateMap();
  const mark = (ids: readonly string[], state: NodeState) => {
    for (const id of ids) map[id] = { state };
  };

  switch (status) {
    case "cloning":
      map.clone = { state: "active" };
      break;

    case "parsing":
      // Only the clone is provable here; everything from parse onwards is
      // still ambiguous, so the earliest candidate takes `active`.
      mark(["clone"], "done");
      mark(["parse", "pr_fetch"], "active");
      break;

    case "embedding":
      // Written after the glossary/reading-order join returned, so the whole
      // prefix through reading_order is proven. Embeddings and the brief run
      // concurrently from here, and the PR fetch may still be in flight.
      mark(DONE_ONCE_EMBEDDING, "done");
      mark(["generate_embeddings", "brief", "pr_fetch"], "active");
      break;

    case "ready":
      mark(STAGE_IDS, "done");
      break;

    case "failed":
    case "pending":
    default:
      // Nothing is provable. `pending` additionally renders a queued
      // affordance at the view level, because the worker may not have
      // picked the job up yet.
      break;
  }

  return map;
}

/**
 * Translate a published phase into the node state it implies.
 *
 * `progress` maps to `active` rather than a fifth state: a stage reporting
 * its position is by definition still running.
 */
function phaseToState(phase: string | undefined): NodeState | null {
  switch (phase) {
    case "started":
    case "progress":
      return "active";
    case "done":
      return "done";
    default:
      return null;
  }
}

/** Mark every currently-active node as failed, leaving the rest alone. */
function failActive(state: StageStateMap): StageStateMap {
  let changed = false;
  const next: StageStateMap = { ...state };
  for (const id of STAGE_IDS) {
    if (next[id]?.state === "active") {
      next[id] = { ...next[id], state: "failed" };
      changed = true;
    }
  }
  return changed ? next : state;
}

/**
 * Fold a single frame into the state map.
 *
 * Monotonic: a frame can advance a node but never move it backwards, which
 * is what makes a replayed or out-of-order frame harmless. Idempotent for
 * the same reason, which matters because `embedding_started` is published
 * twice with different messages.
 *
 * Returns the original object when nothing changed, so a caller memoising on
 * identity does not re-render for a frame that carried no new information.
 *
 * @param state - Current states.
 * @param frame - The frame just received.
 * @returns The next states.
 */
export function reduceFrame(
  state: StageStateMap,
  frame: IngestFrame,
): StageStateMap {
  // A failure frame names no stage -- the task's catch-all cannot know which
  // one raised -- so the only honest reading is "whatever was running".
  if (frame.phase === "failed" || frame.status === "failed") {
    return failActive(state);
  }

  // Reaching `ready` proves every stage succeeded: the task writes that status
  // only after the whole pipeline has returned, and any stage raising would
  // have failed the run instead. Completing the whole graph from this one
  // frame is therefore a statement of fact, not an assumption -- and it keeps
  // a missed intermediate frame (a reconnect, say) from leaving the board
  // permanently short of done.
  if (frame.stage === "ready" && frame.phase === "done") {
    return Object.fromEntries(
      STAGE_IDS.map((id) => [id, { ...state[id], state: "done" as NodeState }]),
    );
  }

  const stage = frame.stage;
  if (!stage || !(stage in NODES_BY_ID)) return state;

  const target = phaseToState(frame.phase);
  if (target === null) return state;

  const current: StageState = state[stage] ?? { state: "pending" };
  const nextState = RANK[target] > RANK[current.state] ? target : current.state;

  // Only parse publishes a real counter, and a zero total would divide by
  // zero in the bar, so it is rejected here rather than guarded downstream.
  const hasCounts =
    typeof frame.processed === "number" &&
    typeof frame.total === "number" &&
    frame.total > 0;
  const progress = hasCounts
    ? { processed: frame.processed as number, total: frame.total as number }
    : current.progress;

  const unchanged =
    nextState === current.state &&
    progress === current.progress &&
    frame.message === current.detail;

  if (unchanged) return state;

  return {
    ...state,
    [stage]: { state: nextState, progress, detail: frame.message },
  };
}

/** Fold a whole sequence of frames, oldest first. */
export function reduceFrames(
  state: StageStateMap,
  frames: readonly IngestFrame[],
): StageStateMap {
  return frames.reduce(reduceFrame, state);
}

/**
 * Convert authored waypoints into an SVG path.
 *
 * @param points - Waypoints in canvas space.
 * @returns An `M`/`L` path string, or an empty string for no points.
 */
export function pathFromPoints(points: readonly Point[]): string {
  if (points.length === 0) return "";
  const [first, ...rest] = points;
  const head = `M ${first[0]} ${first[1]}`;
  return rest.reduce((path, [x, y]) => `${path} L ${x} ${y}`, head);
}

/**
 * Progress fractions (0..1) for each waypoint, by cumulative arc length.
 *
 * Keyframing a pulse by vertex index would make a four-point edge move at a
 * different speed from a two-point one. Weighting by distance keeps every
 * pulse at a constant pixels-per-second.
 *
 * @param points - Waypoints in canvas space.
 * @returns One fraction per waypoint, starting at 0 and ending at 1.
 */
export function normaliseTimes(points: readonly Point[]): number[] {
  if (points.length < 2) return points.map(() => 0);

  const cumulative: number[] = [0];
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    total += Math.hypot(x1 - x0, y1 - y0);
    cumulative.push(total);
  }

  // A degenerate edge (all waypoints identical) would divide by zero and
  // hand motion a NaN keyframe, so fall back to an even split.
  if (total === 0) return points.map((_, i) => i / (points.length - 1));

  return cumulative.map((length) => length / total);
}

/**
 * The stage currently running, if exactly one is.
 *
 * @param state - Current states.
 * @returns The active stage id, or null.
 */
export function activeStage(state: StageStateMap): string | null {
  const active = STAGE_IDS.filter((id) => state[id]?.state === "active");
  return active.length > 0 ? active[0] : null;
}

/**
 * Whether every stage has finished.
 *
 * @param state - Current states.
 * @returns True when nothing is pending or active.
 */
export function isComplete(state: StageStateMap): boolean {
  return STAGE_IDS.every((id) => state[id]?.state === "done");
}

/**
 * Whether any stage has failed.
 *
 * @param state - Current states.
 * @returns True when at least one stage failed.
 */
export function hasFailed(state: StageStateMap): boolean {
  return STAGE_IDS.some((id) => state[id]?.state === "failed");
}
