/**
 * Tests for the React Query hooks around the repository endpoints.
 *
 * The hooks are the contract screens depend on: ``data``, ``isLoading``,
 * ``isError``, ``refetch``. We exercise the cache layer (TanStack Query)
 * rather than the transport -- mocking :func:`apiGet` keeps the test
 * pointed at the hook's behaviour, not the fetch wrapper's -- and
 * reset a fresh :class:`QueryClient` per test so the cache never
 * leaks between cases.
 */

import React from "react";
import { renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import Repository from "@/types/repository";
import { useRepositories, useRepository } from "@/hooks/useRepositories";
import { queryKeys } from "@/api/queryKeys";

jest.mock("@/api/repository", () => {
  const fixture: Repository = {
    id: "fixture-1",
    github_url: "https://github.com/example/fixture",
    name: "fixture",
    status: "ready",
    architecture_summary: "fixture summary",
    repo_number: 7,
    primary_language: "TypeScript",
    detected_stack: {
      ci_cd: [],
      databases: [],
      languages: ["TypeScript"],
      frameworks: [],
      infrastructure: [],
    },
    entry_points: null,
    ingested_branch: "main",
    ingested_commit_sha: "fixture0",
    analysis_commit_sha: null,
    created_at: new Date(),
    updated_at: new Date(),
    auto_update_enabled: true,
    auto_update_interval_hours: 6,
    next_sync_at: null,
    last_synced_at: null,
    sync_status: "idle",
    last_sync_error: null,
    consecutive_sync_failures: 0,
    last_sync_summary: null,
    sync_available: false,
  };
  return {
    getRepositories: jest.fn(async () => [fixture]),
    getRepository: jest.fn(async (id: number | string) => ({
      ...fixture,
      id: `fixture-${id}`,
      repo_number: typeof id === "string" ? Number(id) || 0 : id,
    })),
  };
});

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function withClient(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("useRepositories", () => {
  it("starts loading and resolves to the repository list", async () => {
    const client = makeClient();
    const { result } = await renderHook(() => useRepositories(), {
      wrapper: withClient(client),
    });

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.data).toHaveLength(1);
    expect(result.current.data![0].name).toBe("fixture");
  });

  it("uses the stable repositories.list key", () => {
    // The factory must match the keys other modules read -- a rename
    // here would invalidate every cache entry without a chance to log
    // it. Pin the shape so a typo is caught at unit-test time.
    expect(queryKeys.repositories.list()).toEqual(["repositories", "list"]);
  });

  it("exposes refetch for pull-to-refresh", async () => {
    const client = makeClient();
    const { result } = await renderHook(() => useRepositories(), {
      wrapper: withClient(client),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await result.current.refetch();
    expect(result.current.isError).toBe(false);
  });
});

describe("useRepository", () => {
  it("does not fetch when the id is missing", async () => {
    const client = makeClient();
    const { result } = await renderHook(() => useRepository(undefined), {
      wrapper: withClient(client),
    });
    // No fetch means the hook stays in the disabled state.
    await waitFor(() => {
      expect(result.current.fetchStatus).toBe("idle");
    });
    expect(result.current.data).toBeUndefined();
  });

  it("fetches and resolves when given a repo_number", async () => {
    const client = makeClient();
    const { result } = await renderHook(() => useRepository(7), {
      wrapper: withClient(client),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.data?.repo_number).toBe(7);
  });
});
