import { vi } from "vitest";

/** A response body the test writes to and closes by hand. */
export function controlledStream() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    stream,
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    close: () => controller.close(),
    fail: (reason: unknown) => controller.error(reason),
  };
}

export interface StreamRequest {
  url: string;
  init: RequestInit;
  body: Record<string, unknown>;
}

/**
 * Replaces `fetch` with a router for the chat page's endpoints.
 *
 * History and run-list calls answer from the given rows; the stream route is
 * delegated to `onStream`, which returns the response (or throws).
 */
export function installFetch(options: {
  history?: unknown[];
  runs?: unknown[];
  onStream?: (request: StreamRequest) => Response | Promise<Response>;
  /** Answers any other URL; return `undefined` to leave it unmocked. */
  onOther?: (url: string, init?: RequestInit) => Response | undefined;
}) {
  const requests: StreamRequest[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/chat/history")) return Response.json(options.history ?? []);
    if (url.includes("/agent-runs?")) return Response.json(options.runs ?? []);
    if (url.endsWith("/chat/stream") && options.onStream) {
      const request = {
        url,
        init: init ?? {},
        body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>,
      };
      requests.push(request);
      return options.onStream(request);
    }
    const other = options.onOther?.(url, init);
    if (other) return other;
    return new Response("not mocked", { status: 500 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, requests };
}

/** An SSE response backed by a controlled stream that errors when aborted. */
export function streamResponse(signal?: AbortSignal | null) {
  const body = controlledStream();
  signal?.addEventListener("abort", () =>
    body.fail(new DOMException("aborted", "AbortError")),
  );
  const response = new Response(body.stream, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
  return { response, ...body };
}
