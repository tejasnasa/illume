/**
 * Wire TanStack Query's :data:`focusManager` to React Native's
 * :class:`AppState`.
 *
 * React Query's web default listens to the window's ``focus`` event; on
 * mobile there is no such signal, so queries never auto-refetch when the
 * user comes back from the background unless we install one. The bridge
 * is one ``AppState.addEventListener("change", ...)`` that forwards
 * ``status === "active"`` to React Query.
 *
 * Re-installation is guarded against so calling this twice does not
 * stack listeners. Tests that need a fresh install should call
 * :func:`__resetFocusManagerForTests` first.
 */

import { AppState, type AppStateStatus } from "react-native";
import { focusManager } from "@tanstack/react-query";

let installed = false;

/**
 * Install the AppState -> focusManager bridge. Idempotent; calling more
 * than once is a no-op so a re-render or HMR-triggered re-evaluation
 * cannot double-subscribe.
 */
export function installAppStateFocusBridge(): void {
  if (installed) return;
  installed = true;
  focusManager.setEventListener((handleFocus) => {
    const subscription = AppState.addEventListener(
      "change",
      (status: AppStateStatus) => {
        handleFocus(status === "active");
      },
    );
    return () => subscription.remove();
  });
}

/**
 * Reset the installation guard. Tests use this to install a fresh
 * listener with a mocked AppState; production code never calls it.
 */
export function __resetFocusManagerForTests(): void {
  installed = false;
}
