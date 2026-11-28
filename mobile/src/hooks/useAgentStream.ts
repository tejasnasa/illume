/**
 * Streams an agent run from the server.
 *
 * @module UseAgentStream
 *
 * Port of ``client/src/hooks/useAgentStream.ts``. The reducer and the event
 * parser are the web version, copied by hand; only the transport differs.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";

import {
  streamAgentRun,
  type HistoryMessage,
  type StreamOptions,
} from "@/api/agentStream";
import {
  initialRunState,
  isTerminal,
  runReducer,
  type RunState,
} from "@/lib/agent/reducer";
import type { Overrides, PresetChoice } from "@/lib/agent/presets";

export type { HistoryMessage };

export interface StartArgs {
  repoId: string;
  question: string;
  preset: PresetChoice;
  overrides?: Overrides;
  history: HistoryMessage[];
  /** The conversation the answer joins; omitted, the server starts one. */
  conversationId?: string | null;
}

/**
 * Owns the state of one run and the connection feeding it.
 *
 * The request is cancelled on unmount, and a run that ends without a
 * terminal event settles as `connection_lost`.
 *
 * @param transport - Test seams for the stream request.
 * @returns The run state and the actions that drive it.
 */
export function useAgentStream(transport: StreamOptions = {}) {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const abortRef = useRef<AbortController | null>(null);
  const transportRef = useRef(transport);
  transportRef.current = transport;

  useEffect(() => () => abortRef.current?.abort(), []);

  /** Streams a new run. Resolves when the connection closes. */
  const start = useCallback(
    async ({
      repoId,
      question,
      preset,
      overrides,
      history,
      conversationId,
    }: StartArgs) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      dispatch({ type: "start", at: Date.now() });

      let sawTerminal = false;
      try {
        const refusal = await streamAgentRun(
          repoId,
          { question, preset, overrides, history, conversationId },
          (event) => {
            if (controller.signal.aborted) return;
            if (event.type === "done" || event.type === "error") {
              sawTerminal = true;
            }
            dispatch({ type: "event", event, at: Date.now() });
          },
          { ...transportRef.current, signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        if (refusal) {
          dispatch({
            type: "failed",
            message: refusal.message,
            status: refusal.status,
          });
          return;
        }
        if (!sawTerminal) dispatch({ type: "connection_lost", at: Date.now() });
      } catch {
        if (controller.signal.aborted) return;
        if (!sawTerminal) dispatch({ type: "connection_lost", at: Date.now() });
      }
    },
    [],
  );

  /** Aborts the request and settles the run as cancelled. */
  const stop = useCallback(() => {
    abortRef.current?.abort();
    dispatch({ type: "cancelled", at: Date.now() });
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    dispatch({ type: "reset" });
  }, []);

  return {
    state: state as RunState,
    isLive: !isTerminal(state.status) && state.status !== "idle",
    start,
    stop,
    reset,
  };
}
