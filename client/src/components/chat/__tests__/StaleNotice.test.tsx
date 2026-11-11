import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import StaleNotice from "@/components/chat/StaleNotice";

const CHANGES = {
  stale_paths: ["app/auth.py", "app/users.py"],
  commits: [
    {
      hash: "0123456789abcdef",
      message: "fix: reject expired tokens\n\nLonger body",
      author_name: "Ada Lovelace",
      authored_at: "2026-02-03T10:00:00Z",
      files: ["app/auth.py"],
    },
  ],
  compare_url: "https://github.com/acme/app/compare/abc...def",
};

function mockChanges(body: unknown = CHANGES, status = 200) {
  const fetchMock = vi.fn(async () => Response.json(body, { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderNotice(onReask?: () => void) {
  return render(
    <StaleNotice
      repoId="repo-1"
      messageId="msg-1"
      stale={{ paths: ["app/auth.py"] }}
      onReask={onReask}
    />,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("StaleNotice", () => {
  it("shows a badge and loads nothing until it is opened", () => {
    const fetchMock = mockChanges();
    renderNotice();

    expect(
      screen.getByRole("button", { name: /May be out of date/ }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("stale-panel")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads the changes endpoint when expanded and lists files, commits and the compare link", async () => {
    const fetchMock = mockChanges();
    renderNotice();

    fireEvent.click(screen.getByRole("button", { name: /May be out of date/ }));

    const panel = await screen.findByTestId("stale-panel");
    await waitFor(() =>
      expect(within(panel).getByTestId("stale-commits")).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toMatch(/\/api\/v1\/repository\/repo-1\/chat\/msg-1\/changes$/);
    expect(init.credentials).toBe("include");

    expect(within(panel).getByText("app/users.py")).toBeInTheDocument();
    const commits = within(panel).getByTestId("stale-commits");
    expect(commits).toHaveTextContent("0123456");
    expect(commits).toHaveTextContent("fix: reject expired tokens");
    expect(commits).not.toHaveTextContent("Longer body");
    expect(commits).toHaveTextContent("Ada Lovelace");
    expect(commits).toHaveTextContent("2026-02-03");
    expect(
      within(panel).getByRole("link", { name: /Compare on GitHub/ }),
    ).toHaveAttribute("href", "https://github.com/acme/app/compare/abc...def");
  });

  it("shows the files the history already knows about while the changes load", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    renderNotice();

    fireEvent.click(screen.getByRole("button", { name: /May be out of date/ }));

    const panel = await screen.findByTestId("stale-panel");
    expect(within(panel).getByText("app/auth.py")).toBeInTheDocument();
    expect(within(panel).getByRole("status")).toHaveTextContent(/Loading/);
  });

  it("fetches once, however often it is toggled", async () => {
    const fetchMock = mockChanges();
    renderNotice();
    const badge = screen.getByRole("button", { name: /May be out of date/ });

    fireEvent.click(badge);
    await screen.findByTestId("stale-commits");
    fireEvent.click(badge);
    fireEvent.click(badge);

    expect(await screen.findByTestId("stale-commits")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("says so when the changes cannot be loaded, and retries on request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("no", { status: 500 }))
      .mockResolvedValueOnce(Response.json(CHANGES));
    vi.stubGlobal("fetch", fetchMock);
    renderNotice();

    fireEvent.click(screen.getByRole("button", { name: /May be out of date/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Could not load the changes/,
    );

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("stale-commits")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("says so when no commit is listed, and omits the link without one", async () => {
    mockChanges({
      stale_paths: ["app/auth.py"],
      commits: [],
      compare_url: null,
    });
    renderNotice();

    fireEvent.click(screen.getByRole("button", { name: /May be out of date/ }));

    expect(
      await screen.findByText(/No mined commits are listed/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("re-asks when the button is pressed", () => {
    mockChanges();
    const onReask = vi.fn();
    renderNotice(onReask);

    fireEvent.click(screen.getByRole("button", { name: "Re-ask" }));

    expect(onReask).toHaveBeenCalledTimes(1);
  });

  it("offers no Re-ask while a run is live", () => {
    mockChanges();
    renderNotice(undefined);

    expect(
      screen.queryByRole("button", { name: "Re-ask" }),
    ).not.toBeInTheDocument();
  });
});
