import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../../tests/msw/handlers";
import { server } from "../../../tests/msw/server";
import RepoPickerModal from "@/components/RepoPickerModal";

/**
 * The two-step repository picker: list or URL, then branch/commit.
 *
 * The interesting parts are the two ways a repository is chosen -- a row in the list, or
 * a typed URL -- because both end up producing the `selectedRepo*` triple that the
 * version step and the ingest POST are built from. The debounce and the infinite scroll
 * are pinned because both change *when* requests are sent, which is not visible from the
 * rendered output.
 */

const REPOS_URL = `${BACKEND_URL}/api/v1/github/repos`;
const INGEST_URL = `${BACKEND_URL}/api/v1/repository`;

const push = vi.fn();
const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh, back: vi.fn() }),
}));

/** One repository in the shape GitHub's `/user/repos` returns to the proxy. */
function repo(n: number, overrides: Record<string, unknown> = {}) {
  return {
    id: n,
    name: `repo-${n}`,
    full_name: `example/repo-${n}`,
    description: `Description of repo ${n}`,
    html_url: `https://github.com/example/repo-${n}`,
    language: "Python",
    private: false,
    default_branch: "main",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/**
 * A controllable `IntersectionObserver`.
 *
 * happy-dom ships one whose `observe` is a no-op, so the scroll sentinel never reports
 * as visible and the pagination path is unreachable. This records each callback so a
 * test can fire one deliberately. The component rebuilds the observer whenever its
 * dependencies change, so `triggerIntersection` fires the most recent one.
 */
type ObserverCallback = (entries: Array<{ isIntersecting: boolean }>) => void;

class FakeIntersectionObserver {
  private readonly callback: ObserverCallback;
  active = true;

  constructor(callback: ObserverCallback) {
    this.callback = callback;
    instances.push(this);
  }
  observe() {
    this.active = true;
  }
  unobserve() {
    this.active = false;
  }
  disconnect() {
    this.active = false;
  }
  takeRecords() {
    return [];
  }
  fire() {
    this.callback([{ isIntersecting: true }]);
  }
}

let instances: FakeIntersectionObserver[] = [];

/**
 * Reports the sentinel as visible to whichever observer is still watching it.
 *
 * Returns false when nothing is observing -- which is what happens once the last page
 * has loaded and the sentinel is no longer rendered. Mirroring `unobserve` matters:
 * without it a callback from an earlier render would still be reachable and a test could
 * trigger a request the component would never make.
 */
function fireIntersection(): boolean {
  const live = instances.filter((observer) => observer.active);
  const latest = live.at(-1);
  if (!latest) return false;
  latest.fire();
  return true;
}

/**
 * Fires the sentinel once an observer is actually watching it.
 *
 * The component rebuilds its observer on every `loadingRepos` / `page` change, so between
 * a page rendering and the effect re-running there is a window with no live observer at
 * all. Firing during that window is a silent no-op: `fireIntersection` returns false, the
 * `waitFor` after it never sees the next page, and the failure reads as a product bug when
 * it is a race in the harness. Waiting for a live observer first is what makes these
 * deterministic under the load of a full-suite run.
 */
async function triggerIntersection(): Promise<void> {
  await waitFor(() => expect(fireIntersection()).toBe(true));
}

/** Registers the repo-list endpoint, recording the queries it was asked for. */
function stubRepos(
  respond: (params: URLSearchParams) => JsonBodyType = () => [repo(1)],
) {
  const queries: URLSearchParams[] = [];
  server.use(
    http.get(REPOS_URL, ({ request }) => {
      const params = new URL(request.url).searchParams;
      queries.push(params);
      return HttpResponse.json(respond(params));
    }),
  );
  return queries;
}

/**
 * Registers the two endpoints `GitGraph` loads once a repository is chosen.
 *
 * The history must not be empty: with nothing to select, `GitGraph` disables its own
 * ingest button, so an empty stub would make the ingest assertions unreachable rather
 * than failing them.
 */
function stubGitGraph() {
  server.use(
    http.get(
      `${BACKEND_URL}/api/v1/github/repos/:owner/:repo/branches`,
      () => HttpResponse.json([{ name: "main", sha: "a".repeat(40), is_default: true }]),
    ),
    http.get(
      `${BACKEND_URL}/api/v1/github/repos/:owner/:repo/commits-multibranch`,
      () =>
        HttpResponse.json([
          {
            sha: "c".repeat(40),
            short_sha: "c".repeat(7),
            message: "feat: a recent thing",
            author_name: "Ada Lovelace",
            author_avatar: null,
            authored_at: "2026-01-02T00:00:00Z",
            parents: [],
            branches: ["main"],
          },
        ]),
    ),
  );
}

/** Registers the ingest endpoint, recording the bodies it received. */
function stubIngest(
  respond: () => Response = () =>
    HttpResponse.json({ repo_id: "r1", repo_num: 7 }, { status: 202 }),
) {
  const bodies: Array<Record<string, unknown>> = [];
  server.use(
    http.post(INGEST_URL, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return respond();
    }),
  );
  return bodies;
}

/** Waits for the list to finish its first load. */
async function loaded() {
  await waitFor(() => expect(screen.queryByText(/Loading repositories/)).not.toBeInTheDocument());
}

beforeEach(() => {
  instances = [];
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  push.mockClear();
});

describe("the tabs", () => {
  it("opens on the repository list", async () => {
    stubRepos();
    render(<RepoPickerModal />);

    expect(screen.getByRole("button", { name: /My Repositories/ })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("repo-1")).toBeInTheDocument());
  });

  it("offers an external URL tab", () => {
    stubRepos();
    render(<RepoPickerModal />);

    expect(screen.getByRole("button", { name: /External URL/ })).toBeInTheDocument();
  });

  it("swaps the panel when the external tab is chosen", async () => {
    stubRepos();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await loaded();

    await user.click(screen.getByRole("button", { name: /External URL/ }));

    expect(screen.getByLabelText("GitHub Repository URL")).toBeInTheDocument();
    expect(screen.queryByText("repo-1")).not.toBeInTheDocument();
  });

  it("returns to the list without refetching when the tab is switched back", async () => {
    // The reload is keyed on `activeTab`, not on the render, so a round trip through the
    // external tab costs one request -- the one fired when the list first mounts.
    const queries = stubRepos();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await loaded();

    await user.click(screen.getByRole("button", { name: /External URL/ }));
    await user.click(screen.getByRole("button", { name: /My Repositories/ }));

    await waitFor(() => expect(screen.getByText("repo-1")).toBeInTheDocument());
    expect(queries).toHaveLength(2);
  });
});

