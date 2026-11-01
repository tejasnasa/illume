/**
 * Tests for the ingestion flow graph and its reducer.
 *
 * The reducer is the part with the real logic: it is the only thing that
 * decides what the board shows, and it decides that from the frames alone.
 * It is tested here as a pure function rather than through a rendered
 * canvas, because the rules it encodes -- monotonicity, pessimism about
 * what a status proves, the handling of a failure frame that names no
 * stage -- are worth pinning independently of how they are drawn.
 */

import {
  EDGES,
  NODES,
  NODES_BY_ID,
  STAGE_IDS,
  activeStage,
  emptyStateMap,
  hasFailed,
  isComplete,
  isFlowing,
  isLit,
  normaliseTimes,
  pathFromPoints,
  pathLengthOf,
  reduceFrame,
  reduceFrames,
  seedFromStatus,
} from "@/lib/ingestFlow";
import { PIPELINE_STAGES, stageStatesFromStatus } from "@/lib/repoStatus";
import type { IngestFrame } from "@/types/ingest";

/**
 * Build a frame with sensible defaults.
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

describe("ingest flow graph", () => {
  it("has one node per pipeline stage, with the same labels", () => {
    expect(NODES).toHaveLength(PIPELINE_STAGES.length);

    for (const stage of PIPELINE_STAGES) {
      const node = NODES_BY_ID[stage.id];
      expect(node).toBeDefined();
      expect(node?.label).toBe(stage.label);
    }
  });

  it("addresses every stage from an empty map", () => {
    const map = emptyStateMap();
    for (const id of STAGE_IDS) {
      expect(map[id]?.state).toBe("pending");
    }
  });

  it("keeps the fork and join junctions out of the stage list", () => {
    // A junction is not a stage: it never completes, so it has no state of
    // its own and no node to draw.
    expect(STAGE_IDS).not.toContain("fork_risk");
    expect(STAGE_IDS).not.toContain("join_llm");
    expect(STAGE_IDS).not.toContain("join_final");
  });

  it("turns waypoints into a path", () => {
    expect(pathFromPoints([])).toBe("");
    expect(pathFromPoints([[10, 20]])).toBe("M 10 20");
    expect(pathFromPoints([[10, 20], [30, 40]])).toBe("M 10 20 L 30 40");
  });

  it("measures a path from its waypoints", () => {
    expect(pathLengthOf([[0, 0], [3, 4]])).toBe(5);
    expect(pathLengthOf([[0, 0], [3, 4], [3, 14]])).toBe(15);
    expect(pathLengthOf([])).toBe(0);
  });

  it("weights the keyframes of a path by distance, not by vertex", () => {
    // The long leg comes first, so the middle waypoint is most of the way
    // along the path.
    const times = normaliseTimes([[0, 0], [90, 0], [100, 0]]);
    expect(times[0]).toBe(0);
    expect(times[2]).toBe(1);
    expect(times[1]).toBeCloseTo(0.9);
  });

  it("splits a degenerate path evenly rather than dividing by zero", () => {
    const times = normaliseTimes([[5, 5], [5, 5], [5, 5]]);
    expect(times).toEqual([0, 0.5, 1]);
  });
});

describe("seeding from the coarse status", () => {
  it("proves only the clone from a parsing status", () => {
    const seeded = seedFromStatus("parsing");
    expect(seeded.clone?.state).toBe("done");
    expect(seeded.parse?.state).toBe("active");
    expect(seeded.glossary?.state).toBe("pending");
  });

  it("proves the whole prefix from an embedding status", () => {
    const seeded = seedFromStatus("embedding");
    expect(seeded.glossary?.state).toBe("done");
    expect(seeded.reading_order?.state).toBe("done");
    expect(seeded.generate_embeddings?.state).toBe("active");
    expect(seeded.brief?.state).toBe("active");
  });

  it("completes everything from a ready status", () => {
    const seeded = seedFromStatus("ready");
    for (const id of STAGE_IDS) {
      expect(seeded[id]?.state).toBe("done");
    }
  });

  it("proves nothing from a failed or pending status", () => {
    for (const status of ["failed", "pending", "something-new"]) {
      const seeded = seedFromStatus(status);
      for (const id of STAGE_IDS) {
        expect(seeded[id]?.state).toBe("pending");
      }
    }
  });

  it("agrees with the status view the static screen draws", () => {
    // The static pipeline list and the live canvas show the same pipeline;
    // they must not disagree about what a status proves.
    for (const status of ["cloning", "parsing", "embedding", "ready"]) {
      const live = seedFromStatus(status);
      const static_ = stageStatesFromStatus(status);
      for (const stage of PIPELINE_STAGES) {
        expect(live[stage.id]?.state).toBe(static_[stage.id]);
      }
    }
  });
});

describe("reducing frames", () => {
  it("activates a stage on a started frame", () => {
    const next = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "clone", phase: "started" }),
    );
    expect(next.clone?.state).toBe("active");
  });

  it("completes a stage on a done frame", () => {
    const next = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "clone", phase: "done" }),
    );
    expect(next.clone?.state).toBe("done");
  });

  it("never moves a stage backwards", () => {
    const done = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "clone", phase: "done" }),
    );
    const after = reduceFrame(
      done,
      makeFrame({ stage: "clone", phase: "started" }),
    );
    expect(after.clone?.state).toBe("done");
  });

  it("returns the same map when a frame carries nothing new", () => {
    const first = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "clone", phase: "done", message: "done" }),
    );
    const second = reduceFrame(
      first,
      makeFrame({ stage: "clone", phase: "done", message: "done" }),
    );
    expect(second).toBe(first);
  });

  it("keeps the parse counter and rejects a zero total", () => {
    const withCounter = reduceFrame(
      emptyStateMap(),
      makeFrame({
        stage: "parse",
        phase: "progress",
        processed: 120,
        total: 400,
      }),
    );
    expect(withCounter.parse?.progress).toEqual({ processed: 120, total: 400 });

    const withZeroTotal = reduceFrame(
      withCounter,
      makeFrame({
        stage: "parse",
        phase: "progress",
        processed: 5,
        total: 0,
      }),
    );
    expect(withZeroTotal.parse?.progress).toEqual({ processed: 120, total: 400 });
  });

  it("keeps a count of zero, which is a real total", () => {
    const next = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "pr_fetch", phase: "done", count: 0 }),
    );
    expect(next.pr_fetch?.count).toBe(0);
  });

  it("ignores a stage the graph does not know", () => {
    const before = emptyStateMap();
    const after = reduceFrame(
      before,
      makeFrame({ stage: "a_stage_from_the_future", phase: "done" }),
    );
    expect(after).toBe(before);
  });

  it("fails whatever was running when a failure frame names no stage", () => {
    const running = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "parse", phase: "started" }),
    );
    const failed = reduceFrame(
      running,
      makeFrame({ event: "error", phase: "failed", message: "boom" }),
    );
    expect(failed.parse?.state).toBe("failed");
    expect(failed.clone?.state).toBe("pending");
  });

  it("fails on a failed status as well as a failed phase", () => {
    const running = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "parse", phase: "started" }),
    );
    const failed = reduceFrame(running, makeFrame({ status: "failed" }));
    expect(failed.parse?.state).toBe("failed");
  });

  it("changes nothing when a failure arrives with nothing running", () => {
    const before = emptyStateMap();
    const after = reduceFrame(before, makeFrame({ phase: "failed" }));
    expect(after).toBe(before);
  });

  it("completes the whole graph when the run reaches ready", () => {
    const next = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "ready", phase: "done" }),
    );
    for (const id of STAGE_IDS) {
      expect(next[id]?.state).toBe("done");
    }
  });

  it("folds a whole sequence of frames, oldest first", () => {
    const next = reduceFrames(emptyStateMap(), [
      makeFrame({ stage: "clone", phase: "started" }),
      makeFrame({ stage: "clone", phase: "done" }),
      makeFrame({ stage: "parse", phase: "started" }),
    ]);
    expect(next.clone?.state).toBe("done");
    expect(next.parse?.state).toBe("active");
  });
});

describe("reading the board", () => {
  it("lights an edge whose source has finished", () => {
    const states = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "clone", phase: "done" }),
    );
    const edge = EDGES.find(
      (candidate) => candidate.from === "clone" && candidate.to === "parse",
    );
    expect(edge).toBeDefined();
    expect(isLit(edge!, states)).toBe(true);
  });

  it("waits for every stage an edge names before lighting it", () => {
    const edge = EDGES.find(
      (candidate) =>
        candidate.to === "generate_embeddings" &&
        candidate.requires?.includes("glossary"),
    );
    expect(edge).toBeDefined();

    const glossaryOnly = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "glossary", phase: "done" }),
    );
    expect(isLit(edge!, glossaryOnly)).toBe(false);

    const both = reduceFrame(
      glossaryOnly,
      makeFrame({ stage: "reading_order", phase: "done" }),
    );
    expect(isLit(edge!, both)).toBe(true);
  });

  it("stops flowing once everything downstream has settled", () => {
    const states = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "clone", phase: "done" }),
    );
    const edge = EDGES.find(
      (candidate) => candidate.from === "clone" && candidate.to === "parse",
    );
    expect(isFlowing(edge!, states)).toBe(true);

    const parsed = reduceFrame(
      states,
      makeFrame({ stage: "parse", phase: "done" }),
    );
    expect(isFlowing(edge!, parsed)).toBe(false);
  });

  it("names the stage that is running", () => {
    const states = reduceFrame(
      emptyStateMap(),
      makeFrame({ stage: "parse", phase: "started" }),
    );
    expect(activeStage(states)).toBe("parse");
    expect(activeStage(emptyStateMap())).toBeNull();
  });

  it("knows when the run is complete and when it has failed", () => {
    expect(isComplete(emptyStateMap())).toBe(false);
    expect(hasFailed(emptyStateMap())).toBe(false);

    const complete = seedFromStatus("ready");
    expect(isComplete(complete)).toBe(true);

    const failed = reduceFrame(
      reduceFrame(
        emptyStateMap(),
        makeFrame({ stage: "parse", phase: "started" }),
      ),
      makeFrame({ phase: "failed" }),
    );
    expect(hasFailed(failed)).toBe(true);
    expect(isComplete(failed)).toBe(false);
  });
});
