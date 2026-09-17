import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const REPO_ID = "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30";

const HISTORY_URL = `${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat/history`;
const ASK_URL = `${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat`;

const PERSISTED = [
  {
    id: "m1",
    repository_id: REPO_ID,
    user_id: "u1",
    question: "What does this do?",
    answer: "It reads files.",
    sources: [{ source_type: "symbol", chunk_text: "def f(): pass", file_path: "a.py" }],
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "m2",
    repository_id: REPO_ID,
    user_id: "u1",
    question: "And this?",
    answer: "It writes them.",
    sources: null,
    created_at: "2026-01-01T00:01:00Z",
  },
];

/** Registers the two endpoints the hook talks to. */
function stub({
  history = PERSISTED,
  askBody,
  askStatus = 200,
}: {
  history?: typeof PERSISTED;
  askBody?: JsonBodyType;
  askStatus?: number;
} = {}) {
  server.use(
    http.get(HISTORY_URL, () => HttpResponse.json(history)),
    http.post(ASK_URL, () =>
      askBody === undefined
        ? HttpResponse.json({
            id: "m3",
            answer: "A fresh answer.",
            sources: [{ source_type: "commit", chunk_text: "abc123", commit_hash: "abc1234" }],
          })
        : HttpResponse.json(askBody, { status: askStatus }),
    ),
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("history loading", () => {
  it("maps persisted turns into messages", async () => {
    stub();
    const { useChat } = await import("@/hooks/useChat");

    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages[0].question).toBe("What does this do?");
    expect(result.current.messages[0].answer?.answer).toBe("It reads files.");
  });

  it("carries the citations through", async () => {
    // Sources arrive as JSONB and reload with the history; losing them here would leave
    // the citation cards empty after a refresh even though the answer text survived.
    stub();
    const { useChat } = await import("@/hooks/useChat");

    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages[0].answer?.sources).toEqual(PERSISTED[0].sources);
  });

  it("coerces a null sources column to an empty array", async () => {
    // The column is nullable and old rows have no sources, but the type is a list and
    // CitationCard maps over it -- `null.map` would throw during render.
    stub();
    const { useChat } = await import("@/hooks/useChat");

    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages[1].answer?.sources).toEqual([]);
  });

  it("starts empty for a repository with no history", async () => {
    stub({ history: [] });
    const { useChat } = await import("@/hooks/useChat");

    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));

    await waitFor(() => expect(result.current.messages).toEqual([]));
  });

  it("does not throw when the history request fails", async () => {
    // A 500 is not an error as far as this effect is concerned: `res.ok` is false, the
    // `if` body is skipped, and nothing is logged. The panel renders empty with no
    // indication that a request failed -- indistinguishable from a repository with no
    // history. An unhandled rejection would be worse (it would fail the route render), so
    // this is the safer of the two, but it is silent.
    server.use(http.get(HISTORY_URL, () => new HttpResponse(null, { status: 500 })));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { useChat } = await import("@/hooks/useChat");

    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));

    await waitFor(() => expect(result.current.messages).toEqual([]));
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("logs when the history request cannot be made at all", async () => {
    // The contrast that makes the case above concrete: only a thrown fetch reaches the
    // catch, so a network failure is reported and an HTTP error is not.
    server.use(http.get(HISTORY_URL, () => HttpResponse.error()));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { useChat } = await import("@/hooks/useChat");

    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));

    await waitFor(() => expect(consoleError).toHaveBeenCalled());
    expect(result.current.messages).toEqual([]);
  });

  it("reloads when the repository changes", async () => {
    stub();
    const { useChat } = await import("@/hooks/useChat");

    const { result, rerender } = renderHook(({ repoId }) => useChat({ repoId }), {
      initialProps: { repoId: REPO_ID },
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    const other = "11111111-2222-3333-4444-555555555555";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${other}/chat/history`, () =>
        HttpResponse.json([]),
      ),
    );
    rerender({ repoId: other });

    await waitFor(() => expect(result.current.messages).toEqual([]));
  });
});

describe("sending", () => {
  it("adds an optimistic turn before the answer arrives", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json([])),
      http.post(ASK_URL, async () => {
        await gate;
        return HttpResponse.json({ id: "m3", answer: "An answer.", sources: [] });
      }),
    );
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    act(() => {
      void result.current.sendMessage("A question");
    });

    // The bubble is on screen immediately, with no answer yet.
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]).toMatchObject({ question: "A question", answer: null });
    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      release();
    });
  });

  it("replaces the placeholder with the answer", async () => {
    stub({ history: [] });
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("A question");
    });

    expect(result.current.messages[0].answer?.answer).toBe("A fresh answer.");
    expect(result.current.messages[0].error).toBeUndefined();
  });

  it("adopts the server's id for the turn", async () => {
    // The client's placeholder id is a local UUID; the delete endpoint needs the
    // persisted id, so the swap has to happen or deletion 404s.
    stub({ history: [] });
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("A question");
    });

    expect(result.current.messages[0].id).toBe("m3");
  });

  it("clears the loading flag", async () => {
    stub({ history: [] });
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("A question");
    });

    expect(result.current.isLoading).toBe(false);
  });

  it("ignores an empty question", async () => {
    const spy = vi.fn();
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json([])),
      http.post(ASK_URL, () => {
        spy();
        return HttpResponse.json({ id: "m3", answer: "x", sources: [] });
      }),
    );
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("   ");
    });

    expect(spy).not.toHaveBeenCalled();
    expect(result.current.messages).toEqual([]);
  });

  it("ignores a question sent while one is in flight", async () => {
    // `isLoading` is in the callback's dependency list, so the guard closes over the
    // current value rather than a stale one.
    const spy = vi.fn();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json([])),
      http.post(ASK_URL, async () => {
        spy();
        await gate;
        return HttpResponse.json({ id: "m3", answer: "x", sources: [] });
      }),
    );
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    act(() => {
      void result.current.sendMessage("First");
    });
    await waitFor(() => expect(result.current.isLoading).toBe(true));

    await act(async () => {
      await result.current.sendMessage("Second");
    });

    expect(spy).toHaveBeenCalledTimes(1);

    await act(async () => {
      release();
    });
  });

  it("marks the turn as failed and keeps it visible", async () => {
    // The bubble stays with `error: true` so the user can see what they asked and retry,
    // rather than the question vanishing.
    stub({ history: [], askBody: { detail: "boom" }, askStatus: 500 });
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("A question");
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].error).toBe(true);
    expect(result.current.messages[0].question).toBe("A question");
  });

  it("shows a retryable message on failure", async () => {
    stub({ history: [], askBody: {}, askStatus: 500 });
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("A question");
    });

    expect(result.current.messages[0].answer?.answer).toBe("Failed to get response. Try again.");
  });

  it("clears the loading flag after a failure", async () => {
    // A stuck spinner would block every subsequent send through the isLoading guard.
    stub({ history: [], askBody: {}, askStatus: 500 });
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("A question");
    });

    expect(result.current.isLoading).toBe(false);
  });
});

describe("forwarded history", () => {
  /** The parsed body of the next ask request. */
  function captureBody() {
    const captured = { body: null as { question: string; history: unknown[] } | null };
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json(PERSISTED)),
      http.post(ASK_URL, async ({ request }) => {
        captured.body = (await request.json()) as { question: string; history: unknown[] };
        return HttpResponse.json({ id: "m3", answer: "ok", sources: [] });
      }),
    );
    return captured;
  }

  it("sends prior turns as alternating roles", async () => {
    // Built from the current `messages`, not from inside the `setMessages` updater: React
    // invokes an updater during the *next render*, so a value assigned inside one is still
    // the initial `[]` when the body is serialized. Every follow-up therefore reached the
    // server with no prior context and was answered as though it were the first question.
    const captured = captureBody();
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.sendMessage("A follow-up");
    });

    expect(captured.body?.history).toEqual([
      { role: "user", content: "What does this do?" },
      { role: "assistant", content: "It reads files." },
      { role: "user", content: "And this?" },
      { role: "assistant", content: "It writes them." },
    ]);
  });

  it("excludes the question being asked from the history", async () => {
    // The new turn is sent as `question`, so including it in `history` too would duplicate
    // it -- and it has no answer yet, so it cannot form a user/assistant pair.
    const captured = captureBody();
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.sendMessage("A follow-up");
    });

    expect(captured.body?.history).not.toContainEqual(
      expect.objectContaining({ content: "A follow-up" }),
    );
  });

  it("sends the raw question in the body", async () => {
    const captured = captureBody();
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.sendMessage("A follow-up");
    });

    expect(captured.body?.question).toBe("A follow-up");
  });

  it("excludes turns that failed", async () => {
    // A failed turn's answer is the retry placeholder, and feeding that back as an
    // assistant message would poison the next prompt with text the model never wrote.
    const captured = { body: null as { history: unknown[] } | null };
    let call = 0;
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json([])),
      http.post(ASK_URL, async ({ request }) => {
        captured.body = (await request.json()) as { history: unknown[] };
        call += 1;
        return call === 1
          ? HttpResponse.json({}, { status: 500 })
          : HttpResponse.json({ id: "m3", answer: "ok", sources: [] });
      }),
    );
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      await result.current.sendMessage("This one fails");
    });
    await act(async () => {
      await result.current.sendMessage("This one works");
    });

    expect(captured.body?.history).toEqual([]);
  });
});

describe("deleting", () => {
  it("removes the message locally", async () => {
    stub();
    server.use(
      http.delete(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat/:id`, () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.deleteMessage("m1");
    });

    expect(result.current.messages.map((m) => m.id)).toEqual(["m2"]);
  });

  it("deletes the persisted turn on the server", async () => {
    const spy = vi.fn();
    stub();
    server.use(
      http.delete(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat/:id`, ({ params }) => {
        spy(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.deleteMessage("m1");
    });

    expect(spy).toHaveBeenCalledWith("m1");
  });

  it("keeps the removal when the server call fails", async () => {
    // Deletion is optimistic and never rolled back, so a failed request leaves the UI out
    // of sync with the server until the next reload.
    //
    // A 500 is not reported, only a thrown fetch: the hook awaits the response and never
    // checks `res.ok`, so an HTTP error passes through unnoticed. Compare the network
    // case below, which does log.
    stub();
    server.use(
      http.delete(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat/:id`, () =>
        new HttpResponse(null, { status: 500 }),
      ),
    );
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.deleteMessage("m1");
    });

    expect(result.current.messages.map((m) => m.id)).toEqual(["m2"]);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("logs when the delete request cannot be made", async () => {
    stub();
    server.use(
      http.delete(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat/:id`, () =>
        HttpResponse.error(),
      ),
    );
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.deleteMessage("m1");
    });

    expect(consoleError).toHaveBeenCalled();
    expect(result.current.messages.map((m) => m.id)).toEqual(["m2"]);
  });

  it("does nothing for an id that is not present", async () => {
    const spy = vi.fn();
    stub();
    server.use(
      http.delete(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat/:id`, () => {
        spy();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.deleteMessage("does-not-exist");
    });

    expect(spy).not.toHaveBeenCalled();
    expect(result.current.messages).toHaveLength(2);
  });
});

