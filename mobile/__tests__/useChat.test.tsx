/**
 * Tests for the chat hook.
 *
 * The hook owns the behaviour a reader notices: a turn that appears
 * before its answer does, a turn that stays on the screen when it fails,
 * and deletions that are not undone by a failed request. The transport
 * is mocked so the cases are about the hook rather than about the
 * network.
 */

import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ApiError } from "@/lib/apiError";
import { useChat } from "@/hooks/useChat";
import {
  clearChatHistory,
  deleteChatMessage,
  getChatHistory,
  postChatQuestion,
  type ChatResponse,
} from "@/api/chat";

jest.mock("@/api/chat", () => ({
  getChatHistory: jest.fn(),
  postChatQuestion: jest.fn(),
  deleteChatMessage: jest.fn(),
  clearChatHistory: jest.fn(),
}));

const getChatHistoryMock = getChatHistory as jest.MockedFunction<
  typeof getChatHistory
>;
const postChatQuestionMock = postChatQuestion as jest.MockedFunction<
  typeof postChatQuestion
>;
const deleteChatMessageMock = deleteChatMessage as jest.MockedFunction<
  typeof deleteChatMessage
>;
const clearChatHistoryMock = clearChatHistory as jest.MockedFunction<
  typeof clearChatHistory
>;

/** The repository the chat belongs to. */
const REPO_ID = "repo-1";

/**
 * Build a stored history row.
 *
 * @param overrides - The fields the test cares about.
 * @returns The row.
 */
function makeHistoryRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "turn-1",
    repository_id: REPO_ID,
    user_id: "user-1",
    question: "What does the pipeline do?",
    answer: "It clones, parses and scores.",
    sources: [],
    created_at: "2026-01-15T12:00:00Z",
    ...overrides,
  } as Awaited<ReturnType<typeof getChatHistory>>[number];
}

/**
 * Build an answer payload.
 *
 * @param overrides - The fields the test cares about.
 * @returns The payload.
 */
function makeResponse(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    id: "turn-2",
    answer: "It clones, parses and scores.",
    sources: [],
    ...overrides,
  };
}

/**
 * A query client with the retries turned off.
 *
 * @returns The client.
 */
function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

/**
 * Wrap a hook in the query provider it needs.
 *
 * @param client - The client to provide.
 * @returns The wrapper.
 */
function withClient(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  getChatHistoryMock.mockResolvedValue([]);
  postChatQuestionMock.mockResolvedValue(makeResponse());
  deleteChatMessageMock.mockResolvedValue(undefined);
  clearChatHistoryMock.mockResolvedValue(undefined);
});

