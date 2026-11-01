/**
 * Tests for the glossary search hook.
 *
 * Two behaviours are pinned here, and both are about *when* and *what* is
 * asked rather than about what is drawn:
 *
 * - **The debounce window.** The search box collects keystrokes before it
 *   acts on them, so a term typed in a hurry sends one request rather than
 *   one per character. The window is the web client's own, and the test
 *   pins the number so it cannot drift unnoticed.
 * - **The filtering.** A term goes to the server's search route, and no
 *   term goes to the browse route. The server does the matching, so the
 *   client's job is to send the right term to the right place -- and to
 *   treat a box holding only spaces as empty, because a space matches
 *   every definition that contains one.
 */

import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { getGlossary, searchGlossary } from "@/api/glossary";
import {
  GLOSSARY_SEARCH_DEBOUNCE_MS,
  useGlossarySearch,
} from "@/hooks/useGlossarySearch";

jest.mock("@/api/glossary", () => ({
  GLOSSARY_PAGE_SIZE: 20,
  getGlossary: jest.fn(),
  searchGlossary: jest.fn(),
}));

const getGlossaryMock = getGlossary as jest.MockedFunction<typeof getGlossary>;
const searchGlossaryMock = searchGlossary as jest.MockedFunction<
  typeof searchGlossary
>;

/**
 * The page the backend answers with.
 */
const PAGE = {
  entries: [
    {
      id: "entry-1",
      name: "ingest_repository",
      definition: "Queues and runs the ingestion task.",
      file_path: "app/tasks/ingest.py",
      line_number: 42,
      symbol_id: null,
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
};

/**
 * Render the hook against a query client.
 *
 * The wrapper is built with ``createElement`` rather than JSX so this file
 * stays a plain module, the way the pure-logic tests are.
 *
 * @returns The hook's result.
 */
async function renderSearch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const { result } = await renderHook(
    () => useGlossarySearch({ repoId: "repo-1" }),
    {
      wrapper: ({ children }: { children: React.ReactNode }) =>
        React.createElement(QueryClientProvider, { client }, children),
    },
  );

  return result;
}

/**
 * Type into the search box.
 *
 * The keystroke and the clock are kept in separate ``act`` blocks on
 * purpose: the effect that (re)starts the debounce runs when React flushes,
 * so the timer has to be scheduled before the clock is moved.
 *
 * @param result - The hook's result.
 * @param value - The text to type.
 */
async function type(
  result: { current: { setQuery: (value: string) => void } },
  value: string,
): Promise<void> {
  await act(async () => {
    result.current.setQuery(value);
  });
}

/**
 * Move the clock forward.
 *
 * @param ms - How many milliseconds to advance.
 */
async function advance(ms: number): Promise<void> {
  await act(async () => {
    jest.advanceTimersByTime(ms);
  });
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  getGlossaryMock.mockResolvedValue(PAGE);
  searchGlossaryMock.mockResolvedValue(PAGE);
});

afterEach(() => {
  jest.useRealTimers();
});

describe("useGlossarySearch", () => {
  it("uses the web client's debounce window", () => {
    // The web client waits 400 ms before acting on a search box. A shorter
    // window would send a request per character on a phone keyboard; a
    // longer one would make the search feel laggy.
    expect(GLOSSARY_SEARCH_DEBOUNCE_MS).toBe(400);
  });

  it("browses the whole glossary before anything is typed", async () => {
    const result = await renderSearch();

    await waitFor(() => {
      expect(getGlossaryMock).toHaveBeenCalledTimes(1);
    });
    expect(getGlossaryMock).toHaveBeenCalledWith("repo-1", 1, 20);
    expect(searchGlossaryMock).not.toHaveBeenCalled();
    expect(result.current.isSearching).toBe(false);
  });

  it("does not search until the debounce window has passed", async () => {
    const result = await renderSearch();

    await waitFor(() => {
      expect(getGlossaryMock).toHaveBeenCalledTimes(1);
    });

    await type(result, "ingest");
    await advance(GLOSSARY_SEARCH_DEBOUNCE_MS - 1);

    // Still inside the window: the reader is probably still typing.
    expect(searchGlossaryMock).not.toHaveBeenCalled();

    await advance(1);

    await waitFor(() => {
      expect(searchGlossaryMock).toHaveBeenCalledTimes(1);
    });
    expect(searchGlossaryMock).toHaveBeenCalledWith("repo-1", "ingest", 1, 20);
  });

  it("restarts the window when the reader keeps typing", async () => {
    const result = await renderSearch();

    await waitFor(() => {
      expect(getGlossaryMock).toHaveBeenCalledTimes(1);
    });

    // Type, wait most of the window, type again: the second keystroke
    // restarts the countdown, so the first term is never sent.
    await type(result, "ing");
    await advance(GLOSSARY_SEARCH_DEBOUNCE_MS - 100);
    await type(result, "ingest");
    await advance(GLOSSARY_SEARCH_DEBOUNCE_MS - 100);

    expect(searchGlossaryMock).not.toHaveBeenCalled();

    await advance(100);

    await waitFor(() => {
      expect(searchGlossaryMock).toHaveBeenCalledTimes(1);
    });
    // Only the settled term is sent, not the intermediate one.
    expect(searchGlossaryMock).toHaveBeenCalledWith("repo-1", "ingest", 1, 20);
  });

  it("treats a box holding only spaces as no term at all", async () => {
    const result = await renderSearch();

    await waitFor(() => {
      expect(getGlossaryMock).toHaveBeenCalledTimes(1);
    });

    await type(result, "   ");
    await advance(GLOSSARY_SEARCH_DEBOUNCE_MS);

    // A space matches every definition that contains one, which is not
    // what anybody typing a space means.
    expect(searchGlossaryMock).not.toHaveBeenCalled();
    expect(result.current.isSearching).toBe(false);
  });

  it("reports the entries the server matched", async () => {
    const result = await renderSearch();

    await waitFor(() => {
      expect(getGlossaryMock).toHaveBeenCalledTimes(1);
    });

    await type(result, "ingest");
    await advance(GLOSSARY_SEARCH_DEBOUNCE_MS);

    await waitFor(() => {
      expect(result.current.isSearching).toBe(true);
    });
    expect(result.current.entries).toHaveLength(1);
    expect(result.current.entries[0].name).toBe("ingest_repository");
    expect(result.current.total).toBe(1);
  });

  it("returns to the browse route when the search is cleared", async () => {
    const result = await renderSearch();

    await waitFor(() => {
      expect(getGlossaryMock).toHaveBeenCalledTimes(1);
    });

    await type(result, "ingest");
    await advance(GLOSSARY_SEARCH_DEBOUNCE_MS);

    await waitFor(() => {
      expect(searchGlossaryMock).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      result.current.reset();
    });
    await advance(GLOSSARY_SEARCH_DEBOUNCE_MS);

    await waitFor(() => {
      expect(result.current.isSearching).toBe(false);
    });
    expect(result.current.query).toBe("");
  });

  it("does not search at all without a repository", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const { result } = await renderHook(
      () => useGlossarySearch({ repoId: undefined }),
      {
        wrapper: ({ children }: { children: React.ReactNode }) =>
          React.createElement(QueryClientProvider, { client }, children),
      },
    );

    await advance(GLOSSARY_SEARCH_DEBOUNCE_MS * 2);

    expect(getGlossaryMock).not.toHaveBeenCalled();
    expect(searchGlossaryMock).not.toHaveBeenCalled();
    expect(result.current.entries).toHaveLength(0);
  });
});
