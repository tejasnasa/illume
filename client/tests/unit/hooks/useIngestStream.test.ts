/**
 * The ingest WebSocket transport.
 *
 * The hook is deliberately dumb -- it owns the socket and normalises frames,
 * and decides nothing -- so these assertions are about the connection and the
 * shape of what comes off it, not about meaning.
 */

import { useIngestStream } from "@/hooks/useIngestStream";
import { FakeWebSocket, installFakeWebSocket, lastSocket } from "../../mocks/fakeWebSocket";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "http://localhost:8000");
  installFakeWebSocket();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("connection", () => {
  it("upgrades the backend URL to a websocket and carries the token", () => {
    renderHook(() => useIngestStream({ repoId: "repo-abc", token: "tok-123" }));

    expect(lastSocket().url).toBe(
      "ws://localhost:8000/api/v1/ws/ingest/repo-abc?token=tok-123",
    );
  });

  it("upgrades https to wss", () => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "https://api.example.com");
    renderHook(() => useIngestStream({ repoId: "r1", token: "t1" }));

    expect(lastSocket().url.startsWith("wss://api.example.com/")).toBe(true);
  });

  it("closes the socket on unmount", () => {
    const { unmount } = renderHook(() => useIngestStream({ repoId: "r1", token: "t1" }));
    const socket = lastSocket();

    unmount();

    expect(socket.closed).toBe(true);
  });

  it("opens a new socket when the repository changes", () => {
    const { rerender } = renderHook(
      ({ repoId }: { repoId: string }) => useIngestStream({ repoId, token: "t1" }),
      { initialProps: { repoId: "r1" } },
    );
    expect(FakeWebSocket.instances).toHaveLength(1);

    rerender({ repoId: "r2" });

    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(lastSocket().url).toContain("/ingest/r2");
  });

  it("reports connection state across the socket's life", () => {
    const { result } = renderHook(() => useIngestStream({ repoId: "r1", token: "t1" }));
    expect(result.current.connected).toBe(false);

    act(() => lastSocket().open());
    expect(result.current.connected).toBe(true);
    expect(result.current.closed).toBe(false);

    act(() => lastSocket().serverClose());
    expect(result.current.connected).toBe(false);
    expect(result.current.closed).toBe(true);
  });
});

describe("frames", () => {
  it("appends parsed frames in arrival order", () => {
    const { result } = renderHook(() => useIngestStream({ repoId: "r1", token: "t1" }));

    act(() => {
      lastSocket().emitFrame({ event: "clone_started", message: "Cloning..." });
      lastSocket().emitFrame({ event: "clone_complete", message: "Clone complete." });
    });

    const messages = result.current.frames.map((f) => f.message);
    expect(messages).toEqual(["Cloning...", "Clone complete."]);
  });

  it("carries the structured fields through", () => {
    const { result } = renderHook(() => useIngestStream({ repoId: "r1", token: "t1" }));

    act(() =>
      lastSocket().emitFrame({
        event: "file_processed",
        message: "512/1024 files indexed",
        stage: "parse",
        phase: "progress",
        processed: 512,
        total: 1024,
      }),
    );

    const latest = result.current.frames.at(-1)!;
    expect(latest.stage).toBe("parse");
    expect(latest.phase).toBe("progress");
    expect(latest.processed).toBe(512);
    expect(latest.total).toBe(1024);
  });

  it("surfaces a frame that is not JSON instead of dropping it", () => {
    const { result } = renderHook(() => useIngestStream({ repoId: "r1", token: "t1" }));

    act(() => lastSocket().emit("DONE"));

    expect(result.current.frames.at(-1)?.message).toBe("DONE");
  });

  it("keeps frames received so far across a reconnect", () => {
    const { result } = renderHook(() => useIngestStream({ repoId: "r1", token: "t1" }));

    act(() => lastSocket().emitFrame({ event: "clone_started", message: "Cloning..." }));
    act(() => result.current.reconnect());

    expect(result.current.frames.some((f) => f.message === "Cloning...")).toBe(true);
  });

  it("ignores the close of a socket that has already been replaced", () => {
    // A superseded socket still fires its own close. Letting that through
    // would report the *new* connection as closed and re-arm the retry grace
    // against a run that is perfectly healthy.
    const { result, rerender } = renderHook(
      ({ repoId }: { repoId: string }) => useIngestStream({ repoId, token: "t1" }),
      { initialProps: { repoId: "r1" } },
    );
    const superseded = lastSocket();
    act(() => superseded.open());

    rerender({ repoId: "r2" });
    act(() => lastSocket().open());

    act(() => superseded.serverClose());

    expect(result.current.closed).toBe(false);
    expect(result.current.connected).toBe(true);
  });

  it("ignores frames that arrive after unmount", () => {
    const { result, unmount } = renderHook(() => useIngestStream({ repoId: "r1", token: "t1" }));
    const socket = lastSocket();

    unmount();
    act(() => socket.emitFrame({ event: "clone_started", message: "too late" }));

    expect(result.current.frames).toHaveLength(0);
  });
});
