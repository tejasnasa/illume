/**
 * Streams an agent run from the server.
 * @module UseAgentStream
 */
"use client";

import apiError from "@/lib/apiError";
import {
  initialRunState,
  isTerminal,
  runReducer,
  type RunState,
} from "@/lib/agent/reducer";
import type { Overrides, PresetId } from "@/lib/agent/presets";
import { SseParser } from "@/lib/agent/sse";
import type { StreamEvent } from "@/lib/agent/types";
import { useCallback, useEffect, useReducer, useRef } from "react";

/** A prior turn sent back so a follow-up stays grounded. */
export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface StartArgs {
  repoId: string;
  question: string;
  preset: PresetId;
  overrides?: Overrides;
  history: HistoryMessage[];
}

const BACKEND = () => process.env.NEXT_PUBLIC_BACKEND_URL;

/**
 * Owns the state of one run and the connection feeding it.
 *
 * `start` POSTs to the stream route and reads the body with a decoder stream,
 * since `EventSource` cannot send a body. The request is cancelled on unmount.
 *
 * @returns The run state and the actions that drive it.
 */
export function useAgentStream() {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  /** Streams a new run. Resolves when the connection closes. */
  const start = useCallback(
    async ({ repoId, question, preset, overrides, history }: StartArgs) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      dispatch({ type: "start", at: Date.now() });

      let sawTerminal = false;
      try {
        const res = await fetch(
          `${BACKEND()}/api/v1/repository/${repoId}/chat/stream`,
          {
            method: "POST",
            credentials: "include",
            headers: {
              "Content-Type": "application/json",
              Accept: "text/event-stream",
            },
            body: JSON.stringify({
              question,
              history,
              preset,
              ...(overrides ? { overrides } : {}),
            }),
            signal: controller.signal,
          },
        );

        if (!res.ok || !res.body) {
          const error = await apiError(res, "Failed to get response.");
          dispatch({
            type: "failed",
            message: error.message,
            status: res.status,
          });
          return;
        }

        const reader = res.body
          .pipeThrough(new TextDecoderStream())
          .getReader();
        const parser = new SseParser();

        const feed = (messages: ReturnType<SseParser["push"]>) => {
          for (const message of messages) {
            let event: StreamEvent;
            try {
              event = JSON.parse(message.data) as StreamEvent;
            } catch {
              continue;
            }
            if (!event || typeof event.type !== "string") continue;
            if (event.type === "done" || event.type === "error") {
              sawTerminal = true;
            }
            dispatch({ type: "event", event, at: Date.now() });
          }
        };

        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          feed(parser.push(value));
        }
        feed(parser.flush());

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
