/**
 * Tests for the danger zone.
 *
 * Both actions here are total -- the re-ingest deletes the repository row
 * and recreates it with the same id, cascading every child row away with
 * it, and the delete removes it outright -- so neither may reach the API
 * without an explicit confirmation first.
 *
 * The assertions are therefore in pairs: the press opens the native
 * confirmation and sends nothing, and only the confirmation's own button
 * sends the request.
 */

import React from "react";
import { Alert, type AlertButton } from "react-native";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";

import { DangerZone } from "@/components/DangerZone";
import type Repository from "@/types/repository";

jest.mock("expo-router", () => {
  function noop() {
    /* router stub */
  }
  const routerObj = {
    push: noop,
    replace: noop,
    back: noop,
    navigate: noop,
    dismissTo: noop,
  };
  return {
    __esModule: true,
    default: routerObj,
    router: routerObj,
    useRouter: () => routerObj,
    useLocalSearchParams: () => ({}),
    usePathname: () => "/",
    Stack: ((p: { children?: unknown }) => p.children) as unknown as object,
    Redirect: (() => null) as unknown as object,
  };
});

const BACKEND = "http://backend.test";
const REPO_ID = "repo-uuid-1";
const REPO_PATH = `${BACKEND}/api/v1/repository/${REPO_ID}`;

/**
 * A fetch stub that records the requests it was given.
 */
type FetchMock = jest.Mock<Promise<Response>, [string, RequestInit]>;

/**
 * The repository the actions apply to.
 */
const REPO: Repository = {
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
  auto_update_enabled: false,
  auto_update_interval_hours: 6,
  next_sync_at: null,
  last_synced_at: null,
  sync_status: "idle",
  last_sync_error: null,
  consecutive_sync_failures: 0,
  last_sync_summary: null,
  sync_available: true,
};

/**
 * Render the danger zone with an injected transport.
 *
 * @param fetchImpl - The fetch stub the requests go through.
 * @returns The rendered zone.
 */
async function renderZone(fetchImpl: FetchMock) {
  return render(
    <DangerZone
      repo={REPO}
      options={{
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
        getToken: async () => "test-token",
      }}
    />,
  );
}

/**
 * The buttons of the last confirmation the app raised.
 *
 * @param alertSpy - The spy on ``Alert.alert``.
 * @returns The buttons the confirmation was given.
 */
function lastButtons(alertSpy: jest.SpyInstance): AlertButton[] {
  const call = alertSpy.mock.calls[alertSpy.mock.calls.length - 1];
  return (call[2] ?? []) as AlertButton[];
}

let alertSpy: jest.SpyInstance;

beforeEach(() => {
  alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => {});
});

afterEach(() => {
  alertSpy.mockRestore();
});

describe("DangerZone", () => {
  it("asks for confirmation before deleting, and sends nothing until it is given", async () => {
    const fetchImpl = jest.fn<Promise<Response>, [string, RequestInit]>(
      async () => new Response(null, { status: 204 }),
    );
    const screen = await renderZone(fetchImpl);

    await act(async () => {
      fireEvent.press(screen.getByTestId("danger-zone-delete"));
    });

    // The confirmation was raised...
    expect(alertSpy).toHaveBeenCalledTimes(1);
    expect(alertSpy.mock.calls[0][0]).toBe("Delete repository?");
    // ...and nothing was sent.
    expect(fetchImpl).not.toHaveBeenCalled();

    // Confirming is what sends the request.
    const buttons = lastButtons(alertSpy);
    const confirm = buttons.find((button) => button.style === "destructive");
    expect(confirm).toBeTruthy();

    await act(async () => {
      confirm?.onPress?.();
    });

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(REPO_PATH);
    expect(init.method).toBe("DELETE");
  });

  it("does not delete when the confirmation is cancelled", async () => {
    const fetchImpl = jest.fn();
    const screen = await renderZone(fetchImpl);

    await act(async () => {
      fireEvent.press(screen.getByTestId("danger-zone-delete"));
    });

    const buttons = lastButtons(alertSpy);
    const cancel = buttons.find((button) => button.style === "cancel");
    await act(async () => {
      cancel?.onPress?.();
    });

    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("asks for the repository name before the re-ingest can be armed", async () => {
    const fetchImpl = jest.fn();
    const screen = await renderZone(fetchImpl);

    // The button is inert until the name is typed.
    expect(
      screen.getByTestId("danger-zone-reingest").props.accessibilityState
        .disabled,
    ).toBe(true);

    await act(async () => {
      fireEvent.press(screen.getByTestId("danger-zone-reingest"));
    });

    expect(alertSpy).not.toHaveBeenCalled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("asks for confirmation before re-ingesting, and sends nothing until it is given", async () => {
    const fetchImpl = jest.fn<Promise<Response>, [string, RequestInit]>(
      async () =>
        new Response(JSON.stringify({ repo_id: REPO_ID, repo_num: 1 }), {
          status: 202,
          headers: { "content-type": "application/json" },
        }),
    );
    const screen = await renderZone(fetchImpl);

    await act(async () => {
      fireEvent.changeText(
        screen.getByTestId("danger-zone-confirmation"),
        "illume",
      );
    });

    expect(
      screen.getByTestId("danger-zone-reingest").props.accessibilityState
        .disabled,
    ).toBe(false);

    await act(async () => {
      fireEvent.press(screen.getByTestId("danger-zone-reingest"));
    });

    expect(alertSpy).toHaveBeenCalledTimes(1);
    expect(alertSpy.mock.calls[0][0]).toBe("Re-ingest repository?");
    // The confirmation says what the endpoint does -- the row is deleted
    // and recreated with the same id, so every child row goes with it.
    expect(String(alertSpy.mock.calls[0][1])).toContain("same id");
    expect(fetchImpl).not.toHaveBeenCalled();

    const buttons = lastButtons(alertSpy);
    const confirm = buttons.find((button) => button.style === "destructive");
    expect(confirm).toBeTruthy();

    await act(async () => {
      confirm?.onPress?.();
    });

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${REPO_PATH}/reingest`);
    expect(init.method).toBe("PUT");
  });
});
