/**
 * Lightweight global toast store with auto-dismiss.
 * @module UseToast
 */
import { useCallback, useState } from "react";

/**
 * A single toast notification.
 */
export type Toast = {
  id: string;
  title?: string;
  description?: string;
  variant?: "default" | "success" | "error";
  open?: boolean;
};

// Module-level state shared across all hook subscribers.
let listeners: ((toasts: Toast[]) => void)[] = [];
let memoryState: Toast[] = [];

function notify() {
  listeners.forEach((l) => l(memoryState));
}

/**
 * Pushes a toast and auto-dismisses it after 4 seconds.
 *
 * @param t - Toast payload without the generated id.
 * @returns void
 */
export function toast(t: Omit<Toast, "id">) {
  const id = crypto.randomUUID();

  const newToast = { id, ...t };
  // Cap the stack so rapid fires don't overflow the viewport.
  memoryState = [newToast, ...memoryState].slice(0, 5);

  notify();

  setTimeout(() => {
    memoryState = memoryState.filter((x) => x.id !== id);
    notify();
  }, 4000);
}

/**
 * Subscribes a component to the shared toast stack.
 *
 * @returns Current toasts and the subscribe handle for the Toast host.
 */
export function useToastStore() {
  const [state, setState] = useState<Toast[]>(memoryState);

  const subscribe = useCallback(() => {
    listeners.push(setState);
    return () => {
      listeners = listeners.filter((l) => l !== setState);
    };
  }, []);

  return { state, subscribe };
}
