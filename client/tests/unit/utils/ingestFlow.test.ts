/**
 * The ingestion flow reducer.
 *
 * This is the highest-value test in the feature: every claim the progress
 * view makes about the backend is produced here, so the honesty rules --
 * monotonic, idempotent, and pessimistic when seeding -- are pinned at this
 * level rather than through the DOM.
 */

import type { IngestFrame, StageStateMap } from "@/types/ingest";
import {
  STAGE_IDS,
  emptyStateMap,
  hasFailed,
  isComplete,
  normaliseTimes,
  reduceFrame,
  reduceFrames,
  seedFromStatus,
} from "@/utils/ingestFlow";
import { describe, expect, it } from "vitest";

/** Build a frame in the shape the backend publishes. */
function frame(partial: Partial<IngestFrame> & { stage: string }): IngestFrame {
  return {
    event: "test",
    message: partial.message ?? "test frame",
    timestamp: "2026-01-01T00:00:00+00:00",
    ...partial,
  };
}

/** The state of one stage, defaulting to `pending` so reads never throw. */
function stateOf(map: StageStateMap, id: string) {
  return map[id]?.state ?? "pending";
}

describe("seedFromStatus", () => {
  it("marks nothing as done while the job is still pending", () => {
    const seeded = seedFromStatus("pending");

    expect(Object.values(seeded).every((entry) => entry.state === "pending")).toBe(true);
  });

  it("puts the clone in flight while cloning", () => {
    const seeded = seedFromStatus("cloning");

    expect(stateOf(seeded, "clone")).toBe("active");
    expect(stateOf(seeded, "parse")).toBe("pending");
  });

  it("proves only the clone once parsing has started", () => {
    const seeded = seedFromStatus("parsing");

    expect(stateOf(seeded, "clone")).toBe("done");
    expect(stateOf(seeded, "parse")).toBe("active");
    // Everything after parse is inside the same status window, so none of it
    // may be claimed -- the seed picks the earliest candidate and stops.
    expect(stateOf(seeded, "git_history")).toBe("pending");
    expect(stateOf(seeded, "reading_order")).toBe("pending");
  });

  it("proves the whole prefix once embedding has started", () => {
    const seeded = seedFromStatus("embedding");

    for (const id of [
      "clone",
      "parse",
      "resolve_dependencies",
      "compute_fan_metrics",
      "detect_stack",
      "git_history",
      "criticality",
      "glossary",
      "reading_order",
    ]) {
      expect(stateOf(seeded, id), `${id} should be provably done`).toBe("done");
    }
    expect(stateOf(seeded, "generate_embeddings")).toBe("active");
    expect(stateOf(seeded, "brief")).toBe("active");
  });

  it("never seeds the PR fetch as done, because no status proves it", () => {
    // Its future is only joined at the very end of the task, so it can still
    // be running even once everything else has finished. This is the
    // assertion a future refactor is most likely to break.
    for (const status of ["pending", "cloning", "parsing", "embedding"]) {
      expect(stateOf(seedFromStatus(status), "pr_fetch"), status).not.toBe("done");
    }
  });

  it("treats an unknown status as nothing having started", () => {
    const seeded = seedFromStatus("something-new");

    expect(Object.values(seeded).every((entry) => entry.state === "pending")).toBe(true);
  });
});

describe("reduceFrame", () => {
  it("activates a stage on a started frame", () => {
    const next = reduceFrame(emptyStateMap(), frame({ stage: "parse", phase: "started" }));

    expect(stateOf(next, "parse")).toBe("active");
  });

  it("completes a stage on a done frame", () => {
    const next = reduceFrame(emptyStateMap(), frame({ stage: "parse", phase: "done" }));

    expect(stateOf(next, "parse")).toBe("done");
  });

  it("never moves a stage backwards", () => {
    // The pipeline publishes embedding_started before an earlier stage's
    // status frame, so a late `started` after a `done` is a real ordering the
    // reducer has to absorb rather than a hypothetical.
    const done = reduceFrame(emptyStateMap(), frame({ stage: "parse", phase: "done" }));
    const replayed = reduceFrame(done, frame({ stage: "parse", phase: "started" }));

    expect(stateOf(replayed, "parse")).toBe("done");
  });

  it("is idempotent for the duplicated embedding_started frame", () => {
    const once = reduceFrame(
      emptyStateMap(),
      frame({ stage: "generate_embeddings", phase: "started", message: "Generating embeddings..." }),
    );
    const twice = reduceFrame(
      once,
      frame({
        stage: "generate_embeddings",
        phase: "started",
        message: "Starting embedding generation...",
      }),
    );

    expect(stateOf(twice, "generate_embeddings")).toBe("active");
    expect(stateOf(once, "generate_embeddings")).toBe("active");
  });

  it("keeps the real parse counters", () => {
    const next = reduceFrame(
      emptyStateMap(),
      frame({ stage: "parse", phase: "progress", processed: 512, total: 1024 }),
    );

    expect(next.parse.progress).toEqual({ processed: 512, total: 1024 });
  });

  it("ignores a zero total rather than storing a divisor of zero", () => {
    const next = reduceFrame(
      emptyStateMap(),
      frame({ stage: "parse", phase: "progress", processed: 0, total: 0 }),
    );

    expect(next.parse.progress).toBeUndefined();
  });

  it("returns the same object when a frame carries nothing new", () => {
    const first = reduceFrame(emptyStateMap(), frame({ stage: "parse", phase: "done" }));
    const second = reduceFrame(first, frame({ stage: "parse", phase: "done" }));

    // Identity stability is what stops a memoised canvas re-rendering on
    // every replayed frame.
    expect(second).toBe(first);
  });

  it("ignores a stage id the graph does not know", () => {
    const before = emptyStateMap();
    const after = reduceFrame(before, frame({ stage: "invented_stage", phase: "done" }));

    expect(after).toBe(before);
    expect(Object.keys(after)).toHaveLength(STAGE_IDS.length);
  });

  it("ignores a frame with no stage at all", () => {
    const before = emptyStateMap();
    const after = reduceFrame(before, {
      event: "info",
      message: "Connected.",
      timestamp: "2026-01-01T00:00:00+00:00",
    });

    expect(after).toBe(before);
  });
});

