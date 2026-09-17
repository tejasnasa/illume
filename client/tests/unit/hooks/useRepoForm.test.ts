import { act, renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), back: vi.fn() }),
}));

const CREATE_URL = `${BACKEND_URL}/api/v1/repository`;

/**
 * Replaces `alert`, which this hook uses to report failures.
 *
 * Defined rather than spied on: happy-dom does not implement `window.alert` at all, so
 * there is no existing function to wrap. The hook calls the bare global, so stubbing the
 * global is what it will resolve to.
 */
function alertSpy() {
  const spy = vi.fn();
  vi.stubGlobal("alert", spy);
  return spy;
}

/** Mounts the hook with `github_url` filled in and submits. */
async function submitWith(url: string) {
  const { default: useRepoForm } = await import("@/hooks/useRepoForm");
  const { result } = renderHook(() => useRepoForm());
  await act(async () => {
    result.current.register("github_url").onChange({
      target: { value: url, name: "github_url" },
    });
  });
  await act(async () => {
    await result.current.onSubmit();
  });
  return result;
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  // `restoreAllMocks` does not undo `stubGlobal`, so the alert stub would otherwise leak
  // into every later test file in this worker.
  vi.unstubAllGlobals();
});

describe("validation gate", () => {
  it("does not submit an empty form", async () => {
    const spy = vi.fn();
    server.use(
      http.post(CREATE_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );
    const { default: useRepoForm } = await import("@/hooks/useRepoForm");
    const { result } = renderHook(() => useRepoForm());

    await act(async () => {
      await result.current.onSubmit();
    });

    expect(spy).not.toHaveBeenCalled();
  });

  it("rejects a non-GitHub URL before sending", async () => {
    const spy = vi.fn();
    server.use(
      http.post(CREATE_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );

    const result = await submitWith("https://gitlab.com/example/project");

    expect(result.current.firstError).toMatch(/must point to a valid/i);
    expect(spy).not.toHaveBeenCalled();
  });

  it("rejects a bare github.com URL", async () => {
    const result = await submitWith("https://github.com");

    expect(result.current.firstError).toMatch(/must point to a valid/i);
  });
});

describe("successful submission", () => {
  it("posts the URL", async () => {
    let body: { github_url?: string } = {};
    let method = "";
    server.use(
      http.post(CREATE_URL, async ({ request }) => {
        method = request.method;
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ repo_id: "abc", repo_num: 12 }, { status: 202 });
      }),
    );

    await submitWith("https://github.com/example/project");

    expect(method).toBe("POST");
    expect(body.github_url).toBe("https://github.com/example/project");
  });

  it("navigates to the new repository by its number", async () => {
    // The route is `/repo/{repo_num}`, the user-scoped integer -- not the UUID, which the
    // response also carries. Picking the wrong field would 404 on arrival.
    server.use(
      http.post(CREATE_URL, () => HttpResponse.json({ repo_id: "abc", repo_num: 12 }, { status: 202 })),
    );

    await submitWith("https://github.com/example/project");

    expect(push).toHaveBeenCalledWith("/repo/12");
  });

  it("sends credentials", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    server.use(
      http.post(CREATE_URL, () => HttpResponse.json({ repo_id: "abc", repo_num: 12 }, { status: 202 })),
    );

    await submitWith("https://github.com/example/project");

    expect(spy.mock.calls[0][1]?.credentials).toBe("include");
  });

  it("accepts a 202 rather than expecting a 200", async () => {
    // Ingestion is queued, not completed, so the correct status is 202. Treating anything
    // but 200 as a failure would break the primary action.
    server.use(
      http.post(CREATE_URL, () => HttpResponse.json({ repo_id: "abc", repo_num: 12 }, { status: 202 })),
    );

    await submitWith("https://github.com/example/project");

    expect(push).toHaveBeenCalled();
  });

  it("does not navigate when the request fails", async () => {
    alertSpy();
    server.use(http.post(CREATE_URL, () => new HttpResponse(null, { status: 500 })));

    await submitWith("https://github.com/example/project");

    expect(push).not.toHaveBeenCalled();
  });
});

describe("failure reporting", () => {
  it("uses alert rather than an inline error", async () => {
    // The odd one out among the form hooks: the other two set a banner error. Worth
    // pinning because it is the difference a test would otherwise miss.
    const alert = alertSpy();
    server.use(
      http.post(CREATE_URL, () =>
        HttpResponse.json({ detail: "Repository already exists" }, { status: 400 }),
      ),
    );

    await submitWith("https://github.com/example/project");

    expect(alert).toHaveBeenCalled();
  });

  it("alerts the backend's own message", async () => {
    // `alert()` is the worst place for a message nobody wrote: the user gets a modal they
    // must dismiss that tells them nothing about what to change. The backend's `detail` at
    // least names the problem.
    const alert = alertSpy();
    server.use(
      http.post(CREATE_URL, () =>
        HttpResponse.json({ detail: "Repository already exists" }, { status: 400 }),
      ),
    );

    await submitWith("https://github.com/example/project");

    expect(alert).toHaveBeenCalledWith("Repository already exists");
  });

  it("falls back to the generic message when the body carries no reason", async () => {
    const alert = alertSpy();
    server.use(http.post(CREATE_URL, () => new HttpResponse(null, { status: 500 })));

    await submitWith("https://github.com/example/project");

    expect(alert).toHaveBeenCalledWith("Something went wrong. Please try again.");
  });

  it("does not set an inline error on failure", async () => {
    // The message goes to `alert`, so `firstError` stays undefined after a server-side
    // rejection -- only client-side validation populates it.
    alertSpy();
    server.use(http.post(CREATE_URL, () => new HttpResponse(null, { status: 500 })));

    const result = await submitWith("https://github.com/example/project");

    expect(result.current.firstError).toBeUndefined();
  });

  it("clears the submitting flag after a failure", async () => {
    alertSpy();
    server.use(http.post(CREATE_URL, () => new HttpResponse(null, { status: 500 })));

    const result = await submitWith("https://github.com/example/project");

    expect(result.current.isSubmitting).toBe(false);
  });
});
