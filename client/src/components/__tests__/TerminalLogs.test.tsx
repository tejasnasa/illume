import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TerminalLogs from "@/components/TerminalLogs";

const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh, back: vi.fn() }),
}));

/**
 * A stand-in for the browser's `WebSocket`.
 *
 * happy-dom does not implement one that a test can drive, and the component's behaviour is
 * entirely a function of the frames it receives -- so the fake records itself and lets the
 * test fire `onopen`/`onmessage`/`onclose` by hand.
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  url: string;
  readyState = 0;
  closed = false;

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  /** Fires a frame at the component. */
  emit(data: string) {
    this.onmessage?.({ data });
  }
}

/** The most recently constructed socket. */
function socket(): FakeWebSocket {
  return FakeWebSocket.instances.at(-1)!;
}

/** A frame in the shape the ingestion task actually publishes. */
function frame(message: string, event = "log") {
  return JSON.stringify({ event, message, timestamp: "2026-01-01T00:00:00+00:00" });
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("mounting", () => {
  it("renders the initial connecting line", () => {
    render(<TerminalLogs repoId="r1" token="t1" />);

    expect(screen.getByText("Connecting to ingestion pipeline...")).toBeInTheDocument();
  });

  it("opens a socket to the ingest channel", () => {
    render(<TerminalLogs repoId="repo-abc" token="tok" />);

    expect(socket().url).toContain("/api/v1/ws/ingest/repo-abc");
  });

  it("builds a ws:// URL from the http backend URL", () => {
    // The backend URL is http(s); a WebSocket needs ws(s). The replace is the only thing
    // doing that conversion, and getting it wrong yields a URL the browser refuses.
    render(<TerminalLogs repoId="r1" token="t1" />);

    expect(socket().url.startsWith("ws://") || socket().url.startsWith("wss://")).toBe(true);
    expect(socket().url).not.toContain("http://");
  });

  it("passes the token as a query parameter", () => {
    // The documented workaround for clients that cannot set a WebSocket header. It leaks
    // the token into access logs, which is why the token is no longer written into the
    // application's own log line -- but the transport itself is unchanged.
    render(<TerminalLogs repoId="r1" token="secret-token" />);

    expect(socket().url).toContain("token=secret-token");
  });

  it("adds a connected line when the socket opens", () => {
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().onopen?.();
    });

    expect(screen.getByText("Connected. Waiting for worker...")).toBeInTheDocument();
  });
});

describe("frames", () => {
  it("appends the message from a JSON frame", () => {
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit(frame("Parsing src/main.py", "file_processed"));
    });

    expect(screen.getByText("Parsing src/main.py")).toBeInTheDocument();
  });

  it("keeps every frame in order", () => {
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit(frame("first"));
      socket().emit(frame("second"));
      socket().emit(frame("third"));
    });

    const rendered = screen.getAllByText(/first|second|third/).map((el) => el.textContent);
    expect(rendered).toEqual(["first", "second", "third"]);
  });

  it("shows the raw payload when it is not JSON", () => {
    // `JSON.parse` is inside a try/catch that leaves `logMessage` as the raw string, so a
    // malformed frame is displayed rather than dropped.
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit("plain text frame");
    });

    expect(screen.getByText("plain text frame")).toBeInTheDocument();
  });

  it("refreshes the route on a status update", () => {
    // This is what makes the page reflect a repository that became ready, without the
    // user reloading.
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit(frame("Status changed to parsing", "status_update"));
    });

    expect(refresh).toHaveBeenCalled();
  });

  it("does not refresh for an ordinary log frame", () => {
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit(frame("Parsing src/main.py", "file_processed"));
    });

    expect(refresh).not.toHaveBeenCalled();
  });

  it("renders the message for a frame with no event field", () => {
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit(JSON.stringify({ message: "no event here" }));
    });

    expect(screen.getByText("no event here")).toBeInTheDocument();
  });
});

describe("terminal markers", () => {
  it("shows the success line for the frame the task actually sends", () => {
    // The task publishes `{"event":"done","message":"DONE"}` -- a JSON object, not a bare
    // string. Comparing the *raw frame* against "DONE" meant this branch was unreachable
    // and the completion path never ran, which went unnoticed because the log line still
    // rendered "DONE" from the frame's `message` field.
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit(frame("DONE", "done"));
    });

    expect(screen.getByText(/Ingestion finished successfully/)).toBeInTheDocument();
  });

  it("shows the success line for a bare DONE frame", () => {
    // Nothing publishes this shape, but the fallback still recognises it -- so a future
    // publisher that skips the JSON wrapper cannot silently reintroduce the mismatch.
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit("DONE");
    });

    expect(screen.getByText(/Ingestion finished successfully/)).toBeInTheDocument();
  });

  it("shows the failure line for a bare ERROR frame", () => {
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit("ERROR");
    });

    expect(screen.getByText("Ingestion failed!")).toBeInTheDocument();
  });

  it("shows the failure line for the JSON error frame", () => {
    // The same mismatch as the success marker, on the error path.
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().emit(frame("ERROR", "error"));
    });

    expect(screen.getByText("Ingestion failed!")).toBeInTheDocument();
  });

  it("refreshes a second time after the success marker", () => {
    vi.useFakeTimers();
    try {
      render(<TerminalLogs repoId="r1" token="t1" />);

      act(() => {
        socket().emit("DONE");
      });
      act(() => {
        vi.advanceTimersByTime(1000);
      });

      expect(refresh).toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("lifecycle", () => {
  it("reports a socket error", () => {
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().onerror?.();
    });

    expect(screen.getByText("WebSocket connection error.")).toBeInTheDocument();
  });

  it("reports a close", () => {
    render(<TerminalLogs repoId="r1" token="t1" />);

    act(() => {
      socket().onclose?.();
    });

    expect(screen.getByText("Connection closed.")).toBeInTheDocument();
  });

  it("closes the socket on unmount", () => {
    // Without this, navigating away from an in-progress ingestion leaks a connection --
    // and the server never closes it from its end either.
    const { unmount } = render(<TerminalLogs repoId="r1" token="t1" />);
    const ws = socket();

    unmount();

    expect(ws.closed).toBe(true);
  });

  it("opens a new socket when the repository changes", () => {
    const { rerender } = render(<TerminalLogs repoId="r1" token="t1" />);
    const first = socket();

    rerender(<TerminalLogs repoId="r2" token="t1" />);

    expect(socket()).not.toBe(first);
    expect(socket().url).toContain("/api/v1/ws/ingest/r2");
  });

  it("closes the previous socket when the repository changes", () => {
    const { rerender } = render(<TerminalLogs repoId="r1" token="t1" />);
    const first = socket();

    rerender(<TerminalLogs repoId="r2" token="t1" />);

    expect(first.closed).toBe(true);
  });
});
