/**
 * Pure state machine behind a streamed agent run.
 *
 * Every streamed `StreamEvent` goes through
 * {@link runReducer}, so the activity block and the graph cannot disagree about
 * what a record means. The reducer holds no timers and reads no clock: every
 * action that needs a time carries it. An event type it does not recognise
 * leaves the state untouched, because the server is free to add events before
 * the client learns about them.
 * @module AgentReducer
 */
import type {
  Citation,
  DoneData,
  ErrorData,
  EvidenceData,
  NodesData,
  PlanData,
  QueryData,
  RetrievalData,
  RouteData,
  RunStartedData,
  StreamEvent,
  ThinkingData,
  ToolCallData,
  ToolResultData,
  Usage,
  WorkerData,
} from "./types";

export type RunStatus =
  | "idle"
  | "connecting"
  | "live"
  | "done"
  | "error"
  | "cancelled"
  | "connection_lost";

/** What the run is doing right now; drives the header's status line. */
export type RunPhase =
  | "starting"
  | "routing"
  | "planning"
  | "retrieving"
  | "thinking"
  | "tool"
  | "answering"
  | "finished";

interface RowBase {
  id: string;
  /** The worker whose lane holds the row; `null` for the main agent. */
  laneId: string | null;
  seq: number;
}

export interface ToolRow extends RowBase {
  kind: "tool";
  callId: string | null;
  tool: string;
  /** The raw JSON the model wrote, as the server forwarded it. */
  args: string;
  parsed: Record<string, unknown> | null;
  status: "running" | "ok" | "error";
  /** The tool's own status string when it is not `ok`. */
  failure: string | null;
  summary: string | null;
  resultCount: number | null;
  latencyMs: number | null;
  truncated: boolean;
  /** Files the call looked at, from the `nodes` event that follows its result. */
  paths: string[];
  /** What the tool returned, as far as the server sends it. */
  output: string | null;
}

export interface PlanRow extends RowBase {
  kind: "plan";
  skipped: boolean;
  reason: string | null;
  probability: number | null;
  subquestions: { id: string; question: string }[];
}

export interface RetrievalRow extends RowBase {
  kind: "retrieval";
  source: string;
  channels: Record<string, number>;
  kept: number;
  reranker: string | null;
  /** The keys it kept, best first. */
  keys: string[];
  /** Every phrasing the channels searched with, the question first. */
  queries: QueryData[];
}

export interface ThinkingRow extends RowBase {
  kind: "thinking";
  /** `reasoning` is the model's own chain of thought; `text` is what it said aloud. */
  mode: "text" | "reasoning";
  text: string;
}

export type ActivityRow = ToolRow | PlanRow | RetrievalRow | ThinkingRow;

export interface Lane {
  id: string;
  question: string;
  status: "pending" | "running" | "done" | "failed";
  /** Position in the lane palette, fixed when the lane first appears. */
  colorIndex: number;
}

/** What the graph needs to light up, kept apart from the rows. */
export interface Highlight {
  /** Every file the run has touched, in first-touch order. */
  touched: string[];
  /** Files of the most recent tool call. */
  current: string[];
  /** The lane that last touched each file; `null` is the main agent. */
  laneOf: Record<string, string | null>;
  /** Consecutive files the agent moved between, newest last. */
  edges: [string, string][];
  /** Counts up once per tool call that reached files; the camera follows it. */
  focusSeq: number;
  /** The file the camera should ease towards for the latest call. */
  focus: string | null;
  /** Files the finished answer cites. */
  cited: string[];
}

export interface RunError {
  message: string;
  kind: string;
  status: number | null;
}

export interface RunState {
  status: RunStatus;
  phase: RunPhase;
  runId: string | null;
  meta: RunStartedData | null;
  route: RouteData | null;
  plan: PlanData | null;
  lanes: Record<string, Lane>;
  laneOrder: string[];
  rows: ActivityRow[];
  highlight: Highlight;
  /** Distinct citation keys the run gathered or retrieved. */
  evidenceKeys: string[];
  answer: string;
  citations: Partial<Citation>[];
  unresolved: string[];
  usage: Usage | null;
  stopReason: string | null;
  limitsReached: string[];
  chatMessageId: string | null;
  error: RunError | null;
  startedAt: number | null;
  endedAt: number | null;
  lastSeq: number;
}

