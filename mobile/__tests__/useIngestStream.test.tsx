/**
 * Tests for the live ingestion stream.
 *
 * The stream is transport only, so what matters here is what it does with
 * what arrives: a frame that is JSON becomes a uniform frame, a frame that
 * is not JSON still renders as itself, and the connection's own lifecycle
 * shows up in the frame list rather than only in a boolean.
 */

import { act, renderHook, waitFor } from "@testing-library/react-native";

import { ingestSocketUrl } from "@/api/ingest";
import { useIngestStream } from "@/hooks/useIngestStream";

/**
 * A stand-in for the platform's WebSocket.
 *
 * The real one is a native module; this records what was opened and lets a
 * test push frames through it.
 */
class FakeWebSocket {
  /** Every socket the hook has opened, oldest first. */
  static instances: FakeWebSocket[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  /** The URL the hook opened. */
  url: string;

  /** Whether the hook closed the socket. */
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  /** Report that the socket opened. */
  open() {
    this.onopen?.();
  }

  /** Deliver a raw payload. */
  emit(data: string) {
    this.onmessage?.({ data });
  }

  /** Report that the socket closed. */
  finish() {
    this.onclose?.();
  }
}

const originalWebSocket = global.WebSocket;

/**
 * Render the hook against the fake socket.
 *
 * @param overrides - Fields to change on the hook's arguments.
 * @returns The hook's result and the render handle.
 */
async function renderStream(overrides: Record<string, unknown> = {}) {
  return await renderHook(() =>
    useIngestStream({
      repoId: "repo-1",
      token: "secret",
      backendUrl: "http://host:8000",
      ...overrides,
    }),
  );
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  (global as unknown as { WebSocket: unknown }).WebSocket = FakeWebSocket;
});

afterEach(() => {
  (global as unknown as { WebSocket: unknown }).WebSocket = originalWebSocket;
});

describe("ingest socket url", () => {
  it("swaps the scheme for the WebSocket one", () => {
    expect(ingestSocketUrl("repo-1", "token", "http://host:8000")).toBe(
      "ws://host:8000/api/v1/ws/ingest/repo-1?token=token",
    );
    expect(ingestSocketUrl("repo-1", "token", "https://host")).toBe(
      "wss://host/api/v1/ws/ingest/repo-1?token=token",
    );
  });

  it("escapes the token", () => {
    expect(ingestSocketUrl("repo-1", "a b&c", "http://host")).toBe(
      "ws://host/api/v1/ws/ingest/repo-1?token=a%20b%26c",
    );
  });
});

describe("useIngestStream", () => {
  it("opens a socket carrying the token", async () => {
    await renderStream();

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toBe(
      "ws://host:8000/api/v1/ws/ingest/repo-1?token=secret",
    );
  });

  it("opens no socket when it is disabled", async () => {
    await renderStream({ enabled: false });

    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("records the connection opening as a frame", async () => {
    const { result } = await renderStream();

    await act(async () => {
      FakeWebSocket.instances[0].open();
    });

    await waitFor(() => expect(result.current.connected).toBe(true));
    expect(result.current.frames[0].event).toBe("system");
    expect(result.current.frames[0].message).toContain("Connected");
  });

  it("normalises a frame that arrives as JSON", async () => {
    const { result } = await renderStream();

    await act(async () => {
      FakeWebSocket.instances[0].emit(
        JSON.stringify({
          event: "stage",
          message: "Cloning repository",
          timestamp: "2026-01-15T12:00:00Z",
          stage: "clone",
          phase: "started",
          processed: 3,
          total: 10,
          count: 7,
          status: "cloning",
        }),
      );
    });

    await waitFor(() => expect(result.current.frames).toHaveLength(1));
    expect(result.current.frames[0]).toEqual({
      event: "stage",
      message: "Cloning repository",
      timestamp: "2026-01-15T12:00:00Z",
      stage: "clone",
      phase: "started",
      processed: 3,
      total: 10,
      count: 7,
      status: "cloning",
    });
  });

  it("keeps a frame that is not JSON as itself", async () => {
    const { result } = await renderStream();

    await act(async () => {
      FakeWebSocket.instances[0].emit("not json at all");
    });

    await waitFor(() => expect(result.current.frames).toHaveLength(1));
    expect(result.current.frames[0].message).toBe("not json at all");
    expect(result.current.frames[0].event).toBe("info");
  });

  it("falls back to the raw payload when the JSON has no message", async () => {
    const { result } = await renderStream();

    await act(async () => {
      FakeWebSocket.instances[0].emit(JSON.stringify({ event: "x" }));
    });

    await waitFor(() => expect(result.current.frames).toHaveLength(1));
    expect(result.current.frames[0].message).toBe('{"event":"x"}');
  });

  it("reports the socket closing", async () => {
    const { result } = await renderStream();

    await act(async () => {
      FakeWebSocket.instances[0].open();
    });
    await act(async () => {
      FakeWebSocket.instances[0].finish();
    });

    await waitFor(() => expect(result.current.closed).toBe(true));
    expect(result.current.connected).toBe(false);
    expect(
      result.current.frames[result.current.frames.length - 1].message,
    ).toBe("Connection closed.");
  });

  it("opens a fresh socket on a reconnect and keeps the frames", async () => {
    const { result } = await renderStream();

    await act(async () => {
      FakeWebSocket.instances[0].emit(JSON.stringify({ message: "one" }));
    });
    await waitFor(() => expect(result.current.frames).toHaveLength(1));

    await act(async () => {
      result.current.reconnect();
    });

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    expect(FakeWebSocket.instances[0].closed).toBe(true);
    expect(result.current.frames).toHaveLength(1);
  });

  it("closes the socket when it unmounts", async () => {
    const { unmount } = await renderStream();

    await act(async () => {
      unmount();
    });

    expect(FakeWebSocket.instances[0].closed).toBe(true);
  });
});