describe("clearing", () => {
  it("empties the message list", async () => {
    stub();
    server.use(
      http.delete(ASK_URL, () => new HttpResponse(null, { status: 204 })),
    );
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.clearHistory();
    });

    expect(result.current.messages).toEqual([]);
  });

  it("deletes without a message id in the path", async () => {
    // `DELETE /chat` clears everything; `DELETE /chat/{id}` removes one turn. The two
    // differ only by a trailing segment, so a built path is worth asserting on.
    let path = "";
    stub();
    server.use(
      http.delete(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat`, ({ request }) => {
        path = new URL(request.url).pathname;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.clearHistory();
    });

    expect(path).toBe(`/api/v1/repository/${REPO_ID}/chat`);
  });

  it("keeps the list empty when the server call fails", async () => {
    stub();
    server.use(http.delete(ASK_URL, () => new HttpResponse(null, { status: 500 })));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.clearHistory();
    });

    // Cleared locally and gone from the screen, but still on the server -- so a reload
    // brings the whole conversation back.
    expect(result.current.messages).toEqual([]);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("logs when the clear request cannot be made", async () => {
    stub();
    server.use(http.delete(ASK_URL, () => HttpResponse.error()));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { useChat } = await import("@/hooks/useChat");
    const { result } = renderHook(() => useChat({ repoId: REPO_ID }));
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.clearHistory();
    });

    expect(consoleError).toHaveBeenCalled();
  });
});