export type RunAction =
  | { type: "start"; at: number }
  | { type: "event"; event: StreamEvent; at?: number }
  | { type: "failed"; message: string; status?: number | null; kind?: string }
  | { type: "cancelled"; at: number }
  | { type: "connection_lost"; at: number }
  | { type: "reset" };

const EMPTY_HIGHLIGHT: Highlight = {
  touched: [],
  current: [],
  laneOf: {},
  edges: [],
  focusSeq: 0,
  focus: null,
  cited: [],
};

/** The state of a run that has not started. */
export const initialRunState: RunState = {
  status: "idle",
  phase: "starting",
  runId: null,
  meta: null,
  route: null,
  plan: null,
  lanes: {},
  laneOrder: [],
  rows: [],
  highlight: EMPTY_HIGHLIGHT,
  evidenceKeys: [],
  answer: "",
  citations: [],
  unresolved: [],
  usage: null,
  stopReason: null,
  limitsReached: [],
  chatMessageId: null,
  error: null,
  startedAt: null,
  endedAt: null,
  lastSeq: -1,
};

/** Statuses after which no more events will arrive. */
export function isTerminal(status: RunStatus): boolean {
  return (
    status === "done" ||
    status === "error" ||
    status === "cancelled" ||
    status === "connection_lost"
  );
}

/**
 * Builds the state of an already-finished turn from stored data.
 *
 * Used for chat history, where only the answer and its sources were kept.
 *
 * @param answer - The stored answer text.
 * @param citations - The stored sources.
 * @param usage - What the run that wrote it spent, when that is known.
 * @returns A `done` state with no activity rows.
 */
export function settledRunState(
  answer: string,
  citations: Partial<Citation>[],
  usage: Usage | null = null,
): RunState {
  return {
    ...initialRunState,
    status: "done",
    phase: "finished",
    answer,
    citations,
    usage,
    highlight: {
      ...EMPTY_HIGHLIGHT,
      cited: citedPaths(citations),
    },
  };
}

function citedPaths(citations: Partial<Citation>[]): string[] {
  const paths = new Set<string>();
  for (const citation of citations) {
    if (citation.file_path) paths.add(citation.file_path);
  }
  return [...paths];
}

