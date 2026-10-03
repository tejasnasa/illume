/**
 * Live ingestion frame stream over the backend WebSocket.
 *
 * Transport only: it owns the socket and normalises what arrives into a
 * uniform frame shape. Anything that decides what a frame *means* -- the
 * refresh policy, the terminal markers -- belongs to the component, so the
 * same stream can feed both the flow canvas and the raw-log drawer without
 * opening a second connection.
 *
 * @module hooks/useIngestStream
 */

"use client";

import type { IngestFrame } from "@/types/ingest";
import { useCallback, useEffect, useState } from "react";

/** What the stream exposes to its consumers. */
export interface IngestStream {
  /** Every line, oldest first, including synthetic connection notices. */
  frames: IngestFrame[];
  /** True between the socket opening and it closing. */
  connected: boolean;
  /** True once the socket has closed, for any reason. */
  closed: boolean;
  /** Drop the current socket and open a fresh one, keeping the frames so far. */
  reconnect: () => void;
}

/** Build a frame for something that did not arrive as one. */
function synthetic(message: string, event = "info"): IngestFrame {
  return { event, message, timestamp: new Date().toISOString() };
}

/**
 * Subscribe to a repository's ingestion channel.
 *
 * @param repoId - Repository whose log channel to subscribe to.
 * @param token - Auth token passed as a WebSocket query parameter.
 * @param enabled - When false, no socket is opened and the stream stays
 *   empty. For callers that supply their own frames and must not also open a
 *   connection to a repository that may not exist.
 * @returns The frame stream and its connection state.
 */
export function useIngestStream({
  repoId,
  token,
  enabled = true,
}: {
  repoId: string;
  token: string;
  enabled?: boolean;
}): IngestStream {
  const [frames, setFrames] = useState<IngestFrame[]>([]);
  const [connected, setConnected] = useState(false);
  const [closed, setClosed] = useState(false);
  const [generation, setGeneration] = useState(0);

  const reconnect = useCallback(() => setGeneration((value) => value + 1), []);

  useEffect(() => {
    if (!enabled) return;

    const wsUrl =
      process.env.NEXT_PUBLIC_BACKEND_URL!.replace(/^http/, "ws") +
      `/api/v1/ws/ingest/${repoId}?token=${token}`;

    const ws = new WebSocket(wsUrl);

    /**
     * True once this socket has been superseded or unmounted.
     *
     * Every handler checks it, not just the frame path: a socket replaced by a
     * reconnect still fires `onclose` for itself, and letting that through
     * would report the *new* connection as closed.
     */
    let cancelled = false;

    const push = (frame: IngestFrame) => {
      if (cancelled) return;
      setFrames((prev) => [...prev, frame]);
    };

    ws.onopen = () => {
      if (cancelled) return;
      setConnected(true);
      setClosed(false);
      push(synthetic("Connected. Waiting for worker...", "system"));
    };

    ws.onmessage = (event) => {
      const data: string = event.data;
      try {
        const parsed = JSON.parse(data);
        push({
          event: parsed.event ?? "info",
          message: parsed.message ?? data,
          timestamp: parsed.timestamp ?? new Date().toISOString(),
          stage: parsed.stage,
          phase: parsed.phase,
          processed: parsed.processed,
          total: parsed.total,
          count: parsed.count,
          status: parsed.status,
        });
      } catch {
        // A frame that is not JSON still renders, as itself.
        push(synthetic(data));
      }
    };

    ws.onerror = () => push(synthetic("WebSocket connection error.", "error"));

    ws.onclose = () => {
      if (cancelled) return;
      setClosed(true);
      setConnected(false);
      push(synthetic("Connection closed.", "system"));
    };

    return () => {
      cancelled = true;
      ws.close();
    };
  }, [repoId, token, generation, enabled]);

  return { frames, connected, closed, reconnect };
}