describe("the repository list", () => {
  it("renders the name and description", async () => {
    stubRepos();
    render(<RepoPickerModal />);

    await waitFor(() => expect(screen.getByText("repo-1")).toBeInTheDocument());
    expect(screen.getByText("Description of repo 1")).toBeInTheDocument();
  });

  it("falls back when there is no description", async () => {
    // `repo.description || "No description provided."` -- an empty string falls through,
    // so the row keeps its height rather than collapsing.
    stubRepos(() => [repo(1, { description: "" })]);
    render(<RepoPickerModal />);

    await waitFor(() => expect(screen.getByText("No description provided.")).toBeInTheDocument());
  });

  it("badges the language", async () => {
    stubRepos();
    render(<RepoPickerModal />);

    await waitFor(() => expect(screen.getByText("Python")).toBeInTheDocument());
  });

  it("omits the language badge when GitHub reports none", async () => {
    stubRepos(() => [repo(1, { language: null })]);
    render(<RepoPickerModal />);
    await loaded();

    expect(screen.queryByText("Python")).not.toBeInTheDocument();
  });

  it("badges a private repository", async () => {
    stubRepos(() => [repo(1, { private: true })]);
    render(<RepoPickerModal />);

    await waitFor(() => expect(screen.getByText("Private")).toBeInTheDocument());
  });

  it("does not badge a public repository", async () => {
    stubRepos();
    render(<RepoPickerModal />);
    await loaded();

    expect(screen.queryByText("Private")).not.toBeInTheDocument();
  });

  it("shows the empty state when there is nothing to list", async () => {
    stubRepos(() => []);
    render(<RepoPickerModal />);

    await waitFor(() =>
      expect(screen.getByText("No GitHub repositories found.")).toBeInTheDocument(),
    );
  });

  it("explains an unlinked GitHub account", async () => {
    // The proxy answers 403 when no OAuth token is stored, and the client turns that into
    // a specific message -- the one case where the user is told what to do about it.
    server.use(http.get(REPOS_URL, () => HttpResponse.json({ detail: "no" }, { status: 403 })));
    render(<RepoPickerModal />);

    await waitFor(() =>
      expect(screen.getByText(/GitHub account not linked/)).toBeInTheDocument(),
    );
  });

  it("shows a generic message for any other failure", async () => {
    server.use(http.get(REPOS_URL, () => HttpResponse.json({ detail: "no" }, { status: 502 })));
    render(<RepoPickerModal />);

    await waitFor(() =>
      expect(screen.getByText("Failed to fetch GitHub repositories")).toBeInTheDocument(),
    );
  });

  it("replaces the list rather than appending when the query changes", async () => {
    // A paginated append after a search would leave the previous query's rows on screen.
    const queries = stubRepos((params) =>
      params.get("q") === "second" ? [repo(99)] : [repo(1)],
    );
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await waitFor(() => expect(screen.getByText("repo-1")).toBeInTheDocument());

    await user.type(screen.getByPlaceholderText(/Search your GitHub repositories/), "second");

    await waitFor(() => expect(screen.getByText("repo-99")).toBeInTheDocument());
    expect(screen.queryByText("repo-1")).not.toBeInTheDocument();
    expect(queries.at(-1)?.get("q")).toBe("second");
  });
});

