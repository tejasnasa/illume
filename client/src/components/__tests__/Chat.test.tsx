import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../../tests/msw/handlers";
import { server } from "../../../tests/msw/server";
import Chat from "@/components/Chat";

const REPO_ID = "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30";
const URL = "https://github.com/example/cool-project";

const HISTORY_URL = `${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat/history`;
const ASK_URL = `${BACKEND_URL}/api/v1/repository/${REPO_ID}/chat`;

const PERSISTED = [
  {
    id: "m1",
    repository_id: REPO_ID,
    user_id: "u1",
    question: "What does this do?",
    answer: "It reads files.",
    sources: [],
    created_at: "2026-01-01T00:00:00Z",
  },
];

/**
 * Registers the endpoints the panel uses.
 *
 * `askStatus` is the status the POST handler returns; `askBody` overrides
 * what the failure-endpoint serves back. Tests use both to pin the 402
 * branch -- `askStatus=402` together with `askBody.detail` is what the hook
 * surfaces in the quota bubble, so the branch is left as a two-knob switch.
 */
function stub({
  history = PERSISTED,
  askStatus = 200,
  askBody,
  freeChatRemaining = null,
}: {
  history?: typeof PERSISTED;
  askStatus?: number;
  askBody?: Record<string, unknown>;
  freeChatRemaining?: number | null;
} = {}) {
  server.use(
    http.get(HISTORY_URL, () => HttpResponse.json(history)),
    http.post(ASK_URL, () =>
      askStatus === 200
        ? HttpResponse.json({
            id: "m2",
            answer: "A fresh answer.",
            sources: [],
          })
        : HttpResponse.json(askBody ?? { detail: "boom" }, {
            status: askStatus,
          }),
    ),
  );
  return freeChatRemaining;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("layout", () => {
  it("renders the heading", async () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    expect(
      screen.getByRole("heading", { name: /Chat with Codebase/i }),
    ).toBeInTheDocument();
  });

  it("renders the composer", async () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    expect(
      screen.getByPlaceholderText(/Ask about the codebase/),
    ).toBeInTheDocument();
  });
});

describe("empty state", () => {
  it("prompts the user when there is no history", async () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    await waitFor(() =>
      expect(
        screen.getByText(/Ask questions about the architecture/),
      ).toBeInTheDocument(),
    );
  });

  it("hides the empty state once a turn exists", async () => {
    stub();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    await waitFor(() =>
      expect(screen.getByText("What does this do?")).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/Ask questions about the architecture/),
    ).not.toBeInTheDocument();
  });

  it("hides the clear button while there is nothing to clear", async () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    await waitFor(() =>
      expect(screen.queryByTitle("Clear Chat History")).not.toBeInTheDocument(),
    );
  });
});

describe("history", () => {
  it("renders persisted turns", async () => {
    stub();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    await waitFor(() =>
      expect(screen.getByText("What does this do?")).toBeInTheDocument(),
    );
    expect(screen.getByText("It reads files.")).toBeInTheDocument();
  });

  it("renders turns in the order the server sent them", async () => {
    stub({
      history: [
        { ...PERSISTED[0], id: "a", question: "first" },
        { ...PERSISTED[0], id: "b", question: "second" },
      ],
    });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    await waitFor(() => expect(screen.getByText("first")).toBeInTheDocument());
    const rendered = screen
      .getAllByText(/^(first|second)$/)
      .map((el) => el.textContent);
    expect(rendered).toEqual(["first", "second"]);
  });

  it("shows the clear button once a turn exists", async () => {
    stub();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    await waitFor(() =>
      expect(screen.getByTitle("Clear Chat History")).toBeInTheDocument(),
    );
  });
});

describe("sending", () => {
  it("sends on the send button", async () => {
    stub({ history: [] });
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/Ask about/)).toBeInTheDocument(),
    );

    await user.type(screen.getByPlaceholderText(/Ask about/), "A question");
    await user.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() =>
      expect(screen.getByText("A fresh answer.")).toBeInTheDocument(),
    );
  });

  it("sends on Enter", async () => {
    stub({ history: [] });
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/Ask about/)).toBeInTheDocument(),
    );

    await user.type(
      screen.getByPlaceholderText(/Ask about/),
      "A question{Enter}",
    );

    await waitFor(() =>
      expect(screen.getByText("A fresh answer.")).toBeInTheDocument(),
    );
  });

  it("does not send on Shift+Enter", async () => {
    // Shift+Enter is how a multi-line question is typed; hijacking it would make the
    // textarea single-line in practice.
    const spy = vi.fn();
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json([])),
      http.post(ASK_URL, () => {
        spy();
        return HttpResponse.json({ id: "m2", answer: "x", sources: [] });
      }),
    );
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "line one{Shift>}{Enter}{/Shift}line two");

    expect(spy).not.toHaveBeenCalled();
    expect(box).toHaveValue("line one\nline two");
  });

  it("clears the composer after sending", async () => {
    stub({ history: [] });
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "A question");
    await user.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() => expect(box).toHaveValue(""));
  });

  it("trims the question before sending", async () => {
    let body: { question?: string } = {};
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json([])),
      http.post(ASK_URL, async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ id: "m2", answer: "x", sources: [] });
      }),
    );
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "  A question  ");
    await user.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() => expect(body.question).toBe("A question"));
  });

  it("disables the send button while the composer is empty", async () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Send$/ })).toBeDisabled(),
    );
  });

  it("disables the send button for whitespace only", async () => {
    // `!input.trim()` rather than `!input`, so spaces do not enable the button.
    stub({ history: [] });
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "   ");

    expect(screen.getByRole("button", { name: /^Send$/ })).toBeDisabled();
  });

  it("shows the thinking state while a request is in flight", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json([])),
      http.post(ASK_URL, async () => {
        await gate;
        return HttpResponse.json({ id: "m2", answer: "x", sources: [] });
      }),
    );
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "A question");
    await user.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Thinking/ }),
      ).toBeInTheDocument(),
    );

    release();
  });

  it("shows the optimistic bubble before the answer arrives", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json([])),
      http.post(ASK_URL, async () => {
        await gate;
        return HttpResponse.json({ id: "m2", answer: "x", sources: [] });
      }),
    );
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "A question");
    await user.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() =>
      expect(screen.getByText("A question")).toBeInTheDocument(),
    );
    expect(screen.getByText("Analyzing codebase...")).toBeInTheDocument();

    release();
  });

  it("renders a failed turn in place", async () => {
    stub({ history: [], askStatus: 500 });
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "A question");
    await user.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() =>
      expect(
        screen.getByText("Failed to get response. Try again."),
      ).toBeInTheDocument(),
    );
  });
});

