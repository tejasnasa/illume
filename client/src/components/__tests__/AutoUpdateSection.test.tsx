import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AutoUpdateSection from "@/components/AutoUpdateSection";
import Repository from "@/types/repository";

const REPO_ID = "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30";

const refresh = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh, back: vi.fn() }),
}));

// Server actions call `cookies()` which is only valid inside a Next.js request
// scope. The actions themselves are tested at the route level; here we stub
// them so the component runs end-to-end.
vi.mock("@/actions/updateAutoUpdate", () => ({
  default: vi.fn(),
}));
vi.mock("@/actions/triggerSync", () => ({
  default: vi.fn(),
}));

import updateAutoUpdateAction from "@/actions/updateAutoUpdate";
import triggerSyncAction from "@/actions/triggerSync";

const updateAutoUpdateMock = vi.mocked(updateAutoUpdateAction);
const triggerSyncMock = vi.mocked(triggerSyncAction);

/**
 * Builds a Repository with sensible defaults for the auto-update fields; tests
 * override the bits they care about.
 */
function makeRepo(overrides: Partial<Repository> = {}): Repository {
  return {
    id: REPO_ID,
    github_url: "https://github.com/example/cool-project",
    name: "cool-project",
    status: "ready",
    architecture_summary: "",
    repo_number: 7,
    primary_language: "Python",
    detected_stack: {
      ci_cd: [],
      databases: [],
      languages: [],
      frameworks: [],
      infrastructure: [],
    },
    entry_points: null,
    ingested_branch: "main",
    ingested_commit_sha: "a".repeat(40),
    analysis_commit_sha: "a".repeat(40),
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: new Date("2026-01-01T00:00:00Z"),
    auto_update_enabled: false,
    auto_update_interval_hours: 6,
    next_sync_at: null,
    last_synced_at: null,
    sync_status: "idle",
    last_sync_error: null,
    consecutive_sync_failures: 0,
    last_sync_summary: null,
    ...overrides,
  };
}

