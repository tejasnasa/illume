/**
 * Tests for the AppState -> TanStack Query :data:`focusManager` bridge.
 *
 * The bridge is what makes cached queries refetch when the user comes
 * back from the background -- without it, mobile screens would show
 * stale data until the user pulled to refresh. The bridge is small
 * enough to test in isolation; this file mocks :data:`AppState` and
 * drives transitions directly to observe the boolean React Query is
 * told for each one.
 */

import {
  installAppStateFocusBridge,
  __resetFocusManagerForTests,
} from "@/api/focusManager";

type AppStateHandler = (status: string) => void;

describe("installAppStateFocusBridge", () => {
  beforeEach(() => {
    __resetFocusManagerForTests();
  });

  /**
   * Capture the AppState handler the bridge installs.
   *
   * The bridge's :func:`installAppStateFocusBridge` calls
   * ``AppState.addEventListener("change", handler)`` where
   * ``handler = (status) => handleFocus(status === "active")``.
   * We replace :func:`AppState.addEventListener` with a capture-only
   * shim and drive the captured handler to feed transitions through
   * the real React Query focus manager. We subscribe to the focus
   * changes React Query emits via :data:`focusManager.subscribe`.
   */
  function captureBridge(): {
    driveAppState: (status: "active" | "background") => void;
    forwarded: boolean[];
    unsubscribe: () => void;
  } {
    const { AppState } = require("react-native");
    const { focusManager } = require("@tanstack/react-query");

    let appStateHandler: AppStateHandler | null = null;
    AppState.addEventListener = ((_event: string, handler: AppStateHandler) => {
      appStateHandler = handler;
      return { remove: () => {} };
    }) as typeof AppState.addEventListener;

    // Subscribe to focus changes so we can record what React Query is
    // told. The real bridge drives this through the production code
    // path -- we only intercept the AppState side.
    const forwarded: boolean[] = [];
    const unsubscribe = focusManager.subscribe((focused: boolean) => {
      forwarded.push(focused);
    });

    installAppStateFocusBridge();

    return {
      driveAppState: (status: "active" | "background") => {
        if (!appStateHandler) {
          throw new Error("bridge did not install an AppState listener");
        }
        appStateHandler(status);
      },
      forwarded,
      unsubscribe,
    };
  }

  it("forwards active and background transitions to focusManager.handleFocus", () => {
    const { driveAppState, forwarded } = captureBridge();
    driveAppState("active");
    driveAppState("background");
    driveAppState("active");
    expect(forwarded).toEqual([true, false, true]);
  });

  it("installs exactly one AppState listener per install", () => {
    const { AppState } = require("react-native");
    let addCount = 0;
    AppState.addEventListener = (() => {
      addCount += 1;
      return { remove: () => {} };
    }) as typeof AppState.addEventListener;
    installAppStateFocusBridge();
    installAppStateFocusBridge();
    installAppStateFocusBridge();
    expect(addCount).toBe(1);
  });

  it("__resetFocusManagerForTests allows re-installation", () => {
    const { AppState } = require("react-native");
    let addCount = 0;
    AppState.addEventListener = (() => {
      addCount += 1;
      return { remove: () => {} };
    }) as typeof AppState.addEventListener;
    installAppStateFocusBridge();
    expect(addCount).toBe(1);
    __resetFocusManagerForTests();
    installAppStateFocusBridge();
    expect(addCount).toBe(2);
  });
});
