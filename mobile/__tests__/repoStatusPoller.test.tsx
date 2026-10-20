/**
 * Tests for the repository status poller.
 *
 * The poller is what keeps a repository page honest while something is
 * happening in the background: an ingest that has not settled, or a sync
 * that deliberately leaves ``status='ready'`` alone. On the web it calls
 * ``router.refresh()``; on mobile it invalidates the cached repository.
 */

import React from "react";
import { render, act } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { RepoStatusPoller } from "@/components/RepoStatusPoller";
import { queryKeys } from "@/api/queryKeys";

/**
 * Render the poller against a fresh query client and return the spy on
 * ``invalidateQueries``.
 *
 * @param props - The poller's props.
 * @returns The rendered screen and the invalidation spy.
 */
async function renderPoller(props: {
  status: string;
  syncStatus: string;
  pollIntervalMs?: number;
  maxPollMs?: number;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidate = jest.spyOn(queryClient, "invalidateQueries");

  const screen = await render(
    <QueryClientProvider client={queryClient}>
      <RepoStatusPoller
        repoNumber="42"
        status={props.status}
        syncStatus={props.syncStatus}
        pollIntervalMs={props.pollIntervalMs ?? 1000}
        maxPollMs={props.maxPollMs}
      />
    </QueryClientProvider>,
  );

  return { screen, invalidate };
}

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

describe("RepoStatusPoller", () => {
  it("refetches the repository while the ingest has not settled", async () => {
    const { invalidate } = await renderPoller({
      status: "parsing",
      syncStatus: "idle",
    });

    await act(async () => {
      jest.advanceTimersByTime(1000);
    });

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.repositories.detail("42"),
    });
  });

  it("does not poll once the repository is ready and no sync is running", async () => {
    const { invalidate } = await renderPoller({
      status: "ready",
      syncStatus: "idle",
    });

    await act(async () => {
      jest.advanceTimersByTime(10_000);
    });

    expect(invalidate).not.toHaveBeenCalled();
  });

  it("polls while a sync is running, even though the status stays ready", async () => {
    const { invalidate } = await renderPoller({
      status: "ready",
      syncStatus: "updating",
    });

    await act(async () => {
      jest.advanceTimersByTime(1000);
    });

    expect(invalidate).toHaveBeenCalled();
  });

  it("gives up on a status that never clears", async () => {
    const { invalidate } = await renderPoller({
      status: "parsing",
      syncStatus: "idle",
      pollIntervalMs: 1000,
      maxPollMs: 2500,
    });

    await act(async () => {
      jest.advanceTimersByTime(1000);
    });
    expect(invalidate).toHaveBeenCalledTimes(1);

    // The second tick is still inside the window.
    await act(async () => {
      jest.advanceTimersByTime(1000);
    });
    expect(invalidate).toHaveBeenCalledTimes(2);

    // The third is past it, and the poller stops for good.
    await act(async () => {
      jest.advanceTimersByTime(1000);
    });
    expect(invalidate).toHaveBeenCalledTimes(2);

    await act(async () => {
      jest.advanceTimersByTime(10_000);
    });
    expect(invalidate).toHaveBeenCalledTimes(2);
  });
});