describe("failure", () => {
  it("marks only the stages that were actually running", () => {
    // The task's catch-all cannot name the stage that raised, so the honest
    // reading is "what was in flight". Reddening the whole board would throw
    // away the one fact the chart exists to convey: how far it got.
    const partial = reduceFrames(emptyStateMap(), [
      frame({ stage: "clone", phase: "started" }),
      frame({ stage: "clone", phase: "done" }),
      frame({ stage: "parse", phase: "started" }),
      frame({ stage: "parse", phase: "progress", processed: 10, total: 100 }),
    ]);

    const failed = reduceFrame(partial, {
      event: "status_update",
      message: "Error: boom",
      timestamp: "2026-01-01T00:00:00+00:00",
      status: "failed",
      phase: "failed",
    });

    expect(stateOf(failed, "clone")).toBe("done");
    expect(stateOf(failed, "parse")).toBe("failed");
    expect(stateOf(failed, "git_history")).toBe("pending");
    expect(hasFailed(failed)).toBe(true);
  });

  it("leaves completed stages alone", () => {
    const done = reduceFrames(emptyStateMap(), [
      frame({ stage: "clone", phase: "done" }),
      frame({ stage: "parse", phase: "done" }),
    ]);

    const failed = reduceFrame(done, {
      event: "error",
      message: "ERROR",
      timestamp: "2026-01-01T00:00:00+00:00",
      phase: "failed",
    });

    expect(stateOf(failed, "clone")).toBe("done");
    expect(hasFailed(failed)).toBe(false);
  });
});

describe("completion", () => {
  it("reports complete only when every stage is done", () => {
    const allDone = reduceFrames(
      emptyStateMap(),
      STAGE_IDS.map((id) => frame({ stage: id, phase: "done" })),
    );

    expect(isComplete(allDone)).toBe(true);
    expect(isComplete(seedFromStatus("embedding"))).toBe(false);
  });

  it("completes the whole graph from the terminal frame alone", () => {
    // Reaching `ready` proves the pipeline returned, so every stage ran. This
    // is what stops a frame missed across a reconnect from stranding the view
    // one node short of finished, and the refresh with it.
    const partial = reduceFrames(emptyStateMap(), [
      frame({ stage: "clone", phase: "done" }),
      frame({ stage: "parse", phase: "started" }),
    ]);
    expect(isComplete(partial)).toBe(false);

    const finished = reduceFrame(partial, frame({ stage: "ready", phase: "done" }));

    expect(isComplete(finished)).toBe(true);
  });
});

describe("normaliseTimes", () => {
  it("starts at zero and ends at one", () => {
    const times = normaliseTimes([
      [0, 0],
      [100, 0],
      [100, 50],
    ]);

    expect(times[0]).toBe(0);
    expect(times.at(-1)).toBe(1);
  });

  it("weights by arc length, not by waypoint index", () => {
    // A long first leg and a short second one must not be treated as equal,
    // or a four-point edge would move at a different speed from a two-point
    // one and every pulse would look like it stuttered.
    const times = normaliseTimes([
      [0, 0],
      [300, 0],
      [300, 100],
    ]);

    expect(times[1]).toBeCloseTo(0.75, 5);
  });

  it("stays finite on a degenerate zero-length edge", () => {
    const times = normaliseTimes([
      [10, 10],
      [10, 10],
      [10, 10],
    ]);

    expect(times.every((value) => Number.isFinite(value))).toBe(true);
  });

  it("handles a two-point edge", () => {
    expect(normaliseTimes([[0, 0], [10, 0]])).toEqual([0, 1]);
  });
});
