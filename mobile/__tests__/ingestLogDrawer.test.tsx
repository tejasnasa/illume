/**
 * Tests for the raw ingest log drawer.
 *
 * The drawer is the reader's way of finding out *why* something broke, so
 * what matters is that every line that arrived is in there, in order, and
 * that the sheet opens and closes.
 */

import { fireEvent, render } from "@testing-library/react-native";

import {
  IngestLogDrawer,
  formatTime,
  getLogColor,
} from "@/components/IngestLogDrawer";
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

describe("log line colours", () => {
  it("colours an error line like an error", () => {
    expect(getLogColor("error")).toBe(getLogColor("stage_failed"));
  });

  it("colours a finished stage like a success", () => {
    expect(getLogColor("success")).toBe(getLogColor("done"));
    expect(getLogColor("stage_complete")).toBe(getLogColor("done"));
  });

  it("gives a running stage its own colour", () => {
    expect(getLogColor("clone_started")).not.toBe(getLogColor("done"));
    expect(getLogColor("status_update")).not.toBe(getLogColor("done"));
  });
});

describe("log timestamps", () => {
  it("renders a wall clock", () => {
    expect(formatTime("2026-01-15T12:34:56Z")).toMatch(/\d{2}:\d{2}:\d{2}/);
  });

  it("renders nothing for a timestamp it cannot read", () => {
    expect(formatTime("not a date")).toBe("");
  });
});

describe("IngestLogDrawer", () => {
  it("counts the lines it has", async () => {
    const screen = await render(
      <IngestLogDrawer
        frames={[makeFrame({ message: "one" }), makeFrame({ message: "two" })]}
        open={false}
        onToggle={() => {}}
      />,
    );

    expect(screen.getByTestId("ingest-log-drawer")).toBeTruthy();
    expect(screen.getByText("Ingest logs (2)")).toBeTruthy();
  });

  it("shows the newest line while it is collapsed", async () => {
    const screen = await render(
      <IngestLogDrawer
        frames={[
          makeFrame({ message: "one" }),
          makeFrame({ message: "newest" }),
        ]}
        open={false}
        onToggle={() => {}}
      />,
    );

    expect(screen.getByTestId("ingest-log-latest")).toHaveTextContent("newest");
  });

  it("scrolls through the whole history when it is open", async () => {
    const frames = Array.from({ length: 40 }, (_, index) =>
      makeFrame({ message: `line ${index}` }),
    );

    const screen = await render(
      <IngestLogDrawer frames={frames} open onToggle={() => {}} />,
    );

    // The list is virtualised, so only the visible window is on screen; the
    // whole history is what it was handed.
    const list = screen.getByTestId("ingest-log-list");
    expect(list.props.data).toHaveLength(40);
    expect(list.props.data[39].message).toBe("line 39");

    expect(screen.getByText("line 0")).toBeTruthy();
  });

  it("says so when there is no output yet", async () => {
    const screen = await render(
      <IngestLogDrawer frames={[]} open onToggle={() => {}} />,
    );

    expect(screen.getByText("No output yet.")).toBeTruthy();
  });

  it("opens and closes from its summary bar", async () => {
    let open = false;
    const onToggle = jest.fn(() => {
      open = !open;
    });

    const screen = await render(
      <IngestLogDrawer
        frames={[makeFrame()]}
        open={open}
        onToggle={onToggle}
      />,
    );

    expect(screen.queryByTestId("ingest-log-scrim")).toBeNull();

    fireEvent.press(screen.getByTestId("ingest-log-toggle"));

    expect(onToggle).toHaveBeenCalled();
  });

  it("closes from the scrim", async () => {
    const onToggle = jest.fn();

    const screen = await render(
      <IngestLogDrawer frames={[makeFrame()]} open onToggle={onToggle} />,
    );

    expect(screen.getByTestId("ingest-log-scrim")).toBeTruthy();

    fireEvent.press(screen.getByTestId("ingest-log-scrim"));

    expect(onToggle).toHaveBeenCalled();
  });
});
