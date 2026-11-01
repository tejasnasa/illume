/**
 * Tests for the repository chat screen.
 *
 * The screen is the reader's end of the conversation: a turn on the screen
 * with its question and its answer, the citations under it, and a failed
 * request that reads as a failure rather than as a crash. The transport
 * and the repository record are mocked, so what is under test is the
 * screen's own drawing.
 */

import React from "react";
import { Linking } from "react-native";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import RepoChatScreen from "@/app/(app)/repo/[id]/chat";
import { getChatHistory, postChatQuestion } from "@/api/chat";
import type Repository from "@/types/repository";
import type { ChatSource } from "@/types/chat";

jest.mock("expo-router", () => ({
  useGlobalSearchParams: () => ({ id: "42" }),
  router: { push: jest.fn(), navigate: jest.fn(), replace: jest.fn() },
}));

jest.mock("@/hooks/useRepositories", () => ({
  useRepository: () => ({
    data: mockRepo,
    isLoading: false,
    isError: false,
  }),
}));

jest.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    loading: false,
    token: "valid-jwt",
    user: mockUser,
    signIn: jest.fn(),
    signOut: jest.fn(),
    refreshUser: jest.fn(),
  }),
}));

jest.mock("@/api/chat", () => ({
  getChatHistory: jest.fn(),
  postChatQuestion: jest.fn(),
  deleteChatMessage: jest.fn(),
  clearChatHistory: jest.fn(),
}));

/**
 * The repository the screen is opened on.
 *
 * Declared with the ``mock`` prefix so the hoisted ``jest.mock`` factories
 * are allowed to close over it.
 */
const mockRepo = {
  id: "repo-uuid-1",
  github_url: "https://github.com/example/foo",
  name: "foo",
  status: "ready",
  architecture_summary: "A summary.",
  repo_number: 42,
  primary_language: "Python",
  detected_stack: {
    ci_cd: [],
    databases: [],
    languages: ["Python"],
    frameworks: [],
    infrastructure: [],
  },
  entry_points: null,
  ingested_branch: "main",
  ingested_commit_sha: "abcdef1234567890",
  analysis_commit_sha: null,
  created_at: new Date("2026-01-15T12:00:00Z"),
  updated_at: new Date("2026-01-15T12:00:00Z"),
  auto_update_enabled: true,
  auto_update_interval_hours: 6,
  next_sync_at: null,
  last_synced_at: null,
  sync_status: "idle",
  last_sync_error: null,
  consecutive_sync_failures: 0,
  last_sync_summary: null,
  sync_available: false,
} as unknown as Repository;

/**
 * The reader: one with their own key, so the quota never gets in the way.
 */
const mockUser = {
  id: "user-1",
  name: "Ada",
  email: "ada@example.com",
  avatar_url: null,
  github_id: null,
  ai_provider: null,
  ai_model: null,
  has_ai_key: true,
  free_ingestions_used: 0,
  free_chat_messages_used: 0,
  free_ingestions_limit: 3,
  free_chat_messages_limit: 10,
};

const getChatHistoryMock = getChatHistory as jest.MockedFunction<
  typeof getChatHistory
>;
const postChatQuestionMock = postChatQuestion as jest.MockedFunction<
  typeof postChatQuestion
>;

/**
 * The citation the stored turn carries.
 */
const source: ChatSource = {
  source_type: "symbol",
  chunk_text: "def ingest_repository(repo_id): ...",
  file_path: "app/tasks/ingest.py",
  symbol_name: "ingest_repository",
  start_line: 10,
  end_line: 20,
  commit_hash: null,
  author_name: null,
  pr_number: null,
  pr_title: null,
};

/**
 * Build a stored history row.
 *
 * @param overrides - The fields the test cares about.
 * @returns The row.
 */
function makeHistoryRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "turn-1",
    repository_id: "repo-uuid-1",
    user_id: "user-1",
    question: "What does the pipeline do?",
    answer: "It clones the repo, then parses it.",
    sources: [source],
    created_at: "2026-01-15T12:00:00Z",
    ...overrides,
  } as Awaited<ReturnType<typeof getChatHistory>>[number];
}

/**
 * Render the chat screen.
 *
 * @returns The rendered screen.
 */
async function renderScreen() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const screen = await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 47, left: 0, right: 0, bottom: 34 },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <RepoChatScreen />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );

  // The list schedules a cell-measurement timer of its own. Letting it
  // fire inside ``act`` keeps the update from being reported as one that
  // escaped the test.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 60));
  });

  return screen;
}

beforeEach(() => {
  jest.clearAllMocks();
  getChatHistoryMock.mockResolvedValue([makeHistoryRow()]);
  postChatQuestionMock.mockResolvedValue({
    id: "turn-2",
    answer: "It clones the repo, then parses it.",
    sources: [],
  });
});

describe("RepoChatScreen", () => {
  it("shows the question and the answer of a turn", async () => {
    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("chat-bubble")).toBeTruthy();
    });

    expect(screen.getByText("What does the pipeline do?")).toBeTruthy();
    expect(
      screen.getByText("It clones the repo, then parses it."),
    ).toBeTruthy();
  });

  it("cites the sources of the answer", async () => {
    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("citation-card-0")).toBeTruthy();
    });

    expect(screen.getByText("Sources Cited (1)")).toBeTruthy();
    expect(screen.getByTestId("citation-card-0-title")).toHaveTextContent(
      "ingest_repository",
    );
  });

  it("reveals the chunk text when a citation is expanded", async () => {
    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("citation-card-0")).toBeTruthy();
    });

    expect(screen.queryByTestId("citation-card-0-chunk")).toBeNull();

    await fireEvent.press(screen.getByTestId("citation-card-0-toggle"));

    await waitFor(() => {
      expect(screen.getByTestId("citation-card-0-chunk")).toBeTruthy();
    });
    expect(screen.getByTestId("citation-card-0-chunk")).toHaveTextContent(
      "def ingest_repository(repo_id): ...",
    );
  });

  it("links a citation to the commit the repository was ingested at", async () => {
    const openUrl = jest
      .spyOn(Linking, "openURL")
      .mockImplementation(async () => true);

    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("citation-card-0-github")).toBeTruthy();
    });

    await fireEvent.press(screen.getByTestId("citation-card-0-github"));

    expect(openUrl).toHaveBeenCalledWith(
      "https://github.com/example/foo/blob/abcdef1234567890/app/tasks/ingest.py#L10-L20",
    );

    openUrl.mockRestore();
  });

  it("shows a failed request as a failed turn", async () => {
    postChatQuestionMock.mockRejectedValue(new Error("network down"));

    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("chat-bubble")).toBeTruthy();
    });

    await fireEvent.changeText(
      screen.getByTestId("chat-input"),
      "And the glossary?",
    );
    await fireEvent.press(screen.getByTestId("chat-send"));

    await waitFor(() => {
      expect(screen.getByTestId("chat-bubble-error")).toBeTruthy();
    });

    expect(screen.getByText("Failed to get response. Try again.")).toBeTruthy();
  });

  it("shows the empty state until something is asked", async () => {
    getChatHistoryMock.mockResolvedValue([]);

    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("chat-empty")).toBeTruthy();
    });

    expect(
      screen.getByText(
        "Ask questions about the architecture, logic, or ownership.",
      ),
    ).toBeTruthy();
  });
});
