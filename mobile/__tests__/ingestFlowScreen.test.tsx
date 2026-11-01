/**
 * Tests for the live ingest screen.
 *
 * The screen owns the policy the stream itself should not know about: which
 * stage it names, when a failure is final, and when a repository that has
 * not been claimed yet is better served by the static list. Those decisions
 * are what is pinned here.
 */

import React from "react";
import { render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { IngestFlow } from "@/components/IngestFlow";
import { AuthProvider } from "@/hooks/useAuth";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import type { IngestFrame } from "@/types/ingest";

/**
 * A frame with sensible defaults.
 *
 * @param overrides - The fields the test cares about.
 * @returns The frame.
 */
function makeFrame(overrides: Partial<IngestFrame> = {}): IngestFrame {
  return {
    event: "info",
    message: "working",
    timestamp: "2026-01-15T12:00:00Z",
    ...overrides,
  };
}

/**
 * Build a stream the screen can be handed.
 *
 * @param frames - The frames the stream has received.
 * @returns The stream.
 */
function makeStream(frames: IngestFrame[]) {
  return {
    frames,
    connected: true,
    closed: false,
    reconnect: jest.fn(),
  };
}

/**
 * Render the screen against a stream.
 *
 * @param props - The screen's props.
 * @returns The rendered screen.
 */
async function renderFlow(
  props: Partial<React.ComponentProps<typeof IngestFlow>> = {},
) {
  const fetchImpl = jest.fn(
    async () =>
      new Response(JSON.stringify({ id: "u1", email: "a@b", name: "Ada" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return await render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider fetchImpl={fetchImpl as unknown as typeof fetch}>
        <IngestFlow
          repoId="repo-1"
          repoNumber="42"
          status="parsing"
          stream={makeStream([])}
          {...props}
        />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  __setTokenStoreImplementation({
    async getItemAsync() {
      return "valid-jwt";
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  });
});

describe("IngestFlow", () => {
  it("names the stage that is running", async () => {
    const screen = await renderFlow({
      stream: makeStream([
        makeFrame({ stage: "parse", phase: "started", message: "parsing" }),
      ]),
    });

    await waitFor(() => {
      expect(screen.getByTestId("ingest-flow-headline")).toBeTruthy();
    });
    expect(screen.getByTestId("ingest-flow-headline")).toHaveTextContent(
      "Parse files",
    );
  });

  it("shows the board and the log drawer", async () => {
    const screen = await renderFlow({
      stream: makeStream([
        makeFrame({ stage: "parse", phase: "started", message: "parsing" }),
      ]),
    });

    expect(screen.getByTestId("ingest-flow-canvas")).toBeTruthy();
    expect(screen.getByTestId("ingest-log-drawer")).toBeTruthy();
    expect(screen.getByText("Ingest logs (1)")).toBeTruthy();
  });

  it("shows a failure frame as a failure", async () => {
    const screen = await renderFlow({
      stream: makeStream([
        makeFrame({ stage: "parse", phase: "started", message: "parsing" }),
        makeFrame({
          event: "error",
          phase: "failed",
          message: "the parse blew up",
        }),
      ]),
    });

    await waitFor(() => {
      expect(screen.getByTestId("ingest-flow-headline")).toBeTruthy();
    });
    expect(screen.getByTestId("ingest-flow-headline")).toHaveTextContent(
      "Failed, retrying…",
    );
  });

  it("calls a failure final once it is older than the retry grace", async () => {
    const screen = await renderFlow({
      status: "failed",
      failureAgeMs: 60_000,
      stream: makeStream([]),
    });

    await waitFor(() => {
      expect(screen.getByTestId("ingest-flow-headline")).toBeTruthy();
    });
    expect(screen.getByTestId("ingest-flow-headline")).toHaveTextContent(
      "Ingestion failed",
    );
  });

  it("shows the static list for a repository no worker has claimed", async () => {
    const screen = await renderFlow({
      status: "pending",
      stream: makeStream([]),
    });

    expect(screen.getByTestId("repo-status-view")).toBeTruthy();
    expect(screen.getByTestId("repo-status-headline")).toHaveTextContent(
      "Queued — waiting for a worker",
    );
    expect(screen.queryByTestId("ingest-flow-canvas")).toBeNull();
  });

  it("says the run is ready when every stage finished", async () => {
    const done: IngestFrame[] = [
      makeFrame({ stage: "clone", phase: "done" }),
      makeFrame({ stage: "ready", phase: "done" }),
    ];

    const screen = await renderFlow({ stream: makeStream(done) });

    await waitFor(() => {
      expect(screen.getByTestId("ingest-flow-headline")).toBeTruthy();
    });
    expect(screen.getByTestId("ingest-flow-headline")).toHaveTextContent(
      "Ready",
    );
  });
});
