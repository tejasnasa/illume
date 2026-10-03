/**
 * The in-progress ingestion view.
 *
 * Assertions go through the accessible text rather than the SVG internals --
 * the same discipline the end-to-end suite uses -- so the tests describe what
 * a person is told, not how it is drawn.
 */

import IngestFlow from "@/components/IngestFlow";
import {
  installFakeWebSocket,
  lastSocket,
} from "../../../tests/mocks/fakeWebSocket";
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh,
    back: vi.fn(),
  }),
}));

// Mutable so a single test can turn reduced motion on without a second module
// graph; `vi.hoisted` keeps it reachable from the hoisted mock factory.
const motion = vi.hoisted(() => ({ reduced: false }));

vi.mock("motion/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("motion/react")>();
  return { ...actual, useReducedMotion: () => motion.reduced };
});

/** Read a stage's line back out of the screen-reader summary. */
function nodeDetail(label: string): string {
  const item = screen
    .getAllByRole("listitem")
    .find((element) => element.textContent?.startsWith(`${label}:`));
  return item?.textContent?.slice(label.length + 2) ?? "missing";
}

/** Read just the state, discarding any stats that follow it. */
function nodeState(label: string): string {
  return nodeDetail(label).split(" (")[0];
}

/** Send a frame from the fake server. */
function send(payload: Record<string, unknown>) {
  act(() => lastSocket().emitFrame(payload));
}

/** Mount the view and open its socket. */
function mount(props: Partial<React.ComponentProps<typeof IngestFlow>> = {}) {
  const view = render(
    <IngestFlow
      repoId="r1"
      token="t1"
      repoLabel="example/sample-project"
      branch="main"
      commitSha={"a".repeat(40)}
      status="cloning"
      {...props}
    />,
  );
  act(() => lastSocket().open());
  return view;
}

