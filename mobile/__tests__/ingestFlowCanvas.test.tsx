/**
 * Tests for the live ingest canvas.
 *
 * The canvas is mostly a picture, so what is worth pinning is what a reader
 * can actually take from it: the stage names are on screen, the stage that
 * is running is marked, a stage that failed says so, and the motion is
 * suppressed when the reader has asked for less of it.
 */

import { render } from "@testing-library/react-native";

import { IngestFlowCanvas } from "@/components/IngestFlowCanvas";
import { emptyStateMap, reduceFrame } from "@/lib/ingestFlow";
import type { IngestFrame, StageStateMap } from "@/types/ingest";

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

/**
 * Fold a sequence of frames into a board.
 *
 * @param frames - The frames, oldest first.
 * @returns The board.
 */
function board(frames: IngestFrame[]): StageStateMap {
  return frames.reduce(reduceFrame, emptyStateMap());
}

/**
 * Every piece of text the canvas drew.
 *
 * ``getByText`` only matches React Native's own text elements, and an SVG
 * label is not one of them: the string ends up on the SVG span's ``content``
 * prop instead. The rendered tree is walked directly.
 *
 * @param screen - The rendered screen.
 * @returns The strings the canvas put on screen.
 */
function drawnText(screen: { toJSON: () => unknown }): string[] {
  const found: string[] = [];

  const walk = (node: unknown): void => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    const element = node as {
      props?: { content?: unknown };
      children?: unknown[];
    };
    if (typeof element.props?.content === "string") {
      found.push(element.props.content);
    }
    element.children?.forEach(walk);
  };

  walk(screen.toJSON());
  return found;
}

describe("IngestFlowCanvas", () => {
  it("draws every stage of the pipeline", async () => {
    const screen = await render(<IngestFlowCanvas states={emptyStateMap()} />);

    expect(screen.getByTestId("ingest-flow-canvas")).toBeTruthy();

    const text = drawnText(screen);
    expect(text).toContain("Fetch Repo");
    expect(text).toContain("Parse files");
    expect(text).toContain("Create Reading Order");
    expect(text).toContain("Analyze Architecture");
    expect(text).toContain("Ready");
  });

  it("summarises the board for a screen reader", async () => {
    const states = board([
      makeFrame({ stage: "clone", phase: "done" }),
      makeFrame({ stage: "parse", phase: "started" }),
    ]);

    const screen = await render(<IngestFlowCanvas states={states} />);

    const label =
      screen.getByTestId("ingest-flow-svg").props.accessibilityLabel;
    expect(label).toContain("Fetch Repo: done");
    expect(label).toContain("Parse files: active");
    expect(label).toContain("Create Glossary: pending");
  });

  it("marks a stage that failed", async () => {
    const states = board([
      makeFrame({ stage: "parse", phase: "started" }),
      makeFrame({ event: "error", phase: "failed", message: "boom" }),
    ]);

    const screen = await render(<IngestFlowCanvas states={states} />);

    const label =
      screen.getByTestId("ingest-flow-svg").props.accessibilityLabel;
    expect(label).toContain("Parse files: failed");
  });

  it("draws an edge once its source has finished", async () => {
    const states = board([makeFrame({ stage: "clone", phase: "done" })]);

    const screen = await render(<IngestFlowCanvas states={states} />);

    expect(screen.getByTestId("ingest-lit-clone--parse")).toBeTruthy();
  });

  it("haloes the stage that is running", async () => {
    const states = board([makeFrame({ stage: "parse", phase: "started" })]);

    const screen = await render(<IngestFlowCanvas states={states} />);

    expect(screen.getByTestId("ingest-halo-parse")).toBeTruthy();
  });

  it("suppresses the motion when the reader has asked for less of it", async () => {
    const states = board([makeFrame({ stage: "parse", phase: "started" })]);

    const screen = await render(
      <IngestFlowCanvas states={states} reducedMotion />,
    );

    // The board is still drawn; nothing moves.
    expect(drawnText(screen)).toContain("Parse files");
    expect(screen.queryByTestId("ingest-halo-parse")).toBeNull();
    expect(screen.queryByTestId("ingest-stream-clone--parse")).toBeNull();
  });

  it("shows the counter of the stage that reports one", async () => {
    const states = board([
      makeFrame({
        stage: "parse",
        phase: "progress",
        processed: 120,
        total: 400,
      }),
    ]);

    const screen = await render(<IngestFlowCanvas states={states} />);

    expect(drawnText(screen)).toContain("120/400");
  });
});