beforeEach(() => {
  refresh.mockReset();
  push.mockReset();
  updateAutoUpdateMock.mockReset();
  triggerSyncMock.mockReset();
  updateAutoUpdateMock.mockResolvedValue(undefined as never);
  triggerSyncMock.mockResolvedValue({
    repo_id: REPO_ID,
    sync_status: "queued",
    next_sync_at: "2026-01-01T00:00:00Z",
  } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the switch", () => {
  it("renders off when auto_update_enabled is false", () => {
    render(
      <AutoUpdateSection repo={makeRepo({ auto_update_enabled: false })} />,
    );

    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  it("renders on when auto_update_enabled is true", () => {
    render(
      <AutoUpdateSection repo={makeRepo({ auto_update_enabled: true })} />,
    );

    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("calls the action with enabled=true on toggle-on", async () => {
    const user = userEvent.setup();
    render(
      <AutoUpdateSection repo={makeRepo({ auto_update_enabled: false })} />,
    );

    await user.click(screen.getByRole("switch"));

    await waitFor(() => expect(updateAutoUpdateMock).toHaveBeenCalledTimes(1));
    expect(updateAutoUpdateMock).toHaveBeenCalledWith({
      repoId: REPO_ID,
      enabled: true,
    });
  });

  it("calls the action with enabled=false on toggle-off", async () => {
    const user = userEvent.setup();
    render(
      <AutoUpdateSection repo={makeRepo({ auto_update_enabled: true })} />,
    );

    await user.click(screen.getByRole("switch"));

    await waitFor(() => expect(updateAutoUpdateMock).toHaveBeenCalledTimes(1));
    expect(updateAutoUpdateMock).toHaveBeenCalledWith({
      repoId: REPO_ID,
      enabled: false,
    });
  });

  it("refreshes the page on a successful toggle", async () => {
    const user = userEvent.setup();
    render(<AutoUpdateSection repo={makeRepo()} />);

    await user.click(screen.getByRole("switch"));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("is disabled while sync_status is updating", () => {
    render(
      <AutoUpdateSection
        repo={makeRepo({
          auto_update_enabled: true,
          sync_status: "updating",
        })}
      />,
    );

    expect(screen.getByRole("switch")).toBeDisabled();
  });

  it("is disabled while sync_status is queued", () => {
    render(
      <AutoUpdateSection
        repo={makeRepo({
          auto_update_enabled: true,
          sync_status: "queued",
        })}
      />,
    );

    expect(screen.getByRole("switch")).toBeDisabled();
  });

  it("surfaces the action's error message on a failure", async () => {
    updateAutoUpdateMock.mockRejectedValueOnce(
      new Error("interval_hours must be one of [1, 3, 6, 12, 24]; got 42"),
    );
    const user = userEvent.setup();
    render(<AutoUpdateSection repo={makeRepo()} />);

    await user.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(
        screen.getByText(/interval_hours must be one of/),
      ).toBeInTheDocument(),
    );
  });
});

describe("the interval selector", () => {
  it("is hidden when auto_update_enabled is false", () => {
    render(
      <AutoUpdateSection repo={makeRepo({ auto_update_enabled: false })} />,
    );

    expect(
      screen.queryByRole("button", { name: /Every 6 hours/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the current interval when enabled", () => {
    render(
      <AutoUpdateSection
        repo={makeRepo({
          auto_update_enabled: true,
          auto_update_interval_hours: 3,
        })}
      />,
    );

    expect(
      screen.getByRole("button", { name: /Every 3 hours/i }),
    ).toBeInTheDocument();
  });

  it("calls the action with the chosen interval_hours", async () => {
    const user = userEvent.setup();
    render(
      <AutoUpdateSection
        repo={makeRepo({
          auto_update_enabled: true,
          auto_update_interval_hours: 6,
        })}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Every 6 hours/i }));
    await user.click(screen.getByRole("button", { name: /Every hour/i }));

    await waitFor(() => expect(updateAutoUpdateMock).toHaveBeenCalledTimes(1));
    expect(updateAutoUpdateMock).toHaveBeenCalledWith({
      repoId: REPO_ID,
      intervalHours: 1,
    });
  });

  it("does not call the action when the same interval is reselected", async () => {
    const user = userEvent.setup();
    render(
      <AutoUpdateSection
        repo={makeRepo({
          auto_update_enabled: true,
          auto_update_interval_hours: 6,
        })}
      />,
    );

    // The trigger opens the menu; the menu re-renders an item with the
    // same label. Click the trigger to open, then the menu item to "select".
    await user.click(screen.getByRole("button", { name: /Every 6 hours/i }));
    const matches = screen.getAllByRole("button", {
      name: /Every 6 hours/i,
    });
    // The first match is the now-hidden trigger (the menu is open and
    // overlays the page); the second is the menu item.
    await user.click(matches[matches.length - 1]);

    expect(updateAutoUpdateMock).not.toHaveBeenCalled();
  });
});

describe("sync now", () => {
  it("calls the sync action with the repo id", async () => {
    const user = userEvent.setup();
    render(<AutoUpdateSection repo={makeRepo()} />);

    await user.click(screen.getByRole("button", { name: /Sync now/i }));

    await waitFor(() => expect(triggerSyncMock).toHaveBeenCalledTimes(1));
    expect(triggerSyncMock).toHaveBeenCalledWith(REPO_ID);
  });

  it("refreshes after a successful sync-now", async () => {
    const user = userEvent.setup();
    render(<AutoUpdateSection repo={makeRepo()} />);

    await user.click(screen.getByRole("button", { name: /Sync now/i }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("is disabled while sync_status is active", () => {
    render(<AutoUpdateSection repo={makeRepo({ sync_status: "updating" })} />);

    expect(screen.getByRole("button", { name: /Sync now/i })).toBeDisabled();
  });

  it("surfaces the action's error message on a failure", async () => {
    triggerSyncMock.mockRejectedValueOnce(
      new Error("A sync is already in flight (lease expires at ...)."),
    );
    const user = userEvent.setup();
    render(<AutoUpdateSection repo={makeRepo()} />);

    await user.click(screen.getByRole("button", { name: /Sync now/i }));

    await waitFor(() =>
      expect(screen.getByText(/already in flight/)).toBeInTheDocument(),
    );
  });
});

describe("the status line", () => {
  it("renders 'Never synced' when last_synced_at is null", () => {
    render(<AutoUpdateSection repo={makeRepo({ last_synced_at: null })} />);

    expect(screen.getByText(/Never synced/i)).toBeInTheDocument();
  });

  it("renders the error message when last_sync_error is set", () => {
    render(
      <AutoUpdateSection
        repo={makeRepo({
          last_synced_at: new Date("2026-01-01T00:00:00Z"),
          last_sync_error: "git fetch failed: 401 Unauthorized",
        })}
      />,
    );

    expect(
      screen.getByText(/git fetch failed: 401 Unauthorized/i),
    ).toBeInTheDocument();
  });

  it("renders 'Syncing…' while sync_status is active", () => {
    render(
      <AutoUpdateSection
        repo={makeRepo({
          sync_status: "updating",
          last_synced_at: new Date("2026-01-01T00:00:00Z"),
        })}
      />,
    );

    expect(screen.getByText(/Syncing/)).toBeInTheDocument();
  });

  it("renders 'Paused after N failures' once auto-paused", () => {
    render(
      <AutoUpdateSection
        repo={makeRepo({
          auto_update_enabled: false,
          consecutive_sync_failures: 3,
          last_synced_at: new Date("2026-01-01T00:00:00Z"),
        })}
      />,
    );

    expect(
      screen.getByText(/Paused after 3 consecutive failures/i),
    ).toBeInTheDocument();
  });

  it("renders the relative time plus the changed-file count on success", () => {
    render(
      <AutoUpdateSection
        repo={makeRepo({
          last_synced_at: new Date(Date.now() - 60 * 60 * 1000),
          last_sync_summary: {
            files_upserted: 3,
            files_deleted: 1,
            files_changed: 4,
            new_commit_sha: "b".repeat(40),
            glossary_added: 0,
            embeddings_added: 0,
            status: "ok",
          },
        })}
      />,
    );

    expect(screen.getByText(/Updated .* ago/i)).toBeInTheDocument();
    expect(screen.getByText(/4 files changed/i)).toBeInTheDocument();
  });

  it("does not show the changed-file suffix when files_changed is zero", () => {
    render(
      <AutoUpdateSection
        repo={makeRepo({
          last_synced_at: new Date(Date.now() - 60 * 60 * 1000),
          last_sync_summary: {
            files_upserted: 0,
            files_deleted: 0,
            files_changed: 0,
            new_commit_sha: "b".repeat(40),
            glossary_added: 0,
            embeddings_added: 0,
            status: "ok",
          },
        })}
      />,
    );

    expect(screen.queryByText(/files changed/i)).not.toBeInTheDocument();
  });
});
