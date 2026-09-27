/**
 * A driveable stand-in for the browser's `WebSocket`.
 *
 * happy-dom does not ship one a test can push frames into, and both the
 * stream hook and anything built on it behave purely as a function of the
 * frames they receive -- so the fake records itself and the test fires the
 * handlers by hand.
 *
 * @module tests/mocks/fakeWebSocket
 */

import { vi } from "vitest";

export class FakeWebSocket {
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

  /** Open the socket. */
  open() {
    this.onopen?.();
  }

  /** Push a frame at the client. */
  emit(data: string) {
    this.onmessage?.({ data });
  }

  /** Push a JSON frame. */
  emitFrame(payload: Record<string, unknown>) {
    this.emit(JSON.stringify(payload));
  }

  /** Close the socket from the server side. */
  serverClose() {
    this.onclose?.();
  }
}

/** The most recently constructed socket. */
export function lastSocket(): FakeWebSocket {
  return FakeWebSocket.instances.at(-1)!;
}

/** Install the fake globally and clear any previous instances. */
export function installFakeWebSocket(): void {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
}
