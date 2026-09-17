import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The store keeps its state at module scope, so it is shared by every test in this file
 * and survives between them. Each test therefore starts from a clean slate by resetting
 * the modules -- which is the same thing a page reload does -- rather than by trying to
 * unwind whatever the previous test left behind.
 */
beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/** Renders the store and subscribes it, which is what the Toast host does. */
async function mountStore() {
  const mod = await import("@/lib/use-toast");
  const view = renderHook(() => mod.useToastStore());
  act(() => {
    // The hook returns a subscribe handle rather than subscribing itself, so a test that
    // wants to observe pushes must call it -- exactly as `components/ui/Toast.tsx` does.
    view.result.current.subscribe();
  });
  return { mod, ...view };
}

describe("toast", () => {
  it("adds a toast to the stack", async () => {
    const { mod, result } = await mountStore();

    act(() => {
      mod.toast({ title: "Saved" });
    });

    expect(result.current.state).toHaveLength(1);
    expect(result.current.state[0].title).toBe("Saved");
  });

  it("generates an id", async () => {
    const { mod, result } = await mountStore();

    act(() => {
      mod.toast({ title: "Saved" });
    });

    expect(result.current.state[0].id).toBeTruthy();
  });

  it("gives each toast a distinct id", async () => {
    const { mod, result } = await mountStore();

    act(() => {
      mod.toast({ title: "First" });
      mod.toast({ title: "Second" });
    });

    const ids = result.current.state.map((t) => t.id);
    expect(new Set(ids).size).toBe(2);
  });

  it("puts the newest toast first", async () => {
    const { mod, result } = await mountStore();

    act(() => {
      mod.toast({ title: "First" });
      mod.toast({ title: "Second" });
    });

    // Newest-first so the most recent message is the one nearest the corner and the
    // first one a screen reader reaches.
    expect(result.current.state.map((t) => t.title)).toEqual(["Second", "First"]);
  });

  it("carries the variant and description through", async () => {
    const { mod, result } = await mountStore();

    act(() => {
      mod.toast({ title: "Failed", description: "Try again", variant: "error" });
    });

    expect(result.current.state[0]).toMatchObject({
      title: "Failed",
      description: "Try again",
      variant: "error",
    });
  });

  it("leaves the variant undefined when none is given", async () => {
    const { mod, result } = await mountStore();

    act(() => {
      mod.toast({ title: "Plain" });
    });

    expect(result.current.state[0].variant).toBeUndefined();
  });
});

describe("auto-dismiss", () => {
  it("removes the toast after four seconds", async () => {
    const { mod, result } = await mountStore();
    act(() => {
      mod.toast({ title: "Saved" });
    });

    act(() => {
      vi.advanceTimersByTime(4000);
    });

    expect(result.current.state).toHaveLength(0);
  });

  it("keeps the toast just before the deadline", async () => {
    const { mod, result } = await mountStore();
    act(() => {
      mod.toast({ title: "Saved" });
    });

    act(() => {
      vi.advanceTimersByTime(3999);
    });

    expect(result.current.state).toHaveLength(1);
  });

  it("dismisses only the toast whose timer fired", async () => {
    const { mod, result } = await mountStore();
    act(() => {
      mod.toast({ title: "First" });
    });
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    act(() => {
      mod.toast({ title: "Second" });
    });

    // The first one's timer expires here; the second still has two seconds to run.
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(result.current.state.map((t) => t.title)).toEqual(["Second"]);
  });
});

describe("stack cap", () => {
  it("keeps at most five toasts", async () => {
    const { mod, result } = await mountStore();

    act(() => {
      for (let i = 0; i < 8; i += 1) {
        mod.toast({ title: `Toast ${i}` });
      }
    });

    expect(result.current.state).toHaveLength(5);
  });

  it("drops the oldest toasts, keeping the newest", async () => {
    const { mod, result } = await mountStore();

    act(() => {
      for (let i = 0; i < 7; i += 1) {
        mod.toast({ title: `Toast ${i}` });
      }
    });

    // Toasts 0 and 1 fall off the end; the newest five survive, newest first.
    expect(result.current.state.map((t) => t.title)).toEqual([
      "Toast 6",
      "Toast 5",
      "Toast 4",
      "Toast 3",
      "Toast 2",
    ]);
  });
});

describe("subscribers", () => {
  it("notifies every subscriber", async () => {
    const mod = await import("@/lib/use-toast");
    const first = renderHook(() => mod.useToastStore());
    const second = renderHook(() => mod.useToastStore());
    act(() => {
      first.result.current.subscribe();
      second.result.current.subscribe();
    });

    act(() => {
      mod.toast({ title: "Shared" });
    });

    expect(first.result.current.state).toHaveLength(1);
    expect(second.result.current.state).toHaveLength(1);
  });

  it("stops notifying after unsubscribe", async () => {
    const mod = await import("@/lib/use-toast");
    const view = renderHook(() => mod.useToastStore());
    let unsubscribe: () => void = () => {};
    act(() => {
      unsubscribe = view.result.current.subscribe();
    });

    act(() => {
      unsubscribe();
      mod.toast({ title: "After unsubscribe" });
    });

    expect(view.result.current.state).toHaveLength(0);
  });

  it("reads the current state on mount rather than starting empty", async () => {
    // A subscriber that mounts *after* a toast was pushed must see it -- otherwise a
    // toast fired during navigation would be invisible to the host that renders it.
    const mod = await import("@/lib/use-toast");
    act(() => {
      mod.toast({ title: "Before mount" });
    });

    const view = renderHook(() => mod.useToastStore());

    expect(view.result.current.state).toHaveLength(1);
    expect(view.result.current.state[0].title).toBe("Before mount");
  });
});

describe("crypto", () => {
  it("uses crypto.randomUUID for ids", async () => {
    const spy = vi.spyOn(crypto, "randomUUID");
    const mod = await import("@/lib/use-toast");

    act(() => {
      mod.toast({ title: "Saved" });
    });

    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });
});