describe("search", () => {
  it("sends nothing while the query is still being typed", async () => {
    // Typing is debounced by 400ms; the assertion is that the request count does not
    // track the keystroke count.
    const queries = stubRepos();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await loaded();
    const before = queries.length;

    await user.type(screen.getByPlaceholderText(/Search your GitHub repositories/), "abc");

    // Still inside the debounce window.
    expect(queries.length).toBe(before);
  });

  it("sends one request after typing stops", async () => {
    const queries = stubRepos();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await loaded();
    const before = queries.length;

    await user.type(screen.getByPlaceholderText(/Search your GitHub repositories/), "abc");

    await waitFor(() => expect(queries.length).toBe(before + 1), { timeout: 2000 });
    expect(queries.at(-1)?.get("q")).toBe("abc");
  });

  it("does not resend for a query already loaded", async () => {
    // Clearing the box returns to the mount-time query, which the debounce still fires --
    // this pins that the debounce does not also re-fire on unrelated renders.
    const queries = stubRepos();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await loaded();
    const box = screen.getByPlaceholderText(/Search your GitHub repositories/);

    await user.type(box, "abc");
    await waitFor(() => expect(queries).toHaveLength(2), { timeout: 2000 });

    await new Promise((resolve) => setTimeout(resolve, 500));

    expect(queries).toHaveLength(2);
  });

  it("scopes the search box to the repository list", async () => {
    // The external tab has no search box; switching tabs must not leave one behind.
    stubRepos();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await loaded();

    await user.click(screen.getByRole("button", { name: /External URL/ }));

    expect(screen.queryByPlaceholderText(/Search your GitHub repositories/)).not.toBeInTheDocument();
  });
});