function parseArgs(raw: string | undefined): Record<string, unknown> | null {
  if (!raw) return null;
  try {
    const value: unknown = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function uniqueAppend(list: string[], items: string[]): string[] {
  const seen = new Set(list);
  const added = items.filter((item) => {
    if (seen.has(item)) return false;
    seen.add(item);
    return true;
  });
  return added.length > 0 ? [...list, ...added] : list;
}

const MAX_EDGES = 60;
const MAX_THINKING_CHARS = 12_000;

function ensureLane(
  state: RunState,
  id: string,
  question: string,
  status: Lane["status"],
): RunState {
  const existing = state.lanes[id];
  if (existing) {
    const next: Lane = {
      ...existing,
      status,
      question: question || existing.question,
    };
    return { ...state, lanes: { ...state.lanes, [id]: next } };
  }
  return {
    ...state,
    lanes: {
      ...state.lanes,
      [id]: { id, question, status, colorIndex: state.laneOrder.length },
    },
    laneOrder: [...state.laneOrder, id],
  };
}

function pushRow(state: RunState, row: ActivityRow): RunState {
  return { ...state, rows: [...state.rows, row] };
}

function rowBase(state: RunState, event: StreamEvent): RowBase {
  return {
    id: `${event.seq}`,
    laneId: event.worker_id,
    seq: event.seq,
  };
}

function applyNodes(
  state: RunState,
  event: StreamEvent,
  data: NodesData,
): RunState {
  const paths = (data.paths ?? []).filter(Boolean);
  if (paths.length === 0) return state;

  // The call the paths belong to gets them, so the row can list what matched.
  const rows = state.rows.map((row) =>
    row.kind === "tool" && data.call_id && row.callId === data.call_id
      ? { ...row, paths }
      : row,
  );

  const laneOf = { ...state.highlight.laneOf };
  for (const path of paths) laneOf[path] = event.worker_id;

  // Follow the trail: from where this lane last was to where it is now, or
  // along the listed order when the tool reported a path through the graph.
  const edges = [...state.highlight.edges];
  const previous = state.highlight.focus;
  if (data.action === "path") {
    for (let i = 1; i < paths.length; i++) edges.push([paths[i - 1], paths[i]]);
  } else if (previous && previous !== paths[0]) {
    edges.push([previous, paths[0]]);
  }

  return {
    ...state,
    rows,
    highlight: {
      ...state.highlight,
      touched: uniqueAppend(state.highlight.touched, paths),
      current: paths,
      laneOf,
      edges: edges.slice(-MAX_EDGES),
      focusSeq: state.highlight.focusSeq + 1,
      focus: paths[0],
    },
  };
}

/** Text with its citation marks and spacing removed, for comparing two copies. */
function comparable(text: string): string {
  return text
    .replace(/\[[^\]\n]{1,200}\]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .toLowerCase();
}

/**
 * Drops the text the agent wrote as its answer, once that answer arrives.
 *
 * An agent can answer by writing text rather than calling a tool. That text
 * streams as it is written, and is then the answer itself, so showing it twice
 * would repeat the whole reply.
 */
function withoutDraft(rows: ActivityRow[], answer: string): ActivityRow[] {
  const target = comparable(answer);
  if (!target) return rows;
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    if (row.laneId !== null) continue;
    if (row.kind === "thinking" && row.mode === "reasoning") continue;
    if (row.kind !== "thinking") return rows;
    const probe = comparable(row.text).slice(0, 160);
    return probe.length >= 40 && target.startsWith(probe)
      ? [...rows.slice(0, i), ...rows.slice(i + 1)]
      : rows;
  }
  return rows;
}

function applyEvent(
  state: RunState,
  event: StreamEvent,
  at: number | null,
): RunState {
  const base = rowBase(state, event);
  const data = event.data as unknown;

  switch (event.type) {
    case "run_started": {
      const meta = data as RunStartedData;
      return { ...state, runId: event.run_id, meta, phase: "routing" };
    }
    case "route":
      return { ...state, route: data as RouteData, phase: "routing" };
    case "plan": {
      const plan = data as PlanData;
      let next: RunState = { ...state, plan, phase: "planning" };
      if (!plan.skipped) {
        for (const sub of plan.subquestions ?? []) {
          next = ensureLane(next, sub.id, sub.question, "pending");
        }
      }
      // A question answered directly needs no row: nothing was planned.
      if (plan.skipped || !plan.subquestions?.length) return next;
      return pushRow(next, {
        ...base,
        kind: "plan",
        skipped: Boolean(plan.skipped),
        reason: plan.reason ?? null,
        probability: plan.probability ?? null,
        subquestions: (plan.subquestions ?? []).map((sub) => ({
          id: sub.id,
          question: sub.question,
        })),
      });
    }
    case "worker_started": {
      const worker = data as WorkerData;
      return ensureLane(
        state,
        worker.worker_id,
        worker.question ?? "",
        "running",
      );
    }
    case "worker_done": {
      const worker = data as WorkerData;
      const failed = worker.status != null && worker.status !== "done";
      return ensureLane(
        state,
        worker.worker_id,
        worker.question ?? "",
        failed ? "failed" : "done",
      );
    }
    case "retrieval": {
      const retrieval = data as RetrievalData;
      const keys = retrieval.keys ?? [];
      return pushRow(
        {
          ...state,
          phase: "retrieving",
          evidenceKeys: uniqueAppend(state.evidenceKeys, keys),
        },
        {
          ...base,
          kind: "retrieval",
          source: retrieval.source ?? "pipeline",
          channels: retrieval.channels ?? {},
          kept: keys.length,
          reranker: retrieval.reranker ?? null,
          keys,
          queries: retrieval.queries ?? [],
        },
      );
    }
    case "thinking": {
      const thinking = data as ThinkingData;
      const mode = thinking.kind === "reasoning" ? "reasoning" : "text";
      // Workers stream at the same time, so their chunks interleave: the text
      // continues this lane's own latest row, not whichever row came last.
      const at = state.rows.findLastIndex((row) => row.laneId === event.worker_id);
      const last = at === -1 ? undefined : state.rows[at];
      if (last?.kind === "thinking" && last.mode === mode) {
        const merged: ThinkingRow = {
          ...last,
          text: (last.text + thinking.text).slice(-MAX_THINKING_CHARS),
        };
        const rows = [...state.rows];
        rows[at] = merged;
        return { ...state, phase: "thinking", rows };
      }
      return pushRow(
        { ...state, phase: "thinking" },
        {
          ...base,
          kind: "thinking",
          mode,
          text: thinking.text.slice(-MAX_THINKING_CHARS),
        },
      );
    }
    case "tool_call": {
      const call = data as ToolCallData;
      return pushRow(
        { ...state, phase: "tool" },
        {
          ...base,
          kind: "tool",
          callId: call.call_id ?? null,
          tool: call.tool,
          args: call.arguments ?? "",
          parsed: parseArgs(call.arguments),
          status: "running",
          failure: null,
          summary: null,
          resultCount: null,
          latencyMs: null,
          truncated: false,
          paths: [],
          output: null,
        },
      );
    }
    case "tool_result": {
      const result = data as ToolResultData;
      const ok = result.status === "ok";
      let matched = false;
      const rows = state.rows.map((row) => {
        if (matched || row.kind !== "tool" || row.status !== "running")
          return row;
        const same = result.call_id
          ? row.callId === result.call_id
          : row.tool === result.tool;
        if (!same) return row;
        matched = true;
        const done: ToolRow = {
          ...row,
          status: ok ? "ok" : "error",
          failure: ok ? null : result.status,
          summary: result.summary ?? null,
          resultCount: result.result_count ?? null,
          latencyMs: result.latency_ms ?? null,
          truncated: Boolean(result.truncated),
          output: result.output ?? null,
        };
        return done;
      });
      return matched ? { ...state, rows } : state;
    }
    case "nodes":
      return applyNodes(state, event, data as NodesData);
    case "evidence":
      return {
        ...state,
        evidenceKeys: uniqueAppend(
          state.evidenceKeys,
          (data as EvidenceData).keys ?? [],
        ),
      };
    case "answer_delta":
      return {
        ...state,
        phase: "answering",
        answer: state.answer + (data as { text: string }).text,
      };
    // Limits and fallbacks shape how the answer was reached, not what it says;
    // the answer itself reports anything the reader needs to know.
    case "degraded":
      return state;
    case "error": {
      const error = data as ErrorData;
      return {
        ...state,
        status: "error",
        phase: "finished",
        error: {
          message: error.message,
          kind: error.kind ?? "internal",
          status: error.status ?? null,
        },
        endedAt: at ?? state.endedAt,
      };
    }
    case "done": {
      const done = data as DoneData;
      const citations = done.citations ?? [];
      const answer = done.answer ?? state.answer;
      return {
        ...state,
        rows: withoutDraft(state.rows, answer),
        status: "done",
        phase: "finished",
        runId: done.run_id ?? state.runId,
        answer,
        citations,
        unresolved: done.unresolved ?? [],
        usage: done.usage ?? null,
        stopReason: done.stop_reason ?? null,
        limitsReached: done.limits_reached ?? [],
        chatMessageId: done.chat_message_id ?? null,
        endedAt: at ?? state.endedAt,
        highlight: {
          ...state.highlight,
          current: [],
          cited: citedPaths(citations),
        },
      };
    }
    default:
      return state;
  }
}

/**
 * Advances a run by one action.
 *
 * @param state - The current run state.
 * @param action - A lifecycle action or one streamed event.
 * @returns The next state; the same object when the action changes nothing.
 */
export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "reset":
      return initialRunState;
    case "start":
      return {
        ...initialRunState,
        status: "connecting",
        startedAt: action.at,
      };
    case "failed":
      return {
        ...state,
        status: "error",
        phase: "finished",
        error: {
          message: action.message,
          kind: action.kind ?? "http",
          status: action.status ?? null,
        },
      };
    case "cancelled":
      if (isTerminal(state.status)) return state;
      return { ...state, status: "cancelled", endedAt: action.at };
    case "connection_lost":
      if (isTerminal(state.status)) return state;
      return { ...state, status: "connection_lost", endedAt: action.at };
    case "event": {
      if (isTerminal(state.status) && state.status !== "connection_lost") {
        return state;
      }
      const { event } = action;
      const advanced: RunState =
        state.status === "connecting" || state.status === "connection_lost"
          ? { ...state, status: "live" }
          : state;
      const identified =
        advanced.runId || !event.run_id
          ? advanced
          : { ...advanced, runId: event.run_id };
      const next = applyEvent(identified, event, action.at ?? null);
      if (next === identified && identified === state) return state;
      return { ...next, lastSeq: Math.max(next.lastSeq, event.seq) };
    }
  }
}
