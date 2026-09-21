import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RepoStatusPoller from "@/components/RepoStatusPoller";

const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh,
    replace: vi.fn(),
    push: vi.fn(),
    back: vi.fn(),
  }),
}));

describe("the poller", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    refresh.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("does not refresh when sync_status is idle", () => {
    render(<RepoStatusPoller sync_status="idle" />);

    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    expect(refresh).not.toHaveBeenCalled();
  });

  it("does not refresh when sync_status is failed", () => {
    render(<RepoStatusPoller sync_status="failed" />);

    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    expect(refresh).not.toHaveBeenCalled();
  });

  it("refreshes while sync_status is updating", () => {
    render(<RepoStatusPoller sync_status="updating" />);

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(refresh).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("refreshes while sync_status is queued", () => {
    render(<RepoStatusPoller sync_status="queued" />);

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("refreshes while sync_status is checking", () => {
    render(<RepoStatusPoller sync_status="checking" />);

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("stops refreshing once sync_status clears", () => {
    const { rerender } = render(<RepoStatusPoller sync_status="updating" />);

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(refresh).toHaveBeenCalledTimes(1);

    rerender(<RepoStatusPoller sync_status="idle" />);

    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
