/**
 * Live ingestion frame stream over the backend WebSocket.
 *
 * @module useIngestStream
 *
 * Port of ``client/src/hooks/useIngestStream.ts``. Transport only: it owns
 * the socket and normalises what arrives into a uniform frame shape.
 * Anything that decides what a frame *means* -- the refresh policy, the
 * terminal markers -- belongs to the component, so the same stream can feed
 * both the flow canvas and the raw-log drawer without opening a second
 * connection.
 *
 * React Native ships a global ``WebSocket``, and the endpoint already
 * accepts the token as a query parameter, so this file needed no more than
 * a different URL builder.
 */

import { useCallback, useEffect, useState } from "react";

import { ingestSocketUrl } from "@/api/ingest";
import type { IngestFrame } from "@/types/ingest";

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

/** Props for {@link useIngestStream}. */
export interface UseIngestStreamProps {
  /** Repository whose log channel to subscribe to. */
  repoId: string;
  /** Auth token passed as a WebSocket query parameter. */
  token: string;
  /**
   * When false, no socket is opened and the stream stays empty. For callers
   * that supply their own frames and must not also open a connection to a
   * repository that may not exist.
   */
  enabled?: boolean;
  /**
   * Override for the backend base URL. Used by tests; production callers
   * leave it unset and the configured backend is used.
   */
  backendUrl?: string;
}

/** Build a frame for something that did not arrive as one. */
function synthetic(message: string, event = "info"): IngestFrame {
  return { event, message, timestamp: new Date().toISOString() };
}

/**
 * Subscribe to a repository's ingestion channel.
 *
 * @param props - The repository, the token, and whether to connect at all.
 * @returns The frame stream and its connection state.
 */
export function useIngestStream({
  repoId,
  token,
  enabled = true,
  backendUrl,
}: UseIngestStreamProps): IngestStream {
  const [frames, setFrames] = useState<IngestFrame[]>([]);
  const [connected, setConnected] = useState(false);
  const [closed, setClosed] = useState(false);
  const [generation, setGeneration] = useState(0);

  const reconnect = useCallback(() => setGeneration((value) => value + 1), []);

  useEffect(() => {
    if (!enabled) return;
    // Some environments (a test runner, a bare Node context) have no
    // WebSocket at all. Opening one there throws, and the caller has
    // nothing better to show than the static view.
    if (typeof WebSocket === "undefined") return;

    const wsUrl = ingestSocketUrl(repoId, token, backendUrl);
    const ws = new WebSocket(wsUrl);

    /**
     * True once this socket has been superseded or unmounted.
     *
     * Every handler checks it, not just the frame path: a socket replaced by
     * a reconnect still fires ``onclose`` for itself, and letting that
     * through would report the *new* connection as closed.
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
  }, [repoId, token, generation, enabled, backendUrl]);

  return { frames, connected, closed, reconnect };
}
