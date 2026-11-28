/**
 * Tests for the streaming chat screen.
 *
 * The transport is replaced by a scripted stream of events, so what is under
 * test is the screen: the preset picker and its free-tier gating, the deep
 * agent planner and worker lanes, the streamed answer with its citations,
 * and conversations.
 */

import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import RepoChatScreen from "@/app/(app)/repo/[id]/chat";
import { streamAgentRun } from "@/api/agentStream";
import type { StreamEvent } from "@/lib/agent/types";

jest.mock("expo-router", () => ({
  useGlobalSearchParams: () => ({ id: "42" }),
  router: { push: jest.fn(), navigate: jest.fn(), replace: jest.fn() },
}));

jest.mock("@react-native-async-storage/async-storage", () => ({
  __esModule: true,
  default: {
    getItem: jest.fn(async () => null),
    setItem: jest.fn(async () => {}),
  },
}));

const mockRepo = {
  id: "repo-uuid-1",
  name: "foo",
  github_url: "https://github.com/example/foo",
  status: "ready",
  entry_points: null,
  ingested_branch: "main",
  ingested_commit_sha: "abcdef1234567890",
};

let mockUser: Record<string, unknown> = {};

jest.mock("@/hooks/useRepositories", () => ({
  useRepository: () => ({ data: mockRepo, isLoading: false, isError: false }),
}));

jest.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    loading: false,
    token: "jwt",
    user: mockUser,
    signIn: jest.fn(),
    signOut: jest.fn(),
    refreshUser: jest.fn(async () => {}),
  }),
}));

jest.mock("@/api/graph", () => ({
  getGraph: jest.fn(async () => ({
    nodes: [],
    links: [],
    metadata: { total_nodes: 0, total_edges: 0, clusters: 0 },
  })),
}));

jest.mock("@/api/agentStream", () => ({
  streamAgentRun: jest.fn(),
}));

const mockList = jest.fn(async (): Promise<unknown[]> => []);
jest.mock("@/api/conversations", () => ({
  listConversations: () => mockList(),
  renameConversation: jest.fn(async () => ({})),
  deleteConversation: jest.fn(async () => ({})),
  getConversationMessages: jest.fn(async () => []),
  listAgentRuns: jest.fn(async () => []),
  deleteChatTurn: jest.fn(async () => ({})),
  getAnswerChanges: jest.fn(async () => ({
    stale_paths: [],
    commits: [],
    compare_url: null,
  })),
}));

const stream = streamAgentRun as jest.Mock;

function ev(
  seq: number,
  type: string,
  data: Record<string, unknown> = {},
  worker: string | null = null,
): StreamEvent {
  return {
    seq,
    ts: "2026-01-01T00:00:00Z",
    run_id: "run-1",
    worker_id: worker,
    type,
    data,
  };
}

const FREE_USER = {
  id: "u",
  has_ai_key: false,
  free_chat_messages_used: 1,
  free_chat_messages_limit: 10,
};
const OWN_KEY_USER = { ...FREE_USER, has_ai_key: true, ai_supports_tools: true };

async function renderScreen() {
  await act(async () => {
    await render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 360, height: 800 },
          insets: { top: 0, left: 0, right: 0, bottom: 0 },
        }}
      >
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <RepoChatScreen />
        </QueryClientProvider>
      </SafeAreaProvider>,
    );
  });
}

async function ask(text: string) {
  await fireEvent.changeText(screen.getByTestId("chat-input"), text);
  await act(async () => {
    await fireEvent.press(screen.getByTestId("chat-send"));
  });
}

beforeEach(() => {
  stream.mockReset();
  mockList.mockClear();
  mockUser = OWN_KEY_USER;
});

describe("preset picker", () => {
  it("offers both deep agent presets and Auto with an own key", async () => {
    await renderScreen();
    await fireEvent.press(screen.getByTestId("preset-picker"));
    for (const id of ["auto", "classic", "hybrid", "deep_agent", "deep_agent_workers"]) {
      expect(screen.getByTestId(`preset-${id}`).props.accessibilityState.disabled).toBe(false);
    }
  });

  it("disables Auto and the deep agent presets on the free tier, with a reason", async () => {
    mockUser = FREE_USER;
    await renderScreen();
    await fireEvent.press(screen.getByTestId("preset-picker"));
    for (const id of ["auto", "deep_agent", "deep_agent_workers"]) {
      expect(screen.getByTestId(`preset-${id}`).props.accessibilityState.disabled).toBe(true);
      expect(screen.getByTestId(`preset-reason-${id}`)).toBeTruthy();
    }
    expect(screen.getByTestId("preset-classic").props.accessibilityState.disabled).toBe(false);
  });

  it("starts on the strongest preset the account can run", async () => {
    await renderScreen();
    expect(screen.getByText("Deep agent")).toBeTruthy();
  });
});