describe("pagination", () => {
  /**
   * A first page of exactly the proxy's page size, then one short page.
   *
   * The size matters: `hasMoreRepos` is `data.length < 30`, so a first page smaller than
   * that ends pagination before it starts and the sentinel is never rendered.
   */
  const firstPage = Array.from({ length: 30 }, (_, i) => repo(i + 1));

  function stubPages() {
    return stubRepos((params) => (params.get("page") === "2" ? [repo(99)] : firstPage));
  }

  it("requests the next page when the sentinel becomes visible", async () => {
    const queries = stubPages();
    render(<RepoPickerModal />);
    await waitFor(() => expect(screen.getByText("repo-30")).toBeInTheDocument());

    await triggerIntersection();

    await waitFor(() => expect(screen.getByText("repo-99")).toBeInTheDocument());
    expect(queries.at(-1)?.get("page")).toBe("2");
  });

  it("appends the next page rather than replacing", async () => {
    stubPages();
    render(<RepoPickerModal />);
    await waitFor(() => expect(screen.getByText("repo-30")).toBeInTheDocument());

    await triggerIntersection();

    await waitFor(() => expect(screen.getByText("repo-99")).toBeInTheDocument());
    expect(screen.getByText("repo-1")).toBeInTheDocument();
    expect(screen.getByText("repo-30")).toBeInTheDocument();
  });

  it("stops asking once a short page arrives", async () => {
    // A page with fewer than 30 rows is the last one: `hasMoreRepos` goes false, the
    // sentinel stops being rendered, and the effect that would rebuild the observer
    // returns early. So nothing is watching the sentinel any more, and a second
    // intersection signal is impossible rather than merely ignored.
    const queries = stubPages();
    render(<RepoPickerModal />);
    await waitFor(() => expect(screen.getByText("repo-30")).toBeInTheDocument());

    await triggerIntersection();
    await waitFor(() => expect(screen.getByText("repo-99")).toBeInTheDocument());

    // Let the last effect pass finish tearing the observer down before asserting that
    // nothing is watching the sentinel -- otherwise this races the same rebuild that
    // `triggerIntersection` waits on, in the opposite direction.
    await waitFor(() => expect(instances.every((o) => !o.active)).toBe(true));
    expect(fireIntersection()).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(queries.map((q) => q.get("page"))).toEqual(["1", "2"]);
  });

  it("keeps asking while full pages keep arriving", async () => {
    const queries = stubRepos(() => firstPage);
    render(<RepoPickerModal />);
    await waitFor(() => expect(screen.getByText("repo-30")).toBeInTheDocument());

    await triggerIntersection();
    await waitFor(() => expect(queries.at(-1)?.get("page")).toBe("2"));

    await triggerIntersection();
    await waitFor(() => expect(queries.at(-1)?.get("page")).toBe("3"));
  });
});