describe("free-tier quota", () => {
  it("does not display a counter when freeChatRemaining is null", () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);

    expect(screen.queryByText(/free .* left/i)).not.toBeInTheDocument();
  });

  it("displays the remaining count for a keyless user", () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={5} />);

    expect(screen.getByText(/5 free questions left/i)).toBeInTheDocument();
  });

  it("singularises the label when remaining is one", () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={1} />);

    expect(screen.getByText(/1 free question left/i)).toBeInTheDocument();
  });

  it("disables the composer when the allowance is exhausted", () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={0} />);

    expect(
      screen.getByPlaceholderText(/Free chat allowance used up/i),
    ).toBeDisabled();
  });

  it("disables the send button when the allowance is exhausted", async () => {
    stub({ history: [] });
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={0} />);

    // Typing into a disabled textarea should be a no-op; assert that the
    // button never enables rather than reaching for the slower waitFor loop.
    const box = screen.getByPlaceholderText(/Free chat allowance used up/i);
    await user.type(box, "Should not matter");
    expect(screen.getByRole("button", { name: /^Send$/ })).toBeDisabled();
  });

  it("renders the quota exhausted note linking to /settings", () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={0} />);

    expect(
      screen.getByText(/You've used up the free chat questions/i),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Add your own API key/i });
    expect(link).toHaveAttribute("href", "/settings");
  });

  it("does not show the quota exhausted note when remaining is positive", () => {
    stub({ history: [] });
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={3} />);

    expect(
      screen.queryByText(/You've used up the free chat questions/i),
    ).not.toBeInTheDocument();
  });

  it("renders the 402 detail alongside an 'Add your own API key' link", async () => {
    stub({
      history: [],
      askStatus: 402,
      askBody: {
        detail:
          "Free chat allowance used up. Add your own API key to keep chatting.",
      },
    });
    const user = userEvent.setup();
    // `null` so the composer is enabled -- the hook-level branch is the one
    // under test here, rather than the disabled composer.
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about the codebase/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "A question");
    await user.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() =>
      expect(
        screen.getByText(/Free chat allowance used up/i),
      ).toBeInTheDocument(),
    );
    const link = screen.getByRole("link", { name: /Add your own API key/i });
    expect(link).toHaveAttribute("href", "/settings");
  });

  it("falls back to a generic message when the 402 body has no detail", async () => {
    stub({
      history: [],
      askStatus: 402,
      askBody: {},
    });
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about the codebase/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "A question");
    await user.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() =>
      expect(
        screen.getByText(/Free chat allowance used up/i),
      ).toBeInTheDocument(),
    );
  });

  it("does not show the /settings link for a non-quota failure", async () => {
    stub({ history: [], askStatus: 500 });
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    const box = screen.getByPlaceholderText(/Ask about the codebase/);
    await waitFor(() => expect(box).toBeInTheDocument());

    await user.type(box, "A question");
    await user.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() =>
      expect(
        screen.getByText("Failed to get response. Try again."),
      ).toBeInTheDocument(),
    );
    // The generic failure uses the generic copy; quota is the only path that
    // surfaces the /settings link in the bubble.
    expect(
      screen.queryByRole("link", { name: /Add your own API key/i }),
    ).not.toBeInTheDocument();
  });
});

describe("clearing", () => {
  it("empties the panel", async () => {
    stub();
    server.use(
      http.delete(ASK_URL, () => new HttpResponse(null, { status: 204 })),
    );
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    await waitFor(() =>
      expect(screen.getByText("What does this do?")).toBeInTheDocument(),
    );

    await user.click(screen.getByTitle("Clear Chat History"));

    await waitFor(() =>
      expect(
        screen.getByText(/Ask questions about the architecture/),
      ).toBeInTheDocument(),
    );
  });

  it("restores the empty state and hides the clear button", async () => {
    stub();
    server.use(
      http.delete(ASK_URL, () => new HttpResponse(null, { status: 204 })),
    );
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    await waitFor(() =>
      expect(screen.getByTitle("Clear Chat History")).toBeInTheDocument(),
    );

    await user.click(screen.getByTitle("Clear Chat History"));

    await waitFor(() =>
      expect(screen.queryByTitle("Clear Chat History")).not.toBeInTheDocument(),
    );
  });
});

describe("deleting", () => {
  it("removes a single turn", async () => {
    stub();
    server.use(
      http.delete(
        `${ASK_URL}/:id`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const user = userEvent.setup();
    render(<Chat repoId={REPO_ID} url={URL} freeChatRemaining={null} />);
    await waitFor(() =>
      expect(screen.getByText("What does this do?")).toBeInTheDocument(),
    );

    await user.click(screen.getByTitle("Delete message"));

    await waitFor(() =>
      expect(screen.queryByText("What does this do?")).not.toBeInTheDocument(),
    );
  });
});
