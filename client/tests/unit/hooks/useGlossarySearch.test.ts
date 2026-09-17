import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const REPO_ID = "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30";
const SEARCH_URL = `${BACKEND_URL}/api/v1/repository/${REPO_ID}/glossary/search`;

const PAGE = {
  entries: [
    {
      id: "1",
      name: "Cache",
      definition: "Stores values.",
      file_path: "a.py",
      line_number: 1,
      symbol_id: null,
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
};

/** Registers a search handler that records every query it receives. */
function stub(handler?: (request: Request) => Response | Promise<Response>) {
  const requests: URL[] = [];
  server.use(
    http.get(SEARCH_URL, async ({ request }) => {
      requests.push(new URL(request.url));
      if (handler) return handler(request);
      return HttpResponse.json(PAGE);
    }),
  );
  return requests;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("initial state", () => {
  it("starts with no results", async () => {
    stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");

    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    expect(result.current.results).toBeNull();
    expect(result.current.page).toBe(1);
    expect(result.current.loading).toBe(false);
  });

  it("makes no request until the form is submitted", async () => {
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");

    renderHook(() => useGlossarySearch(REPO_ID));

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(requests).toHaveLength(0);
  });
});

describe("submitting", () => {
  it("requests the search route, not the browse one", async () => {
    // `/glossary?q=` hits the browse handler, which takes no `q` and returns everything.
    // The path is the difference between a working search and one that looks like it
    // works, so it is asserted explicitly.
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });

    expect(requests[0].pathname).toBe(`/api/v1/repository/${REPO_ID}/glossary/search`);
  });

  it("sends the query, page, and page size", async () => {
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });

    expect(requests[0].searchParams.get("q")).toBe("cache");
    expect(requests[0].searchParams.get("page")).toBe("1");
    expect(requests[0].searchParams.get("page_size")).toBe("20");
  });

  it("encodes a query containing reserved characters", async () => {
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "a b&c=d");
      await result.current.onSubmit();
    });

    expect(requests[0].searchParams.get("q")).toBe("a b&c=d");
  });

  it("stores the results", async () => {
    stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });

    await waitFor(() => expect(result.current.results).toEqual(PAGE));
  });

  it("always resets to page one", async () => {
    // Submitting a new query from page 3 must not ask for page 3 of the new results.
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "first");
      await result.current.onSubmit();
    });
    await act(async () => {
      await result.current.goToPage(3);
    });
    await act(async () => {
      result.current.form.setValue("query", "second");
      await result.current.onSubmit();
    });

    expect(requests.at(-1)?.searchParams.get("page")).toBe("1");
    expect(requests.at(-1)?.searchParams.get("q")).toBe("second");
  });

  it("clears the loading flag when the request finishes", async () => {
    stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });

    expect(result.current.loading).toBe(false);
  });

  it("does not send a request for an empty query", async () => {
    // `q` is declared `min_length=1` on the backend, so an empty term is a guaranteed 422
    // -- and the search field has no validation, so pressing Enter on an untouched box is
    // the obvious way to send one. It cannot match anything, so the round trip is skipped
    // rather than sent and handled.
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      await result.current.onSubmit().catch(() => {});
    });

    expect(requests).toHaveLength(0);
  });

  it("does not send a request for a whitespace-only query", async () => {
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "   ");
      await result.current.onSubmit().catch(() => {});
    });

    expect(requests).toHaveLength(0);
  });
});

describe("pagination", () => {
  it("reuses the last submitted query", async () => {
    // `goToPage` takes only a page number, so it has to remember the query. Losing it
    // would silently search for the empty string on every page change.
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });
    await act(async () => {
      await result.current.goToPage(2);
    });

    expect(requests.at(-1)?.searchParams.get("q")).toBe("cache");
    expect(requests.at(-1)?.searchParams.get("page")).toBe("2");
  });

  it("updates the page state", async () => {
    stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });
    await act(async () => {
      await result.current.goToPage(4);
    });

    expect(result.current.page).toBe(4);
  });

  it("sends no request if paged before searching", async () => {
    // `goToPage` reuses the remembered query, and before any search that is empty -- so
    // paging early hits the same short-circuit instead of a guaranteed 422.
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      await result.current.goToPage(2);
    });

    expect(requests).toHaveLength(0);
  });
});

describe("errors", () => {
  it("surfaces a failed search instead of rejecting into the void", async () => {
    // The component mounts this as `<form onSubmit={onSubmit}>`, and React does not await
    // a submit handler -- so an escaping rejection was an unhandled promise rejection.
    // The spinner stopped, the stale results stayed on screen, and the user read that as
    // "no matches found".
    stub(() => new HttpResponse(null, { status: 500 }) as unknown as Response);
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });

    expect(result.current.error).toBe("Failed to fetch glossary");
  });

  it("clears a previous error when a retry starts", async () => {
    // A stale error banner sitting over fresh results would read as "this search failed"
    // when it did not.
    let call = 0;
    stub(() =>
      (call += 1) === 1
        ? (new HttpResponse(null, { status: 500 }) as unknown as Response)
        : (HttpResponse.json(PAGE) as unknown as Response),
    );
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });
    expect(result.current.error).toBeTruthy();

    await act(async () => {
      await result.current.onSubmit();
    });

    expect(result.current.error).toBeNull();
  });

  it("clears the loading flag after a failure", async () => {
    // The `finally` is what makes a retry possible; without it the spinner would persist
    // and the next submit would look like it did nothing.
    stub(() => new HttpResponse(null, { status: 500 }) as unknown as Response);
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit().catch(() => {});
    });

    expect(result.current.loading).toBe(false);
  });

  it("leaves previous results in place after a failure", async () => {
    // Stale results stay on screen rather than blanking, which is deliberate: the user
    // keeps something to look at while the error surfaces.
    let call = 0;
    stub(() => {
      call += 1;
      return (call === 1
        ? HttpResponse.json(PAGE)
        : new HttpResponse(null, { status: 500 })) as unknown as Response;
    });
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });
    await act(async () => {
      result.current.form.setValue("query", "other");
      await result.current.onSubmit().catch(() => {});
    });

    expect(result.current.results).toEqual(PAGE);
  });
});

describe("reset", () => {
  it("clears the results and the page", async () => {
    stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });
    await act(async () => {
      await result.current.goToPage(3);
    });

    act(() => {
      result.current.reset();
    });

    expect(result.current.results).toBeNull();
    expect(result.current.page).toBe(1);
  });

  it("clears the remembered query", async () => {
    // If `lastQuery` survived a reset, the pager would still be usable and would search
    // for a term the user can no longer see in the box.
    const requests = stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });
    const afterSearch = requests.length;

    act(() => {
      result.current.reset();
    });
    await act(async () => {
      await result.current.goToPage(2);
    });

    expect(requests).toHaveLength(afterSearch);
  });

  it("empties the form field", async () => {
    stub();
    const { useGlossarySearch } = await import("@/hooks/useGlossarySearch");
    const { result } = renderHook(() => useGlossarySearch(REPO_ID));

    await act(async () => {
      result.current.form.setValue("query", "cache");
      await result.current.onSubmit();
    });
    act(() => {
      result.current.reset();
    });

    expect(result.current.form.getValues("query")).toBe("");
  });
});