describe("a deep agent run with workers", () => {
  it("sends the chosen preset and renders the planner and numbered workers", async () => {
    stream.mockImplementation(async (_repo, request, onEvent) => {
      expect(request.preset).toBe("deep_agent");
      onEvent(
        ev(1, "run_started", {
          preset: "deep_agent_workers",
          model: "m",
          config_hash: "h",
          execution: "x",
        }),
      );
      onEvent(
        ev(2, "plan", {
          subquestions: [
            { id: "w1", question: "How is login handled?" },
            { id: "w2", question: "Where are tokens stored?" },
          ],
        }),
      );
      onEvent(ev(3, "worker_started", { worker_id: "w1", question: "How is login handled?" }, "w1"));
      onEvent(ev(4, "worker_started", { worker_id: "w2", question: "Where are tokens stored?" }, "w2"));
      onEvent(
        ev(5, "tool_call", { call_id: "c1", tool: "grep_code", arguments: '{"pattern":"login"}' }, "w1"),
      );
      onEvent(ev(6, "worker_done", { worker_id: "w1", status: "completed" }, "w1"));
      onEvent(ev(7, "worker_done", { worker_id: "w2", status: "completed" }, "w2"));
      onEvent(ev(8, "answer_delta", { text: "Login is in auth.py [F:app/auth.py:1-9]." }));
      onEvent(
        ev(9, "done", {
          run_id: "run-1",
          status: "completed",
          answer: "Login is in auth.py [F:app/auth.py:1-9].",
          citations: [
            {
              key: "F:app/auth.py:1-9",
              source_type: "symbol",
              chunk_text: "def login(): ...",
              file_path: "app/auth.py",
              symbol_name: "login",
              start_line: 1,
              end_line: 9,
            },
          ],
          conversation_id: "conv-1",
          chat_message_id: "msg-1",
          usage: { input_tokens: 1200, output_tokens: 300, tool_calls: 1, elapsed_seconds: 12 },
        }),
      );
      return null;
    });

    await renderScreen();
    await ask("How does auth work?");

    await waitFor(() => expect(screen.getByTestId("answer")).toBeTruthy());
    expect(screen.getByTestId("row-plan")).toBeTruthy();
    expect(screen.getByText("Split into 2 parts, worked on in parallel")).toBeTruthy();
    expect(screen.getByText("#1")).toBeTruthy();
    expect(screen.getByText("#2")).toBeTruthy();
    expect(screen.getByText("How is login handled?")).toBeTruthy();
    expect(screen.getByText("Where are tokens stored?")).toBeTruthy();
    expect(screen.getByText(/1.2k in/)).toBeTruthy();
    // The finished turn refreshes the conversation list.
    await waitFor(() => expect(mockList.mock.calls.length).toBeGreaterThan(1));
  });

  it("opens a cited source when its key is tapped", async () => {
    stream.mockImplementation(async (_r, _q, onEvent) => {
      onEvent(ev(1, "run_started", { preset: "deep_agent" }));
      onEvent(
        ev(2, "done", {
          run_id: "run-1",
          answer: "See [F:app/auth.py:1-9].",
          citations: [
            {
              key: "F:app/auth.py:1-9",
              source_type: "symbol",
              chunk_text: "def login(): ...",
              file_path: "app/auth.py",
              symbol_name: "login",
              start_line: 1,
              end_line: 9,
            },
          ],
        }),
      );
      return null;
    });
    await renderScreen();
    await ask("q");
    await waitFor(() => expect(screen.getByTestId("cite-F:app/auth.py:1-9")).toBeTruthy());
    await fireEvent.press(screen.getByTestId("cite-F:app/auth.py:1-9"));
    expect(screen.getByTestId("opened-citation")).toBeTruthy();
  });
});

describe("failures", () => {
  it("shows a refusal message and a link to add a key on a 402", async () => {
    mockUser = FREE_USER;
    stream.mockResolvedValue({ status: 402, message: "Free chat used up" });
    await renderScreen();
    await fireEvent.press(screen.getByTestId("preset-picker"));
    await fireEvent.press(screen.getByTestId("preset-classic"));
    await ask("q");
    await waitFor(() => expect(screen.getByText("Free chat used up")).toBeTruthy());
    expect(screen.getByText("Add your own API key")).toBeTruthy();
  });

  it("marks a stream that ends with no terminal event as connection lost", async () => {
    stream.mockImplementation(async (_r, _q, onEvent) => {
      onEvent(ev(1, "run_started", { preset: "deep_agent" }));
      return null;
    });
    await renderScreen();
    await ask("q");
    await waitFor(() => expect(screen.getByText(/Connection lost/)).toBeTruthy());
  });

  it("marks a dropped connection as connection lost", async () => {
    stream.mockRejectedValue(new Error("socket closed"));
    await renderScreen();
    await ask("q");
    await waitFor(() => expect(screen.getByText(/Connection lost/)).toBeTruthy());
  });
});

describe("composer", () => {
  it("shows suggestions on an empty chat and asks one when tapped", async () => {
    stream.mockResolvedValue(null);
    await renderScreen();
    const suggestions = screen.getAllByTestId("chat-suggestion");
    expect(suggestions).toHaveLength(3);
    await act(async () => {
      await fireEvent.press(suggestions[0]);
    });
    expect(stream).toHaveBeenCalledTimes(1);
  });

  it("blocks sending when the free allowance is spent", async () => {
    mockUser = { ...FREE_USER, free_chat_messages_used: 10 };
    await renderScreen();
    expect(screen.getByTestId("chat-send").props.accessibilityState.disabled).toBe(true);
  });
});