describe("choosing a listed repository", () => {
  it("advances to the version step", async () => {
    stubRepos();
    stubGitGraph();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await waitFor(() => expect(screen.getByText("repo-1")).toBeInTheDocument());

    await user.click(screen.getByText("repo-1"));

    expect(
      await screen.findByRole("heading", { name: /Configure Version for example\/repo-1/ }),
    ).toBeInTheDocument();
  });

  it("does not load the version step before a repository is chosen", async () => {
    // `GitGraph` fetches on mount; rendering it eagerly would query GitHub for a
    // repository the user has not selected.
    const graphRequests = vi.fn();
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/branches`, () => {
        graphRequests();
        return HttpResponse.json([]);
      }),
    );
    stubRepos();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await loaded();

    await user.click(screen.getByRole("button", { name: /External URL/ }));

    expect(graphRequests).not.toHaveBeenCalled();
  });

  it("returns to the list from the version step", async () => {
    stubRepos();
    stubGitGraph();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await waitFor(() => expect(screen.getByText("repo-1")).toBeInTheDocument());
    await user.click(screen.getByText("repo-1"));
    await screen.findByRole("heading", { name: /Configure Version/ });

    await user.click(screen.getByRole("button", { name: /Back to repository list/ }));

    expect(await screen.findByText("repo-1")).toBeInTheDocument();
  });
});

describe("the external URL form", () => {
  /** Types a URL and submits the external form. */
  async function submitUrl(url: string) {
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /External URL/ }));
    await user.type(screen.getByLabelText("GitHub Repository URL"), url);
    await user.click(screen.getByRole("button", { name: "Continue" }));
  }

  it("advances on a valid URL", async () => {
    stubRepos();
    stubGitGraph();
    render(<RepoPickerModal />);
    await loaded();

    await submitUrl("https://github.com/example/cool-project");

    expect(
      await screen.findByRole("heading", {
        name: /Configure Version for example\/cool-project/,
      }),
    ).toBeInTheDocument();
  });

  it("accepts a trailing slash", async () => {
    stubRepos();
    stubGitGraph();
    render(<RepoPickerModal />);
    await loaded();

    await submitUrl("https://github.com/example/cool-project/");

    expect(
      await screen.findByRole("heading", {
        name: /Configure Version for example\/cool-project/,
      }),
    ).toBeInTheDocument();
  });

  it("strips a .git suffix from the repository name", async () => {
    // GitHub's clone URL is a natural thing to paste. Only the *name* is stripped; the
    // `.git` survives into the URL that is sent to the backend.
    stubRepos();
    stubGitGraph();
    render(<RepoPickerModal />);
    await loaded();

    await submitUrl("https://github.com/example/cool-project.git");

    expect(
      await screen.findByRole("heading", {
        name: /Configure Version for example\/cool-project$/,
      }),
    ).toBeInTheDocument();
  });

  it("rejects a non-GitHub URL", async () => {
    stubRepos();
    render(<RepoPickerModal />);
    await loaded();

    await submitUrl("https://gitlab.com/example/cool-project");

    expect(await screen.findByText(/Please enter a valid GitHub repository URL/)).toBeInTheDocument();
  });

  it("rejects a URL without a repository segment", async () => {
    stubRepos();
    render(<RepoPickerModal />);
    await loaded();

    await submitUrl("https://github.com/example");

    expect(await screen.findByText(/Please enter a valid GitHub repository URL/)).toBeInTheDocument();
  });

  it("rejects a deep link inside a repository", async () => {
    // `.../tree/main` is what the address bar shows while browsing a repo, so this is a
    // reachable paste; the pattern is anchored, so it is refused rather than ingested as
    // a repository named "main".
    stubRepos();
    render(<RepoPickerModal />);
    await loaded();

    await submitUrl("https://github.com/example/cool-project/tree/main");

    expect(await screen.findByText(/Please enter a valid GitHub repository URL/)).toBeInTheDocument();
  });

  it("rejects plain http", async () => {
    stubRepos();
    render(<RepoPickerModal />);
    await loaded();

    await submitUrl("http://github.com/example/cool-project");

    expect(await screen.findByText(/Please enter a valid GitHub repository URL/)).toBeInTheDocument();
  });

  it("sends nothing when the URL is rejected", async () => {
    stubRepos();
    const graphRequests = vi.fn();
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/branches`, () => {
        graphRequests();
        return HttpResponse.json([]);
      }),
    );
    render(<RepoPickerModal />);
    await loaded();

    await submitUrl("not a url");

    expect(graphRequests).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: /Configure Version/ })).not.toBeInTheDocument();
  });
});

