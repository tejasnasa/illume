import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useConversationList } from "@/hooks/useConversationList";
import type { ConversationSummary } from "@/types/conversation";

const item = (id: string, title: string): ConversationSummary => ({
  id,
  title,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  message_count: 1,
});

function mockFetch(answer: (url: string, init?: RequestInit) => Response) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    answer(String(input), init),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useConversationList", () => {
  it("loads the list for the repository", async () => {
    const fetchMock = mockFetch(() =>
      Response.json([item("a", "First"), item("b", "Second")]),
    );

    const { result } = renderHook(() => useConversationList("repo-1"));

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.items.map((i) => i.title)).toEqual([
      "First",
      "Second",
    ]);
    expect(fetchMock.mock.calls[0][0]).toMatch(
      /\/repository\/repo-1\/conversations$/,
    );
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      credentials: "include",
    });
  });

  it("renames optimistically with a PATCH", async () => {
    const fetchMock = mockFetch((_, init) =>
      init?.method === "PATCH"
        ? Response.json({})
        : Response.json([item("a", "First")]),
    );
    const { result } = renderHook(() => useConversationList("repo-1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    let accepted = false;
    await act(async () => {
      accepted = await result.current.rename("a", "  Renamed  ");
    });

    expect(accepted).toBe(true);
    expect(result.current.items[0].title).toBe("Renamed");
    const patch = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "PATCH",
    )!;
    expect(String(patch[0])).toMatch(/\/conversations\/a$/);
    expect(JSON.parse(String(patch[1]?.body))).toEqual({ title: "Renamed" });
  });

  it("puts the title back when the server refuses, and never sends a blank or over-long one", async () => {
    const fetchMock = mockFetch((_, init) =>
      init?.method === "PATCH"
        ? new Response("{}", { status: 422 })
        : Response.json([item("a", "First")]),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useConversationList("repo-1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    await act(async () => {
      expect(await result.current.rename("a", "Nope")).toBe(false);
    });
    expect(result.current.items[0].title).toBe("First");

    const sent = fetchMock.mock.calls.length;
    await act(async () => {
      expect(await result.current.rename("a", "   ")).toBe(false);
      expect(await result.current.rename("a", "x".repeat(121))).toBe(false);
    });
    expect(fetchMock.mock.calls.length).toBe(sent);
  });

  it("removes optimistically and restores the row when the delete fails", async () => {
    let failing = true;
    mockFetch((_, init) => {
      if (init?.method === "DELETE") {
        return failing
          ? new Response("{}", { status: 500 })
          : new Response(null, { status: 204 });
      }
      return Response.json([item("a", "First"), item("b", "Second")]);
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useConversationList("repo-1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    await act(async () => {
      expect(await result.current.remove("a")).toBe(false);
    });
    expect(result.current.items.map((i) => i.id)).toEqual(["a", "b"]);

    failing = false;
    await act(async () => {
      expect(await result.current.remove("a")).toBe(true);
    });
    expect(result.current.items.map((i) => i.id)).toEqual(["b"]);
  });

  it("refresh re-reads the list", async () => {
    let titles = ["First"];
    mockFetch(() => Response.json(titles.map((t, i) => item(String(i), t))));
    const { result } = renderHook(() => useConversationList("repo-1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));

    titles = ["Newest", "First"];
    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.items.map((i) => i.title)).toEqual([
      "Newest",
      "First",
    ]);
  });
});
