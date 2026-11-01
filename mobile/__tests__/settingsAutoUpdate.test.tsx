/**
 * Tests for the auto-update and manual-sync controls.
 *
 * Two things matter on this screen and both are requests:
 *
 * 1. Choosing a cadence PATCHes the repository's auto-update settings.
 * 2. "Sync now" POSTs to the sync endpoint, and the panel then reports
 *    the status the server answered with.
 *
 * The panel is driven with an injected ``fetchImpl`` so the assertions are
 * about the requests that actually went out.
 */

import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";

import { AutoUpdateSection } from "@/components/AutoUpdateSection";
import type Repository from "@/types/repository";

const BACKEND = "http://backend.test";
const REPO_ID = "repo-uuid-1";
const REPO_PATH = `${BACKEND}/api/v1/repository/${REPO_ID}`;

/**
 * A fetch stub that records the requests it was given.
 */
type FetchMock = jest.Mock<Promise<Response>, [string, RequestInit]>;

/**
 * A repository that can sync: it has a baseline commit and its owner has
 * a key on file.
 */
function makeRepo(overrides: Partial<Repository> = {}): Repository {
  return {
    id: REPO_ID,
    github_url: "https://github.com/owner/illume",
    name: "illume",
    status: "ready",
    architecture_summary: "",
    repo_number: 1,
    primary_language: "TypeScript",
    detected_stack: {
      ci_cd: [],
      databases: [],
      languages: [],
      frameworks: [],
      infrastructure: [],
    },
    entry_points: null,
    ingested_branch: "main",
    ingested_commit_sha: "abc123",
    analysis_commit_sha: "abc123",
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: new Date("2026-01-02T00:00:00Z"),
    auto_update_enabled: true,
    auto_update_interval_hours: 6,
    next_sync_at: null,
    last_synced_at: null,
    sync_status: "idle",
    last_sync_error: null,
    consecutive_sync_failures: 0,
    last_sync_summary: null,
    sync_available: true,
    ...overrides,
  };
}

/**
 * Render the panel with an injected transport.
 *
 * @param repo - The repository to show.
 * @param fetchImpl - The fetch stub the requests go through.
 * @returns The rendered panel.
 */
async function renderSection(repo: Repository, fetchImpl: FetchMock) {
  return render(
    <AutoUpdateSection
      repo={repo}
      options={{
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
        getToken: async () => "test-token",
      }}
    />,
  );
}

describe("AutoUpdateSection", () => {
  it("shows the current interval", async () => {
    const fetchImpl = jest.fn();
    const screen = await renderSection(makeRepo(), fetchImpl);

    expect(screen.getByText("Every 6 hours")).toBeTruthy();
  });

  it("issues the right request when an interval is chosen", async () => {
    const fetchImpl = jest.fn<Promise<Response>, [string, RequestInit]>(
      async () =>
        new Response(
          JSON.stringify(makeRepo({ auto_update_interval_hours: 3 })),
          {
            status: 200,
            headers: { "content-type": "application/json" },
          },
        ),
    );
    const screen = await renderSection(makeRepo(), fetchImpl);

    // The picker is a list of radio rows in a modal; open it first.
    await act(async () => {
      fireEvent.press(screen.getByTestId("auto-update-interval"));
    });

    await act(async () => {
      fireEvent.press(screen.getByTestId("auto-update-interval-option-3"));
    });

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${REPO_PATH}/auto-update`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ interval_hours: 3 });

    // The panel repaints with the cadence the server accepted.
    await waitFor(() => {
      expect(screen.getByText("Every 3 hours")).toBeTruthy();
    });
  });

  it("triggers the sync endpoint from the sync button", async () => {
    const fetchImpl = jest.fn<Promise<Response>, [string, RequestInit]>(
      async () =>
        new Response(
          JSON.stringify({
            repo_id: REPO_ID,
            sync_status: "queued",
            next_sync_at: null,
          }),
          { status: 202, headers: { "content-type": "application/json" } },
        ),
    );
    const screen = await renderSection(makeRepo(), fetchImpl);

    await act(async () => {
      fireEvent.press(screen.getByTestId("auto-update-sync-now"));
    });

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${REPO_PATH}/sync`);
    expect(init.method).toBe("POST");

    // The status the server answered with is reflected on the panel.
    await waitFor(() => {
      expect(screen.getByTestId("auto-update-status").props.children).toBe(
        "Syncing…",
      );
    });
  });

  it("toggles auto-update with a patch", async () => {
    const fetchImpl = jest.fn<Promise<Response>, [string, RequestInit]>(
      async () =>
        new Response(JSON.stringify(makeRepo({ auto_update_enabled: false })), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const screen = await renderSection(makeRepo(), fetchImpl);

    await act(async () => {
      fireEvent(screen.getByTestId("auto-update-switch"), "valueChange", false);
    });

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${REPO_PATH}/auto-update`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ enabled: false });
  });

  it("locks the controls when the repository has no baseline commit", async () => {
    const fetchImpl = jest.fn();
    const screen = await renderSection(
      makeRepo({ ingested_commit_sha: null }),
      fetchImpl,
    );

    await act(async () => {
      fireEvent.press(screen.getByTestId("auto-update-sync-now"));
    });

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(screen.getByText(/no baseline commit to update from/)).toBeTruthy();
  });
});
