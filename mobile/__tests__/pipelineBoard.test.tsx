import { render, screen } from "@testing-library/react-native";

import { IngestLog } from "@/components/ingest/IngestLog";
import { PipelineBoard } from "@/components/ingest/PipelineBoard";
import { STAGE_IDS, emptyStateMap, reduceFrame, seedFromStatus } from "@/lib/ingestFlow";
import {
  PIPELINE_COLUMNS,
  countLabel,
  doneCount,
  fillOf,
  formatClock,
  logLabel,
  logTone,
  metaLine,
} from "@/lib/pipelineBoard";
import type { IngestFrame } from "@/types/ingest";

function frame(over: Partial<IngestFrame> = {}): IngestFrame {
  return {
    event: "progress",
    message: "working",
    timestamp: "2026-01-01T10:20:30",
    ...over,
  };
}

describe("pipeline columns", () => {
  it("place every stage exactly once", () => {
    const placed = PIPELINE_COLUMNS.flatMap((c) => [...c.stages]);
    expect([...placed].sort()).toEqual([...STAGE_IDS].sort());
    expect(new Set(placed).size).toBe(placed.length);
  });
});

describe("board wording", () => {
  it("words a total with its noun and singular form", () => {
    expect(countLabel({ id: "x", label: "x", cx: 0, cy: 0, unit: ["PR", "PRs"] }, 1)).toBe("1 PR");
    expect(countLabel({ id: "x", label: "x", cx: 0, cy: 0, unit: ["PR", "PRs"] }, 2871)).toBe("2,871 PRs");
    expect(countLabel({ id: "x", label: "x", cx: 0, cy: 0 }, 4)).toBeNull();
  });

  it("describes each state", () => {
    expect(metaLine("clone", { state: "pending" })).toBe("Waiting");
    expect(metaLine("clone", { state: "active" })).toBe("Running");
    expect(metaLine("parse", { state: "active", progress: { processed: 1200, total: 4000 } })).toBe(
      "1,200 / 4,000 files",
    );
    expect(metaLine("resolve_dependencies", { state: "done", count: 12 })).toBe("12 dependencies");
    expect(metaLine("resolve_dependencies", { state: "done", count: 0 })).toBe("0 dependencies");
    expect(metaLine("clone", { state: "done" })).toBe("Done");
    expect(metaLine("clone", { state: "failed" })).toBe("Failed");
  });

  it("fills bars by state and counter", () => {
    expect(fillOf({ state: "pending" })).toBe(0);
    expect(fillOf({ state: "done" })).toBe(1);
    expect(fillOf({ state: "failed" })).toBe(1);
    expect(fillOf({ state: "active" })).toBeNull();
    expect(fillOf({ state: "active", progress: { processed: 1, total: 4 } })).toBe(0.25);
    expect(fillOf({ state: "active", progress: { processed: 9, total: 4 } })).toBe(1);
    expect(fillOf({ state: "active", progress: { processed: 1, total: 0 } })).toBeNull();
  });

  it("counts finished stages from the frame reducer", () => {
    let states = seedFromStatus("embedding");
    expect(doneCount(states)).toBe(9);
    states = reduceFrame(states, frame({ stage: "ready", phase: "done" }));
    expect(doneCount(states)).toBe(STAGE_IDS.length);
    expect(doneCount(emptyStateMap())).toBe(0);
  });
});

describe("log formatting", () => {
  it("tones, labels and clocks", () => {
    expect(logTone(frame({ phase: "failed" }))).toBe("#f87171");
    expect(logTone(frame({ event: "error" }))).toBe("#f87171");
    expect(logTone(frame({ phase: "done" }))).not.toBe(logTone(frame({ phase: "started" })));
    expect(logLabel(frame({ stage: "parse" }))).toBe("stage=parse");
    expect(logLabel(frame())).toBe("progress");
    expect(formatClock("2026-01-01T10:20:30")).toBe("10:20:30");
    expect(formatClock("nonsense")).toBe("");
  });
});

describe("PipelineBoard", () => {
  it("draws every stage as a card with its state", async () => {
    let states = seedFromStatus("parsing");
    states = reduceFrame(
      states,
      frame({ stage: "parse", phase: "progress", processed: 50, total: 200 }),
    );
    await render(<PipelineBoard states={states} />);
    for (const id of STAGE_IDS) {
      expect(screen.getByTestId(`stage-${id}`, { includeHiddenElements: true })).toBeTruthy();
    }
    expect(screen.getByTestId("stage-mark-clone", { includeHiddenElements: true })).toHaveTextContent("✓");
    expect(screen.getByTestId("stage-mark-parse", { includeHiddenElements: true })).toHaveTextContent("●");
    expect(screen.getByTestId("stage-meta-parse", { includeHiddenElements: true })).toHaveTextContent(
      "50 / 200 files",
    );
    expect(screen.getByTestId("stage-mark-glossary", { includeHiddenElements: true })).toHaveTextContent("·");
  });

  it("marks failed stages", async () => {
    let states = seedFromStatus("parsing");
    states = reduceFrame(states, frame({ phase: "failed" }));
    await render(<PipelineBoard states={states} />);
    expect(screen.getByTestId("stage-mark-parse", { includeHiddenElements: true })).toHaveTextContent("✕");
  });

  it("gives a screen reader one line per stage", async () => {
    await render(<PipelineBoard states={emptyStateMap()} />);
    expect(screen.getByText("Fetch Repo: pending", { includeHiddenElements: true })).toBeTruthy();
  });
});

describe("IngestLog", () => {
  it("shows a waiting line, then one entry per frame with a count", async () => {
    const { rerender } = await render(<IngestLog frames={[]} repoId="abcdef" />);
    expect(screen.getByText("Waiting for the first line…")).toBeTruthy();
    await rerender(
      <IngestLog
        repoId="abcdef"
        frames={[frame({ message: "one", stage: "clone" }), frame({ message: "two" })]}
      />,
    );
    expect(screen.getAllByTestId("ingest-log-line")).toHaveLength(2);
    expect(screen.getByText("one")).toBeTruthy();
    expect(screen.getByText(/task:abcd…:logs · 2 lines/)).toBeTruthy();
  });
});
