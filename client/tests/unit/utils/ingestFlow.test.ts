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
  EDGES,
  STAGE_IDS,
  emptyStateMap,
  hasFailed,
  isComplete,
  isFlowing,
  normaliseTimes,
  pathLengthOf,
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

    expect(
      Object.values(seeded).every((entry) => entry.state === "pending"),
    ).toBe(true);
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
      expect(stateOf(seedFromStatus(status), "pr_fetch"), status).not.toBe(
        "done",
      );
    }
  });

  it("treats an unknown status as nothing having started", () => {
    const seeded = seedFromStatus("something-new");

    expect(
      Object.values(seeded).every((entry) => entry.state === "pending"),
    ).toBe(true);
  });
});

describe("reduceFrame", () => {
  it("activates a stage on a started frame", () => {
    const next = reduceFrame(
      emptyStateMap(),
      frame({ stage: "parse", phase: "started" }),
    );

    expect(stateOf(next, "parse")).toBe("active");
  });

  it("completes a stage on a done frame", () => {
    const next = reduceFrame(
      emptyStateMap(),
      frame({ stage: "parse", phase: "done" }),
    );

    expect(stateOf(next, "parse")).toBe("done");
  });

  it("never moves a stage backwards", () => {
    // The pipeline publishes embedding_started before an earlier stage's
    // status frame, so a late `started` after a `done` is a real ordering the
    // reducer has to absorb rather than a hypothetical.
    const done = reduceFrame(
      emptyStateMap(),
      frame({ stage: "parse", phase: "done" }),
    );
    const replayed = reduceFrame(
      done,
      frame({ stage: "parse", phase: "started" }),
    );

    expect(stateOf(replayed, "parse")).toBe("done");
  });

  it("is idempotent for the duplicated embedding_started frame", () => {
    const once = reduceFrame(
      emptyStateMap(),
      frame({
        stage: "generate_embeddings",
        phase: "started",
        message: "Generating embeddings...",
      }),
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
    const first = reduceFrame(
      emptyStateMap(),
      frame({ stage: "parse", phase: "done" }),
    );
    const second = reduceFrame(first, frame({ stage: "parse", phase: "done" }));

    // Identity stability is what stops a memoised canvas re-rendering on
    // every replayed frame.
    expect(second).toBe(first);
  });

  it("ignores a stage id the graph does not know", () => {
    const before = emptyStateMap();
    const after = reduceFrame(
      before,
      frame({ stage: "invented_stage", phase: "done" }),
    );

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

    const finished = reduceFrame(
      partial,
      frame({ stage: "ready", phase: "done" }),
    );

    expect(isComplete(finished)).toBe(true);
  });
});

describe("counts", () => {
  it("keeps the total a completed stage publishes", () => {
    const next = reduceFrame(
      emptyStateMap(),
      frame({ stage: "resolve_dependencies", phase: "done", count: 2871 }),
    );

    expect(next.resolve_dependencies.count).toBe(2871);
  });

  it("keeps the latest when one stage publishes more than once", () => {
    // Mining git history reports commits and then files; the node ends up
    // showing the second, which is the record it actually wrote.
    const next = reduceFrames(emptyStateMap(), [
      frame({ stage: "git_history", phase: "progress", count: 500 }),
      frame({ stage: "git_history", phase: "progress", count: 1024 }),
    ]);

    expect(next.git_history.count).toBe(1024);
  });

  it("does not mistake a zero for a missing total", () => {
    // A repository with no merged pull requests reports count=0, and that is
    // an answer rather than the absence of one.
    const next = reduceFrame(
      emptyStateMap(),
      frame({ stage: "pr_fetch", phase: "done", count: 0 }),
    );

    expect(next.pr_fetch.count).toBe(0);
  });

  it("leaves the total unset for a stage that publishes none", () => {
    const next = reduceFrame(
      emptyStateMap(),
      frame({ stage: "detect_stack", phase: "done" }),
    );

    expect(next.detect_stack.count).toBeUndefined();
  });
});

describe("isFlowing", () => {
  /** Look an edge up by its endpoints, failing loudly if the graph moved. */
  function edgeBetween(from: string, to: string) {
    const edge = EDGES.find((e) => e.from === from && e.to === to);
    if (!edge) throw new Error(`no edge ${from} -> ${to} in the graph`);
    return edge;
  }

  /** A state map with every named stage done. */
  function statesWith(done: readonly string[]): StageStateMap {
    const map = emptyStateMap();
    for (const id of done) map[id] = { state: "done" };
    return map;
  }

  it("leaves nothing flowing once every stage is done", () => {
    // The regression. Edges into a barrier have no stage to look up, so the
    // original check compared `undefined` against "done", never matched, and
    // left finished runs with particles streaming forever.
    const finished = statesWith(STAGE_IDS);

    expect(EDGES.filter((edge) => isFlowing(edge, finished))).toEqual([]);
  });

  it("stops an edge into a barrier once everything it feeds is done", () => {
    const edge = edgeBetween("criticality", "fork_risk");

    expect(isFlowing(edge, statesWith(["criticality"]))).toBe(true);
    expect(
      isFlowing(edge, statesWith(["criticality", "glossary"])),
      "still waiting on reading_order",
    ).toBe(true);
    expect(
      isFlowing(edge, statesWith(["criticality", "glossary", "reading_order"])),
    ).toBe(false);
  });

  it("stops the feed into ready once ready is done", () => {
    const edge = edgeBetween("join_final", "ready");

    expect(isFlowing(edge, statesWith(["generate_embeddings", "brief"]))).toBe(
      true,
    );
    expect(
      isFlowing(edge, statesWith(["generate_embeddings", "brief", "ready"])),
    ).toBe(false);
  });

  it("stops a plain edge when its target settles", () => {
    const edge = edgeBetween("clone", "parse");

    expect(isFlowing(edge, statesWith(["clone"]))).toBe(true);
    expect(isFlowing(edge, statesWith(["clone", "parse"]))).toBe(false);
  });

  it("treats a failed target as settled rather than as still in flight", () => {
    const edge = edgeBetween("clone", "parse");
    const map = statesWith(["clone"]);
    map.parse = { state: "failed" };

    expect(isFlowing(edge, map)).toBe(false);
  });

  it("never flows before its source is done", () => {
    expect(isFlowing(edgeBetween("clone", "parse"), emptyStateMap())).toBe(
      false,
    );
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
    expect(
      normaliseTimes([
        [0, 0],
        [10, 0],
      ]),
    ).toEqual([0, 1]);
  });
});

describe("pathLengthOf", () => {
  it("sums the segments rather than measuring end to end", () => {
    // The comet is a dash on the path, so it needs the travelled length of an
    // elbow -- the straight-line distance would put it in the wrong place.
    expect(
      pathLengthOf([
        [0, 0],
        [300, 0],
        [300, 100],
      ]),
    ).toBe(400);
  });

  it("is zero for a degenerate edge", () => {
    expect(pathLengthOf([[5, 5]])).toBe(0);
  });

  it("agrees with the last entry of normaliseTimes", () => {
    const points = [
      [0, 0],
      [120, 40],
      [200, 40],
      [200, 300],
    ] as const;

    expect(pathLengthOf(points)).toBeGreaterThan(0);
    expect(normaliseTimes(points).at(-1)).toBe(1);
  });
});
