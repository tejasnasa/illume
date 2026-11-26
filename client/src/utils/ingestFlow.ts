/**
 * The ingestion pipeline's stages, and the pure functions that drive them.
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

/** One stage of the pipeline. */
export interface FlowNode {
  id: string;
  label: string;
  /**
   * Singular and plural noun for the total this stage publishes. Absent where
   * the stage publishes no total, which is most of them -- a bare number on a
   * node says nothing.
   */
  unit?: readonly [string, string];
}

/**
 * Every stage the backend publishes, with the label the page shows for it.
 *
 * Order is the screen-reader summary's order. `pr_fetch` comes last because
 * its future is only joined at the very end, so it can outlive every other
 * stage.
 */
export const NODES: readonly FlowNode[] = [
  { id: "clone", label: "Fetch Repo" },
  { id: "parse", label: "Parse files" },
  {
    id: "resolve_dependencies",
    label: "Map Connections",
    unit: ["dependency", "dependencies"],
  },
  { id: "compute_fan_metrics", label: "Rank Impact" },
  { id: "detect_stack", label: "Identify Stack" },
  {
    id: "git_history",
    label: "Mine Git History",
    unit: ["file", "files"],
  },
  { id: "criticality", label: "Score Risk" },
  { id: "glossary", label: "Create Glossary" },
  { id: "reading_order", label: "Create Reading Order" },
  {
    id: "generate_embeddings",
    label: "Generate Embeddings",
    unit: ["vector", "vectors"],
  },
  { id: "brief", label: "Analyze Architecture" },
  { id: "ready", label: "Ready" },
  {
    id: "pr_fetch",
    label: "Gather PRs",
    unit: ["PR", "PRs"],
  },
];

export const NODES_BY_ID: Record<string, FlowNode> = Object.fromEntries(
  NODES.map((node) => [node.id, node]),
);

/** Every stage id the page can render. */
export const STAGE_IDS: readonly string[] = NODES.map((node) => node.id);

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

/** One column of the pipeline board: a heading and the stages under it. */
export interface PipelineColumn {
  label: string;
  stages: readonly string[];
}

/**
 * The board's columns, left to right.
 *
 * Stages that share a column run at the same time -- the parse, the git
 * history mine and the PR fetch all start straight after the clone -- so the
 * columns read as "what can happen now" rather than as a strict sequence.
 */
export const PIPELINE_COLUMNS: readonly PipelineColumn[] = [
  { label: "Fetch", stages: ["clone"] },
  { label: "Read", stages: ["parse", "git_history", "pr_fetch"] },
  {
    label: "Connect",
    stages: ["resolve_dependencies", "compute_fan_metrics", "detect_stack"],
  },
  { label: "Score", stages: ["criticality"] },
  { label: "Write", stages: ["glossary", "reading_order"] },
  { label: "Index", stages: ["generate_embeddings", "brief"] },
  { label: "Done", stages: ["ready"] },
];

/**
 * Render a stage's published total with its noun, e.g. ``2,871 dependencies``.
 *
 * @param node - The stage the total belongs to.
 * @param count - The total it published.
 * @returns The label, or null for a stage whose totals carry no noun.
 */
export function countLabel(node: FlowNode, count: number): string | null {
  if (!node.unit) return null;
  const noun = count === 1 ? node.unit[0] : node.unit[1];
  return `${count.toLocaleString("en-US")} ${noun}`;
}

/** How many stages have finished. */
export function doneCount(state: StageStateMap): number {
  return STAGE_IDS.filter((id) => state[id]?.state === "done").length;
}
