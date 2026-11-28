/**
 * The streaming chat endpoint.
 *
 * @module AgentStreamApi
 *
 * `POST /api/v1/repository/{repo_id}/chat/stream` answers with server-sent
 * events. React Native's built-in `fetch` buffers the whole response before
 * handing it over, so nothing would arrive until the run had finished; the
 * `fetch` exported by `expo/fetch` exposes the body as a stream instead.
 * That is the one place in the app that does not go through
 * {@link apiRequest}, because a JSON wrapper cannot carry a stream.
 */

import { resolveBackendUrl } from "@/api/client";
import { SseParser } from "@/lib/agent/sse";
import type { Overrides, PresetChoice } from "@/lib/agent/presets";
import type { StreamEvent } from "@/lib/agent/types";
import { getAccessToken } from "@/lib/tokenStore";

/** A prior turn sent back so a follow-up stays grounded. */
export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

/** The request body of one streamed run. */
export interface StreamRequest {
  question: string;
  preset: PresetChoice;
  overrides?: Overrides;
  history: HistoryMessage[];
  /** The conversation the answer joins; omitted, the server starts one. */
  conversationId?: string | null;
}

/** Transport overrides; production callers pass none. */
export interface StreamOptions {
  signal?: AbortSignal;
  backendUrl?: string;
  getToken?: () => Promise<string | null>;
  fetchImpl?: typeof fetch;
}

/** How a stream request ended before any event was read. */
export interface StreamRefusal {
  status: number;
  message: string;
}

/**
 * The streaming `fetch`, resolved on first use so a test that injects its
 * own never loads the native-backed module.
 *
 * @returns Expo's streaming fetch.
 */
function streamingFetch(): typeof fetch {
  return (require("expo/fetch") as { fetch: unknown }).fetch as typeof fetch;
}

/**
 * Pull a readable message out of an error body.
 *
 * @param text - The raw response text.
 * @param fallback - Used when the body carries nothing useful.
 * @returns The message.
 */
function refusalMessage(text: string, fallback: string): string {
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail) return parsed.detail;
  } catch {
    // Not JSON; fall through.
  }
  return fallback;
}

/**
 * Run one streamed request and hand every event to `onEvent`.
 *
 * @param repoId - The repository UUID.
 * @param request - The question, preset and history.
 * @param onEvent - Called for each well-formed event, in order.
 * @param options - Abort signal and test seams.
 * @returns A refusal when the server answered with an error status, otherwise
 *   null once the connection has closed. A dropped connection throws.
 */
export async function streamAgentRun(
  repoId: string,
  request: StreamRequest,
  onEvent: (event: StreamEvent) => void,
  options: StreamOptions = {},
): Promise<StreamRefusal | null> {
  const { signal, backendUrl, getToken = getAccessToken } = options;
  const doFetch = options.fetchImpl ?? streamingFetch();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = await getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await doFetch(
    `${resolveBackendUrl(backendUrl)}/api/v1/repository/${repoId}/chat/stream`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        question: request.question,
        history: request.history,
        ...(request.conversationId
          ? { conversation_id: request.conversationId }
          : {}),
        preset: request.preset,
        ...(request.overrides ? { overrides: request.overrides } : {}),
      }),
      signal,
    },
  );

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    return {
      status: res.status,
      message: refusalMessage(text, "Failed to get response."),
    };
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
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
      onEvent(event);
    }
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    feed(parser.push(decoder.decode(value, { stream: true })));
  }
  feed(parser.push(decoder.decode()));
  feed(parser.flush());
  return null;
}