describe("useChat", () => {
  it("loads the history of the repository", async () => {
    getChatHistoryMock.mockResolvedValue([makeHistoryRow()]);

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
    });

    expect(result.current.messages[0].question).toBe(
      "What does the pipeline do?",
    );
    expect(result.current.messages[0].answer).toEqual({
      answer: "It clones, parses and scores.",
      sources: [],
    });
    expect(getChatHistoryMock).toHaveBeenCalledWith(REPO_ID);
  });

  it("shows a turn before its answer arrives", async () => {
    let resolvePost: ((value: ChatResponse) => void) | undefined;
    postChatQuestionMock.mockImplementation(
      () =>
        new Promise<ChatResponse>((resolve) => {
          resolvePost = resolve;
        }),
    );

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await act(async () => {
      void result.current.sendMessage("Why is it a single task?");
    });

    // The turn is on the screen straight away, with no answer yet.
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].question).toBe(
      "Why is it a single task?",
    );
    expect(result.current.messages[0].answer).toBeNull();
    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      resolvePost?.(makeResponse({ id: "turn-9", answer: "For the memory." }));
    });

    expect(result.current.messages[0].answer).toEqual({
      answer: "For the memory.",
      sources: [],
    });
    expect(result.current.messages[0].id).toBe("turn-9");
    expect(result.current.isLoading).toBe(false);
  });

  it("keeps a failed turn on the screen with the generic message", async () => {
    postChatQuestionMock.mockRejectedValue(new Error("network down"));

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await act(async () => {
      await result.current.sendMessage("Why is it a single task?");
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].error).toBe(true);
    expect(result.current.messages[0].errorKind).toBe("generic");
    expect(result.current.messages[0].answer).toEqual({
      answer: "Failed to get response. Try again.",
      sources: [],
    });
  });

  it("gives the quota failure its own message", async () => {
    postChatQuestionMock.mockRejectedValue(
      new ApiError({
        kind: "quota",
        status: 402,
        message: "You've used all of your free chat questions.",
        body: { detail: "You've used all of your free chat questions." },
      }),
    );

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await act(async () => {
      await result.current.sendMessage("Why is it a single task?");
    });

    expect(result.current.messages[0].error).toBe(true);
    expect(result.current.messages[0].errorKind).toBe("quota");
    expect(result.current.messages[0].answer?.answer).toBe(
      "You've used all of your free chat questions.",
    );
  });

  it("sends the answered turns as the history of the next question", async () => {
    getChatHistoryMock.mockResolvedValue([makeHistoryRow()]);

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
    });

    await act(async () => {
      await result.current.sendMessage("And the glossary?");
    });

    expect(postChatQuestionMock).toHaveBeenCalledWith(REPO_ID, {
      question: "And the glossary?",
      history: [
        { role: "user", content: "What does the pipeline do?" },
        { role: "assistant", content: "It clones, parses and scores." },
      ],
    });
  });

  it("leaves a failed turn out of the history it sends", async () => {
    getChatHistoryMock.mockResolvedValue([makeHistoryRow()]);
    postChatQuestionMock.mockRejectedValueOnce(new Error("network down"));

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
    });

    await act(async () => {
      await result.current.sendMessage("And the glossary?");
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1].error).toBe(true);

    postChatQuestionMock.mockResolvedValueOnce(makeResponse());
    await act(async () => {
      await result.current.sendMessage("One more?");
    });

    const lastCall = postChatQuestionMock.mock.calls.at(-1);
    expect(lastCall?.[1].history).toEqual([
      { role: "user", content: "What does the pipeline do?" },
      { role: "assistant", content: "It clones, parses and scores." },
    ]);
  });

  it("removes a turn and deletes it on the server", async () => {
    getChatHistoryMock.mockResolvedValue([makeHistoryRow()]);

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
    });

    await act(async () => {
      await result.current.deleteMessage("turn-1");
    });

    expect(result.current.messages).toHaveLength(0);
    expect(deleteChatMessageMock).toHaveBeenCalledWith(REPO_ID, "turn-1");
  });

  it("does not put a turn back when the delete fails", async () => {
    getChatHistoryMock.mockResolvedValue([makeHistoryRow()]);
    deleteChatMessageMock.mockRejectedValue(new Error("network down"));

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
    });

    await act(async () => {
      await result.current.deleteMessage("turn-1");
    });

    expect(result.current.messages).toHaveLength(0);
  });

  it("clears the history on screen and on the server", async () => {
    getChatHistoryMock.mockResolvedValue([makeHistoryRow()]);

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
    });

    await act(async () => {
      await result.current.clearHistory();
    });

    expect(result.current.messages).toHaveLength(0);
    expect(clearChatHistoryMock).toHaveBeenCalledWith(REPO_ID);
  });

  it("does not put the turns back when the clear fails", async () => {
    getChatHistoryMock.mockResolvedValue([makeHistoryRow()]);
    clearChatHistoryMock.mockRejectedValue(new Error("network down"));

    const { result } = await renderHook(() => useChat({ repoId: REPO_ID }), {
      wrapper: withClient(makeClient()),
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
    });

    await act(async () => {
      await result.current.clearHistory();
    });

    expect(result.current.messages).toHaveLength(0);
  });

  it("does not fetch the history without a repository", async () => {
    const { result } = await renderHook(() => useChat({ repoId: "" }), {
      wrapper: withClient(makeClient()),
    });

    await waitFor(() => {
      expect(result.current.isLoadingHistory).toBe(false);
    });

    expect(getChatHistoryMock).not.toHaveBeenCalled();
    expect(result.current.messages).toHaveLength(0);
  });
});
