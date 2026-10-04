import Contact from "@/app/contact/page";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getMyData = vi.hoisted(() => vi.fn());

// Hoisted above the import of the page, so the page's own import of `@/api/auth`
// resolves to this mock.
vi.mock("@/api/auth", () => ({ default: getMyData }));

// The signed-in branch renders `<Navbar>`, which calls `useRouter()` from
// `next/navigation`. Without an App Router context the hook throws
// `invariant expected app router to be mounted` -- matching the pattern used by
// the component suite so the page can render in isolation.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
  }),
}));

/**
 * Renders the page, which is an async server component.
 *
 * The page is imported at module scope rather than inside the test: a dynamic import in
 * the test body puts the whole transform cost of the page and its dependencies inside the
 * 5s test budget, which this file was observed exceeding under a full parallel run.
 */
async function renderPage() {
  render(await Contact());
}

const USER = {
  id: "8f14e45f-ceea-467a-9e5b-1a2b3c4d5e6f",
  name: "Grace Hopper",
  email: "grace@example.com",
  avatar_url: null,
  github_id: null,
  ai_provider: null,
  ai_model: null,
  has_ai_key: false,
  free_ingestions_used: 0,
  free_chat_messages_used: 0,
  free_ingestions_limit: 3,
  free_chat_messages_limit: 5,
};

beforeEach(() => {
  getMyData.mockReset();
});

describe("anonymous visitor", () => {
  it("renders the form when the request is unauthenticated", async () => {
    // `GetMyData` throws for an anonymous caller. A contact page that needed a session
    // would be unreachable by exactly the people most likely to use it.
    getMyData.mockRejectedValue(new Error("Failed to fetch my data"));

    await renderPage();

    expect(
      screen.getByRole("heading", { name: /get in touch/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^message/i)).toBeInTheDocument();
  });

  it("renders the form when the API is unreachable", async () => {
    // The same catch has to cover a network failure: a page that could not load while the
    // API was down would be useless for reporting that the API was down.
    getMyData.mockRejectedValue(new TypeError("fetch failed"));

    await renderPage();

    expect(
      screen.getByRole("heading", { name: /get in touch/i }),
    ).toBeInTheDocument();
  });

  it("leaves the identity fields empty", async () => {
    getMyData.mockRejectedValue(new Error("unauthenticated"));

    await renderPage();

    expect(screen.getByLabelText(/^name/i)).toHaveValue("");
    expect(screen.getByLabelText(/^email/i)).toHaveValue("");
  });

  it("does not surface the failure to the visitor", async () => {
    getMyData.mockRejectedValue(new Error("Failed to fetch my data"));

    await renderPage();

    expect(screen.queryByText(/failed to fetch/i)).not.toBeInTheDocument();
  });
});

describe("signed-in visitor", () => {
  it("prefills the name and email from the session", async () => {
    getMyData.mockResolvedValue(USER);

    await renderPage();

    expect(screen.getByLabelText(/^name/i)).toHaveValue("Grace Hopper");
    expect(screen.getByLabelText(/^email/i)).toHaveValue("grace@example.com");
  });

  it("still renders the category and message empty", async () => {
    // Identity is a convenience; the two fields that carry the submission start blank.
    getMyData.mockResolvedValue(USER);

    await renderPage();

    expect(screen.getByLabelText(/what is this about/i)).toHaveValue("");
    expect(screen.getByLabelText(/^message/i)).toHaveValue("");
  });
});

describe("page shell", () => {
  it("links back to the landing page", async () => {
    getMyData.mockRejectedValue(new Error("unauthenticated"));

    await renderPage();

    expect(screen.getByRole("link", { name: /illume/i })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("renders the footer", async () => {
    getMyData.mockRejectedValue(new Error("unauthenticated"));

    await renderPage();

    expect(screen.getByRole("link", { name: "GitHub" })).toBeInTheDocument();
  });
});