beforeEach(() => {
  refresh.mockClear();
  motion.reduced = false;
  vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "http://localhost:8000");
  installFakeWebSocket();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("the header", () => {
  it("names the active stage while running", () => {
    mount();

    // `repoLabel` is no longer rendered in the header; the headline reflects
    // the currently-running stage instead. Scoped to <header> so the SVG text
    // node with the same label (it's the canvas) doesn't satisfy the query.
    expect(
      within(screen.getByRole("banner")).getByText("Fetch Repo"),
    ).toBeInTheDocument();
  });

  it("says it is queued rather than pretending a stage is running", () => {
    mount({ status: "pending" });

    expect(
      screen.getByText(/Queued — waiting for a worker/),
    ).toBeInTheDocument();
  });
});

describe("node states", () => {
  it("starts everything pending and lights a stage as it reports", () => {
    mount();

    expect(nodeState("Parse files")).toBe("pending");

    send({
      event: "parsing_started",
      message: "Starting file analysis...",
      stage: "parse",
      phase: "started",
    });

    expect(nodeState("Parse files")).toBe("active");
  });

  it("advances the parse stage when the backend reports progress", () => {
    mount();

    send({
      event: "file_processed",
      message: "512/1024 files indexed",
      stage: "parse",
      phase: "progress",
      processed: 512,
      total: 1024,
    });

    expect(nodeState("Parse files")).toBe("active");
  });

  it("resumes from the repository status instead of replaying from the clone", () => {
    // Opening the page mid-ingest must not restart the animation: the status
    // proves everything before the embedding phase already finished.
    mount({ status: "embedding" });

    expect(nodeState("Fetch Repo")).toBe("done");
    expect(nodeState("Mine Git History")).toBe("done");
    expect(nodeState("Create Reading Order")).toBe("done");
    expect(nodeState("Generate Embeddings")).toBe("active");
  });

  it("keeps the information when reduced motion is requested", () => {
    motion.reduced = true;
    mount({ status: "embedding" });

    expect(nodeState("Fetch Repo")).toBe("done");
    expect(nodeState("Generate Embeddings")).toBe("active");
    expect(nodeState("Ready")).toBe("pending");
  });
});

describe("what a stage reports", () => {
  it("says what a finished stage produced", () => {
    mount();

    send({
      event: "deps_resolved",
      message: "Resolved 2871 dependencies.",
      stage: "resolve_dependencies",
      phase: "done",
      count: 2871,
    });

    expect(nodeDetail("Map Connections")).toBe("done (2,871 dependencies)");
    // And on the node itself, where the number is the point of it.
    expect(screen.getByText("2,871 dependencies")).toBeInTheDocument();
  });

  it("carries the total through to a stage that publishes twice", () => {
    mount();

    send({
      event: "commits_parsed",
      message: "Parsed 500 commits from git log",
      stage: "git_history",
      phase: "progress",
      count: 500,
    });
    send({
      event: "ownership_written",
      message: "Code ownership records written for 1024 files",
      stage: "git_history",
      phase: "done",
      count: 1024,
    });

    expect(nodeDetail("Mine Git History")).toBe("done (1,024 files)");
  });

  it("draws no number for a stage that publishes none", () => {
    mount();

    send({
      event: "stack_detected",
      message: "Stack detected: ['Python']",
      stage: "detect_stack",
      phase: "done",
    });

    expect(nodeDetail("Identify Stack")).toBe("done");
  });

  it("claims no total for a stage it only knows finished", () => {
    // Seeded from the repository status, so the board knows the stage ended
    // without ever having been told what it produced.
    mount({ status: "embedding" });

    expect(nodeDetail("Mine Git History")).toBe("done");
  });

  it("keeps the parse counter out of the summary it announces", () => {
    mount();

    send({
      event: "file_processed",
      message: "512/1024 files indexed",
      stage: "parse",
      phase: "progress",
      processed: 512,
      total: 1024,
    });

    // Deliberately absent: a progress tick would otherwise announce itself on
    // every batch of a ten-thousand-file repository.
    expect(nodeDetail("Parse files")).toBe("active");
  });
});

describe("the refresh policy", () => {
  it("refreshes exactly once when the run completes, after the settle", () => {
    mount();

    act(() => {
      lastSocket().emitFrame({
        event: "status_update",
        message: "Ingestion complete!",
        status: "ready",
        stage: "ready",
        phase: "done",
      });
      lastSocket().emitFrame({
        event: "done",
        message: "DONE",
        stage: "ready",
        phase: "done",
      });
    });

    // Both terminal frames arrive, and neither may fire before the settle.
    expect(refresh).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1000));

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("never refreshes on an intermediate status update", () => {
    // The old view refreshed on every status change, which could re-render
    // the route out from under a running animation.
    mount();

    act(() => {
      lastSocket().emitFrame({
        event: "status_update",
        message: "Status changed to parsing",
        status: "parsing",
      });
      lastSocket().emitFrame({
        event: "status_update",
        message: "Status changed to embedding",
        status: "embedding",
      });
    });

    act(() => vi.advanceTimersByTime(5000));

    expect(refresh).not.toHaveBeenCalled();
  });

  it("refreshes after a failure, later than it would for success", () => {
    mount();

    act(() =>
      lastSocket().emitFrame({
        event: "error",
        message: "ERROR",
        phase: "failed",
      }),
    );

    act(() => vi.advanceTimersByTime(1000));
    expect(refresh).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(2000));
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

describe("failure and retry", () => {
  it("fails only the stage that was running", () => {
    mount();

    send({
      event: "clone_complete",
      message: "Clone complete.",
      stage: "clone",
      phase: "done",
    });
    send({
      event: "parsing_started",
      message: "Starting file analysis...",
      stage: "parse",
      phase: "started",
    });
    send({ event: "error", message: "ERROR", phase: "failed" });

    expect(nodeState("Fetch Repo")).toBe("done");
    expect(nodeState("Parse files")).toBe("failed");
    expect(nodeState("Ready")).toBe("pending");
  });

  it("clears the failure when the task retries from the clone", () => {
    mount();

    send({
      event: "parsing_started",
      message: "Starting file analysis...",
      stage: "parse",
      phase: "started",
    });
    send({ event: "error", message: "ERROR", phase: "failed" });
    expect(nodeState("Parse files")).toBe("failed");

    send({
      event: "clone_started",
      message: "Cloning repository...",
      stage: "clone",
      phase: "started",
    });

    expect(nodeState("Parse files")).toBe("pending");
    expect(nodeState("Fetch Repo")).toBe("active");
  });
});

describe("the raw log drawer", () => {
  it("is collapsed by default and shows the newest line when opened", () => {
    mount();

    expect(screen.queryByLabelText("Raw ingestion output")).toBeNull();

    const toggle = screen.getByRole("button", { name: /Ingest logs/ });
    act(() => toggle.click());

    expect(screen.getByLabelText("Raw ingestion output")).toBeInTheDocument();
  });
});
