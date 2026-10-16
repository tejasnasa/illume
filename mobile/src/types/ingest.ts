/**
 * Shared types for the live ingestion progress view.
 * @module types/ingest
 */

/** Where a stage sits in its lifecycle, as published by the backend. */
export type Phase = "started" | "progress" | "done" | "failed";

/** How a pipeline node should render. */
export type NodeState = "pending" | "active" | "done" | "failed";

/** A single progress frame from the ingest WebSocket. */
export interface IngestFrame {
  event: string;
  message: string;
  timestamp: string;
  /**
   * Stage ids are typed loosely on purpose. The backend enum can grow
   * without breaking this build, and an unrecognised id is ignored rather
   * than thrown -- a newer worker must not blank the page.
   */
  stage?: string;
  phase?: string;
  processed?: number;
  total?: number;
  count?: number;
  status?: string;
}

/** The state of one stage plus the numbers behind it. */
export interface StageState {
  state: NodeState;
  /** Only the parse stage reports this; nothing else has a real counter. */
  progress?: { processed: number; total: number };
  /**
   * The structured total a stage published. Most stages report one of these
   * once, as a result rather than as a running count.
   */
  count?: number;
  /** The most recent human-readable line for this stage. */
  detail?: string;
}

/** Every stage id mapped to its state. */
export type StageStateMap = Record<string, StageState>;
