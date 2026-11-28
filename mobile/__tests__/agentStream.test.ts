import { streamAgentRun } from "@/api/agentStream";
import type { StreamEvent } from "@/lib/agent/types";

const encoder = new TextEncoder();

/** A streaming response whose body is the given text chunks. */
function sseResponse(chunks: string[], status = 200): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, { status });
}

function frame(seq: number, type: string, data: Record<string, unknown> = {}) {
  const event: StreamEvent = {
    seq,
    ts: "2026-01-01T00:00:00Z",
    run_id: "run-1",
    worker_id: null,
    type,
    data,
  };
  return `data: ${JSON.stringify(event)}\n\n`;
}

const request = {
  question: "How does auth work?",
  preset: "deep_agent_workers" as const,
  history: [{ role: "user" as const, content: "hi" }],
};

describe("streamAgentRun", () => {
  it("posts the request with the bearer token to the stream route", async () => {
    const fetchImpl = jest.fn(async () => sseResponse([]));
    await streamAgentRun("repo-1", request, () => {}, {
      backendUrl: "http://api.test",
      getToken: async () => "jwt",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/api/v1/repository/repo-1/chat/stream");
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt");
    expect(headers.Accept).toBe("text/event-stream");
    expect(JSON.parse(String(init.body))).toEqual({
      question: "How does auth work?",
      history: [{ role: "user", content: "hi" }],
      preset: "deep_agent_workers",
    });
  });

  it("sends the conversation and overrides only when present", async () => {
    const fetchImpl = jest.fn(async () => sseResponse([]));
    await streamAgentRun(
      "repo-1",
      { ...request, conversationId: "c1", overrides: { agent: { max_iterations: 5 } } },
      () => {},
      {
        backendUrl: "http://api.test",
        getToken: async () => null,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      },
    );
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.conversation_id).toBe("c1");
    expect(body.overrides).toEqual({ agent: { max_iterations: 5 } });
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("delivers events even when chunk boundaries fall mid-frame", async () => {
    const text = frame(1, "run_started") + frame(2, "answer_delta", { text: "hi" });
    const cut = Math.floor(text.length / 3);
    const events: StreamEvent[] = [];
    const refusal = await streamAgentRun(
      "r",
      request,
      (e) => events.push(e),
      {
        backendUrl: "http://api.test",
        getToken: async () => null,
        fetchImpl: (async () =>
          sseResponse([
            text.slice(0, cut),
            text.slice(cut, cut * 2),
            text.slice(cut * 2),
          ])) as unknown as typeof fetch,
      },
    );
    expect(refusal).toBeNull();
    expect(events.map((e) => e.type)).toEqual(["run_started", "answer_delta"]);
  });

  it("skips malformed frames and keep-alive comments", async () => {
    const events: StreamEvent[] = [];
    await streamAgentRun("r", request, (e) => events.push(e), {
      backendUrl: "http://api.test",
      getToken: async () => null,
      fetchImpl: (async () =>
        sseResponse([": ping\n\n", "data: {not json\n\n", frame(1, "done")])) as unknown as typeof fetch,
    });
    expect(events).toHaveLength(1);
  });

  it("returns a refusal carrying the server message", async () => {
    const refusal = await streamAgentRun("r", request, () => {}, {
      backendUrl: "http://api.test",
      getToken: async () => null,
      fetchImpl: (async () =>
        new Response(JSON.stringify({ detail: "Free chat used up" }), {
          status: 402,
        })) as unknown as typeof fetch,
    });
    expect(refusal).toEqual({ status: 402, message: "Free chat used up" });
  });
});