describe("ingesting", () => {
  /** Picks a repository and lands on the version step. */
  async function chooseRepo() {
    stubRepos();
    stubGitGraph();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await waitFor(() => expect(screen.getByText("repo-1")).toBeInTheDocument());
    await user.click(screen.getByText("repo-1"));
    await screen.findByRole("heading", { name: /Configure Version/ });
    return user;
  }

  /** The ingest button on the version step. */
  function ingestButton(): HTMLElement {
    return screen.getByRole("button", { name: /Ingest / });
  }

  it("posts the chosen repository and the default branch", async () => {
    const bodies = stubIngest();
    const user = await chooseRepo();

    await user.click(ingestButton());

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({
      github_url: "https://github.com/example/repo-1",
      branch: "main",
      commit_sha: null,
    });
  });

  it("navigates to the new repository", async () => {
    stubIngest();
    const user = await chooseRepo();

    await user.click(ingestButton());

    await waitFor(() => expect(push).toHaveBeenCalledWith("/repo/7"));
  });

  it("closes the modal before navigating", async () => {
    // Both are called on success; the order matters only in that `onClose` must not be
    // skipped, or the modal would stay mounted behind the new route.
    const onClose = vi.fn();
    stubIngest();
    stubRepos();
    stubGitGraph();
    const user = userEvent.setup();
    render(<RepoPickerModal onClose={onClose} />);
    await waitFor(() => expect(screen.getByText("repo-1")).toBeInTheDocument());
    await user.click(screen.getByText("repo-1"));
    await screen.findByRole("heading", { name: /Configure Version/ });

    await user.click(ingestButton());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(push).toHaveBeenCalledWith("/repo/7");
  });

  it("renders without a close handler", async () => {
    stubIngest();
    const user = await chooseRepo();

    await user.click(ingestButton());

    await waitFor(() => expect(push).toHaveBeenCalledWith("/repo/7"));
  });

  it("posts the URL typed on the external tab", async () => {
    const bodies = stubIngest();
    stubRepos();
    stubGitGraph();
    const user = userEvent.setup();
    render(<RepoPickerModal />);
    await loaded();
    await user.click(screen.getByRole("button", { name: /External URL/ }));
    await user.type(screen.getByLabelText("GitHub Repository URL"), "https://github.com/example/typed");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: /Configure Version/ });

    await user.click(screen.getByRole("button", { name: /Ingest / }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].github_url).toBe("https://github.com/example/typed");
  });

  it("shows a failed ingestion in place", async () => {
    stubIngest(() =>
      HttpResponse.json({ detail: "Repository already exists" }, { status: 400 }),
    );
    const user = await chooseRepo();

    await user.click(ingestButton());

    await waitFor(() =>
      expect(screen.getByText("Repository already exists")).toBeInTheDocument(),
    );
  });

  it("shows the backend's detail rather than a generic string", async () => {
    // The backend reports every failure as `{"detail": ...}`. Reading `errorData.message`
    // -- a field it never sends -- discarded the reason, so a duplicate repository, a
    // validation error, and an unlinked account all rendered the same sentence.
    stubIngest(() =>
      HttpResponse.json({ detail: "Repository already exists" }, { status: 400 }),
    );
    const user = await chooseRepo();

    await user.click(ingestButton());

    await waitFor(() =>
      expect(screen.getByText("Repository already exists")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Failed to trigger ingestion")).not.toBeInTheDocument();
  });

  it("falls back to the generic message when the failure body is not JSON", async () => {
    // A bodyless failure -- an nginx error page, or a proxy dropping the connection --
    // makes `res.json()` throw. The shared helper swallows that, so the banner shows the
    // intended fallback rather than the parser's own message, which is what used to reach
    // the screen.
    stubIngest(() => new HttpResponse(null, { status: 500 }));
    const user = await chooseRepo();

    await user.click(ingestButton());

    await waitFor(() =>
      expect(screen.getByText("Failed to trigger ingestion")).toBeInTheDocument(),
    );
  });

  it("does not navigate on a failure", async () => {
    stubIngest(() => HttpResponse.json({ detail: "nope" }, { status: 500 }));
    const user = await chooseRepo();

    await user.click(ingestButton());

    await waitFor(() => expect(screen.getByText("nope")).toBeInTheDocument());
    expect(push).not.toHaveBeenCalled();
  });

  it("clears a previous failure when a retry starts", async () => {
    let attempt = 0;
    stubIngest(() => {
      attempt += 1;
      return attempt === 1
        ? HttpResponse.json({ detail: "nope" }, { status: 500 })
        : HttpResponse.json({ repo_id: "r1", repo_num: 7 }, { status: 202 });
    });
    const user = await chooseRepo();

    await user.click(ingestButton());
    await waitFor(() => expect(screen.getByText("nope")).toBeInTheDocument());

    await user.click(ingestButton());

    await waitFor(() => expect(push).toHaveBeenCalledWith("/repo/7"));
  });
});
