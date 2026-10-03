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
  /**
   * Singular and plural noun for the total this stage publishes. Absent where
   * the stage publishes no total, which is most of them -- a bare number on a
   * node says nothing.
   */
  unit?: readonly [string, string];
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
  /**
   * The stages that must *all* be done for this edge to light.
   *
   * An edge leaving a junction cannot key off its own source -- a junction is
   * not a stage and never completes -- so it names the stages it actually
   * waited for instead. Defaults to "the source is done".
   */
  requires?: readonly string[];
}

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 60;
export const VIEWBOX = { width: 1210, height: 580 } as const;

/**
 * The pipeline, drawn to match the real execution order.
 *
 * The spine runs top-to-bottom because it is genuinely one sequential chain;
 * the two fork/join pairs sit to its right where their parallelism is
 * visible; `pr_fetch` rides a rail above everything because its future is
 * only joined at the very end, so it can outlive every other stage.
 */
export const NODES: readonly FlowNode[] = [
  { id: "clone", label: "Fetch Repo", cx: 150, cy: 70 },
  { id: "parse", label: "Parse files", cx: 150, cy: 146 },
  {
    id: "resolve_dependencies",
    label: "Map Connections",
    cx: 150,
    cy: 222,
    unit: ["dependency", "dependencies"],
  },
  { id: "compute_fan_metrics", label: "Rank Impact", cx: 150, cy: 298 },
  { id: "detect_stack", label: "Identify Stack", cx: 150, cy: 374 },
  {
    id: "git_history",
    label: "Mine Git History",
    cx: 150,
    cy: 450,
    unit: ["file", "files"],
  },
  { id: "criticality", label: "Score Risk", cx: 150, cy: 526 },
  { id: "glossary", label: "Create Glossary", cx: 470, cy: 390 },
  { id: "reading_order", label: "Create Reading Order", cx: 470, cy: 526 },
  {
    id: "generate_embeddings",
    label: "Generate Embeddings",
    cx: 790,
    cy: 390,
    unit: ["vector", "vectors"],
  },
  { id: "brief", label: "Analyze Architecture", cx: 790, cy: 526 },
  { id: "ready", label: "Ready", cx: 1080, cy: 298 },
  {
    id: "pr_fetch",
    label: "Gather PRs",
    cx: 470,
    cy: 70,
    unit: ["PR", "PRs"],
  },
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
      [150, 100],
      [150, 116],
    ],
    kind: "main",
  },
  {
    from: "parse",
    to: "resolve_dependencies",
    points: [
      [150, 176],
      [150, 192],
    ],
    kind: "main",
  },
  {
    from: "resolve_dependencies",
    to: "compute_fan_metrics",
    points: [
      [150, 252],
      [150, 268],
    ],
    kind: "main",
  },
  {
    from: "compute_fan_metrics",
    to: "detect_stack",
    points: [
      [150, 328],
      [150, 344],
    ],
    kind: "main",
  },
  {
    from: "detect_stack",
    to: "git_history",
    points: [
      [150, 404],
      [150, 420],
    ],
    kind: "main",
  },
  {
    from: "git_history",
    to: "criticality",
    points: [
      [150, 480],
      [150, 496],
    ],
    kind: "main",
  },
  {
    from: "clone",
    to: "pr_fetch",
    points: [
      [250, 70],
      [370, 70],
    ],
    kind: "sidecar",
  },
  {
    from: "pr_fetch",
    to: "ready",
    points: [
      [570, 70],
      [1080, 70],
      [1080, 268],
    ],
    kind: "sidecar",
  },
  {
    from: "criticality",
    to: "fork_risk",
    points: [
      [250, 526],
      [290, 526],
      [290, 458],
      [330, 458],
    ],
    kind: "main",
  },
  {
    from: "fork_risk",
    to: "glossary",
    points: [
      [330, 458],
      [330, 390],
      [370, 390],
    ],
    kind: "main",
    requires: ["criticality"],
  },
  {
    from: "fork_risk",
    to: "reading_order",
    points: [
      [330, 458],
      [330, 526],
      [370, 526],
    ],
    kind: "main",
    requires: ["criticality"],
  },
  {
    from: "glossary",
    to: "join_llm",
    points: [
      [570, 390],
      [610, 390],
      [610, 458],
      [620, 458],
    ],
    kind: "main",
  },
  {
    from: "reading_order",
    to: "join_llm",
    points: [
      [570, 526],
      [610, 526],
      [610, 458],
      [620, 458],
    ],
    kind: "main",
  },
  {
    from: "join_llm",
    to: "generate_embeddings",
    points: [
      [620, 458],
      [650, 458],
      [650, 390],
      [690, 390],
    ],
    kind: "main",
    requires: ["glossary", "reading_order"],
  },
  {
    from: "join_llm",
    to: "brief",
    points: [
      [620, 458],
      [650, 458],
      [650, 526],
      [690, 526],
    ],
    kind: "main",
    requires: ["glossary", "reading_order"],
  },
  {
    from: "generate_embeddings",
    to: "join_final",
    points: [
      [890, 390],
      [930, 390],
      [930, 458],
      [940, 458],
    ],
    kind: "main",
  },
  {
    from: "brief",
    to: "join_final",
    points: [
      [890, 526],
      [930, 526],
      [930, 458],
      [940, 458],
    ],
    kind: "main",
  },
  {
    from: "join_final",
    to: "ready",
    points: [
      [940, 458],
      [1080, 458],
      [1080, 328],
    ],
    kind: "main",
    requires: ["generate_embeddings", "brief"],
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

  // Zero is a real total -- an empty history, a repository with no pull
  // requests -- so this tests for presence, not truthiness.
  const count = typeof frame.count === "number" ? frame.count : current.count;

  const unchanged =
    nextState === current.state &&
    progress === current.progress &&
    count === current.count &&
    frame.message === current.detail;

  if (unchanged) return state;

  return {
    ...state,
    [stage]: { state: nextState, progress, count, detail: frame.message },
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
 * Cumulative arc length at each waypoint, starting at 0.
 *
 * @param points - Waypoints in canvas space.
 * @returns One running total per waypoint.
 */
function cumulativeLengths(points: readonly Point[]): number[] {
  const lengths: number[] = [0];
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    total += Math.hypot(x1 - x0, y1 - y0);
    lengths.push(total);
  }
  return lengths;
}

/**
 * Total arc length of an edge.
 *
 * The travelling comet is drawn as a dash on the edge's own path, so it needs
 * the path's length in the same units the geometry was authored in -- no
 * `getTotalLength()`, and therefore no layout read.
 *
 * @param points - Waypoints in canvas space.
 * @returns The summed segment length, or 0 for a degenerate edge.
 */
export function pathLengthOf(points: readonly Point[]): number {
  const lengths = cumulativeLengths(points);
  return lengths[lengths.length - 1] ?? 0;
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

  const cumulative = cumulativeLengths(points);
  const total = cumulative[cumulative.length - 1];

  // A degenerate edge (all waypoints identical) would divide by zero and
  // hand motion a NaN keyframe, so fall back to an even split.
  if (total === 0) return points.map((_, i) => i / (points.length - 1));

  return cumulative.map((length) => length / total);
}

/** Whether a stage has stopped changing. */
function hasSettled(state: NodeState | undefined): boolean {
  return state === "done" || state === "failed";
}

/**
 * Whether an edge should be drawn as lit.
 *
 * An edge leaving a barrier names the stages it waited for rather than
 * carrying a source that can complete -- a barrier is not a stage and never
 * finishes -- so `requires` is checked first.
 */
export function isLit(edge: FlowEdge, states: StageStateMap): boolean {
  if (edge.requires) {
    return edge.requires.every((id) => states[id]?.state === "done");
  }
  return states[edge.from]?.state === "done";
}

/**
 * Whether an edge's far end has stopped changing.
 *
 * An edge into a barrier has no stage of its own to consult. Looking its
 * target up in the state map returns `undefined`, which is never `done`, so
 * a finished run kept its particles flowing forever. The stages the barrier
 * feeds stand in for it instead.
 */
function downstreamSettled(edge: FlowEdge, states: StageStateMap): boolean {
  if (!(edge.to in NODES_BY_ID)) {
    return EDGES.filter((candidate) => candidate.from === edge.to).every(
      (candidate) => hasSettled(states[candidate.to]?.state),
    );
  }
  return hasSettled(states[edge.to]?.state);
}

/**
 * Whether an edge should show particles in transit.
 *
 * True while it is lit and whatever it leads to has not settled. Note this
 * is not the same question as `isLit`: an edge stays lit once its source is
 * done, but particles belong only to work still in flight.
 *
 * @param edge - The edge to test.
 * @param states - Current state of every stage.
 * @returns True when particles should be drawn along this edge.
 */
export function isFlowing(edge: FlowEdge, states: StageStateMap): boolean {
  return isLit(edge, states) && !downstreamSettled(edge, states);
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
