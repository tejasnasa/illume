import { useCallback, useState } from "react";

export type Toast = {
  id: string;
  title?: string;
  description?: string;
  variant?: "default" | "success" | "error";
  open?: boolean;
};

let listeners: ((toasts: Toast[]) => void)[] = [];
let memoryState: Toast[] = [];

function notify() {
  listeners.forEach((l) => l(memoryState));
}

export function toast(t: Omit<Toast, "id">) {
  const id = crypto.randomUUID();

  const newToast = { id, ...t };
  memoryState = [newToast, ...memoryState].slice(0, 5);

  notify();

  setTimeout(() => {
    memoryState = memoryState.filter((x) => x.id !== id);
    notify();
  }, 4000);
}

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
