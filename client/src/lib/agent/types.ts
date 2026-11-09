/**
 * Wire types for the streaming chat endpoint.
 *
 * Mirrors the event envelope and the per-type payloads the server publishes
 * (`app/services/agent/events.py`). Every payload field the client reads is
 * optional-tolerant, because the server may add fields and events before the
 * client learns about them.
 * @module AgentTypes
 */

/** The public event types the reducer understands. */
export const EVENT_TYPES = [
  "run_started",
  "route",
  "plan",
  "worker_started",
  "worker_done",
  "retrieval",
  "thinking",
  "tool_call",
  "tool_result",
  "nodes",
  "evidence",
  "answer_delta",
  "degraded",
  "error",
  "done",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

/** The envelope every streamed event travels in. */
export interface StreamEvent<T = Record<string, unknown>> {
  seq: number;
  ts: string;
  run_id: string;
  worker_id: string | null;
  /** Kept as a string so an event type added by the server parses and is ignored. */
  type: string;
  data: T;
}

export interface RunStartedData {
  preset: string;
  config_hash: string;
  model: string;
  execution: string;
}

export interface RouteData {
  route: string;
  probabilities?: Record<string, number>;
  confidence?: number | null;
  fell_back?: boolean;
  model?: string | null;
}

export interface SubQuestion {
  id: string;
  question: string;
  focus?: string;
}

export interface PlanData {
  skipped?: boolean;
  reason?: string | null;
  probability?: number | null;
  threshold?: number | null;
  model?: string | null;
  subquestions?: SubQuestion[];
  synthesis_hint?: string;
}

export interface WorkerData {
  worker_id: string;
  question?: string | null;
  status?: string | null;
  stop_reason?: string | null;
}

/** One phrasing of the question a retrieval searched with. */
export interface QueryData {
  text: string;
  /** `original`, `condensed`, `multi_query` or `hyde`. */
  kind: string;
}

export interface RetrievalData {
  source?: string;
  standalone_question?: string | null;
  channels?: Record<string, number>;
  keys?: string[];
  reranker?: string | null;
  queries?: QueryData[];
}

export interface ThinkingData {
  iteration?: number | null;
  text: string;
  /** `reasoning` for the model's chain of thought, `text` for what it said. */
  kind?: "text" | "reasoning";
}

export interface ToolCallData {
  call_id?: string | null;
  tool: string;
  arguments?: string;
}

export interface ToolResultData {
  call_id?: string | null;
  tool: string;
  status: string;
  summary?: string | null;
  result_count?: number | null;
  truncated?: boolean;
  latency_ms?: number;
  error_type?: string | null;
  /** What the tool returned, cut to a readable length. */
  output?: string | null;
}

export interface NodesData {
  call_id?: string | null;
  tool?: string | null;
  paths?: string[];
  action?: string | null;
}

export interface EvidenceData {
  keys: string[];
}

export interface AnswerDeltaData {
  text: string;
}

export interface DegradedData {
  stage: string;
  limit?: string | null;
  used?: number | null;
  allowed?: number | null;
  reason?: string | null;
  detail?: Record<string, unknown>;
}

export interface ErrorData {
  message: string;
  kind?: string;
  status?: number;
}

/** One piece of evidence behind an answer, in the shape chat history stores. */
export interface Citation {
  key?: string | null;
  source_type: string;
  chunk_text: string;
  file_path: string | null;
  symbol_name: string | null;
  start_line: number | null;
  end_line: number | null;
  commit_hash: string | null;
  author_name: string | null;
  pr_number: number | null;
  pr_title: string | null;
}

export interface Usage {
  input_tokens?: number;
  output_tokens?: number;
  tool_calls?: number;
  iterations?: number;
  elapsed_seconds?: number;
}

export interface DoneData {
  run_id: string;
  status?: string;
  answer: string;
  citations?: Partial<Citation>[];
  unresolved?: string[];
  stop_reason?: string;
  usage?: Usage;
  chat_message_id?: string | null;
  steps_dropped?: number;
  limits_reached?: string[];
}

/** One run as the list endpoint returns it. */
export interface AgentRunSummary {
  id: string;
  question: string;
  preset: string;
  status: string;
  chat_message_id: string | null;
  tool_calls?: number | null;
  latency_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  created_at: string;
}
