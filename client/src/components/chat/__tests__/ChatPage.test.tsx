import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChatPage, { type ChatPageProps } from "@/components/chat/ChatPage";
import { RepoGraphProvider } from "@/components/RepoGraphContext";
import type Graph from "@/types/graph";
import { sseBody, ev } from "../../../../tests/unit/lib/agent/factories";
import { installFetch, streamResponse } from "./streamHelpers";

// Counts how often the WebGL module is actually loaded.
const graphLoads = vi.hoisted(() => ({ count: 0 }));

vi.mock("@/components/chat/LiveGraph", () => ({
  default: () => <div data-testid="live-graph-stub" />,
}));

// `next/dynamic` resolves the loader on first render, as the real one does.
vi.mock("next/dynamic", async () => {
  const React = await import("react");
  return {
    default: (loader: () => Promise<{ default: React.ComponentType<unknown> }>) =>
      function Dynamic(props: Record<string, unknown>) {
        const [Component, setComponent] = React.useState<React.ComponentType<unknown> | null>(null);
        React.useEffect(() => {
          graphLoads.count += 1;
          void loader().then((mod) => setComponent(() => mod.default));
        }, []);
        return Component ? React.createElement(Component as React.ComponentType<Record<string, unknown>>, props) : null;
      },
  };
});

const GRAPH: Graph = {
  nodes: [
    {
      id: "1",
      label: "auth.py",
      path: "app/auth.py",
      group: "app",
      kind: "file",
      loc: 40,
      criticality: "safe",
      criticality_score: 25,
      language: "python",
      fan_in: 0,
      fan_out: 0,
    },
  ],
  links: [],
  metadata: { total_nodes: 1, total_edges: 0, clusters: 1 },
};

const PROPS: ChatPageProps = {
  repoId: "repo-1",
  repoName: "acme",
  url: "https://github.com/acme/app",
  commitSha: "abc123",
  branch: "main",
  suggestions: ["Q one?", "Q two?", "Q three?"],
  caps: { hasOwnKey: true, supportsTools: true },
  freeChatRemaining: null,
};

function setViewport(wide: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: wide && query.includes("min-width"),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (globalThis as unknown as { matchMedia: typeof window.matchMedia }).matchMedia,
  });
}

function renderPage(props: Partial<ChatPageProps> = {}) {
  return render(
    <RepoGraphProvider graph={GRAPH}>
      <ChatPage {...PROPS} {...props} />
    </RepoGraphProvider>,
  );
}

async function ask(text: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByRole("textbox", { name: /Ask about the codebase/ }), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
}

beforeEach(() => {
  graphLoads.count = 0;
  setViewport(true);
  window.localStorage.clear();
  Element.prototype.scrollTo = vi.fn() as unknown as typeof Element.prototype.scrollTo;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatPage empty state", () => {
  it("greets, offers three suggestions and sends one when clicked", async () => {
    const stream = streamResponse();
    const { requests } = installFetch({ onStream: () => stream.response });
    renderPage();

    expect(await screen.findByText(/What would you like to know about acme/)).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Suggested questions" });
    expect(list.querySelectorAll("button")).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: "Q two?" }));
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].body.question).toBe("Q two?");
    expect(within(screen.getByTestId("turn")).getByText("Q two?")).toBeInTheDocument();
    stream.close();
  });

  it("sends on Enter and keeps Shift+Enter for a new line", async () => {
    const stream = streamResponse();
    const { requests } = installFetch({ onStream: () => stream.response });
    renderPage();
    const box = await screen.findByRole("textbox", { name: /Ask about the codebase/ });

    fireEvent.change(box, { target: { value: "line one" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(requests).toHaveLength(0);

    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].body).toMatchObject({ question: "line one", history: [] });
    stream.close();
  });
});

describe("ChatPage request", () => {
  it("posts the resolved preset with credentials and no overrides by default", async () => {
    const stream = streamResponse();
    const { requests } = installFetch({ onStream: () => stream.response });
    renderPage();
    await ask("How does auth work?");
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].init.credentials).toBe("include");
    expect(requests[0].body.preset).toBe("deep_agent");
    expect(requests[0].body).not.toHaveProperty("overrides");
    stream.close();
  });

  it("starts on the account's default, not on Auto, and sends Auto as `auto` when chosen", async () => {
    const stream = streamResponse();
    const { requests } = installFetch({ onStream: () => stream.response });
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByTestId("preset-label")).toHaveTextContent("Deep agent");

    await user.click(screen.getByRole("button", { name: /Deep agent/ }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Auto/ }));
    expect(screen.getByTestId("preset-label")).toHaveTextContent("Auto");
    await ask("Where is login handled?");

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].body.preset).toBe("auto");
    expect(requests[0].body).not.toHaveProperty("overrides");
    stream.close();
  });

  it("lands on the account default when an old `auto` was remembered", async () => {
    window.localStorage.setItem(
      "illume.chat.preset.repo-1",
      JSON.stringify({ preset: "auto", settings: null }),
    );
    installFetch({});
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("preset-label")).toHaveTextContent("Deep agent"),
    );
  });

  it("keeps a remembered Auto once it is stored in the current format", async () => {
    window.localStorage.setItem(
      "illume.chat.preset.repo-1",
      JSON.stringify({ preset: "auto", settings: null, version: 2 }),
    );
    installFetch({});
    renderPage();
    await waitFor(() => expect(screen.getByTestId("preset-label")).toHaveTextContent("Auto"));
  });

  it("remembers a preset choice per repository", async () => {
    installFetch({});
    const user = userEvent.setup();
    const first = renderPage();
    await user.click(await screen.findByRole("button", { name: /Deep agent/ }));
    await user.click(screen.getByRole("menuitemradio", { name: /Hybrid/ }));
    expect(screen.getByTestId("preset-label")).toHaveTextContent("Hybrid");
    expect(JSON.parse(window.localStorage.getItem("illume.chat.preset.repo-1")!)).toMatchObject({
      preset: "hybrid",
    });
    first.unmount();

    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("preset-label")).toHaveTextContent("Hybrid"),
    );
  });

  it("shows the server's reason when overrides are refused", async () => {
    installFetch({
      onStream: () =>
        Response.json(
          { detail: "channel 'grep' cannot be added to preset 'classic' on the free tier" },
          { status: 422 },
        ),
    });
    renderPage();
    await ask("hi");
    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot be added/);
  });

  it("links to settings when the allowance is spent (402)", async () => {
    installFetch({
      onStream: () => Response.json({ detail: "You've used all of your free chat questions." }, { status: 402 }),
    });
    renderPage();
    await ask("hi");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/used all of your free chat/);
    expect(alert.querySelector("a")).toHaveAttribute("href", "/settings");
  });
});

describe("ChatPage live run", () => {
  it("streams activity into the block and the answer into the turn", async () => {
    const stream = streamResponse();
    installFetch({ onStream: () => stream.response });
    renderPage();
    await ask("Where is login?");

    await act(async () => {
      stream.push(
        sseBody([
          ev("tool_call", { call_id: "c1", tool: "grep_code", arguments: '{"pattern":"login"}' }),
        ]),
      );
    });
    expect(await screen.findByText("login")).toBeInTheDocument();
    await act(async () => {
      stream.push(sseBody([ev("answer_delta", { text: "Login is in " })]));
    });
    expect(await screen.findByTestId("answer")).toHaveTextContent("Login is in");

    await act(async () => {
      stream.push(
        sseBody([
          ev("done", {
            run_id: "run-1",
            answer: "Login is in [F:app/auth.py:1-9].",
            citations: [{ key: "F:app/auth.py:1-9", source_type: "symbol", file_path: "app/auth.py" }],
            usage: { elapsed_seconds: 3, input_tokens: 12_400, output_tokens: 850 },
          }),
        ]),
      );
      stream.close();
    });
    expect(await screen.findByRole("button", { name: "Source F:app/auth.py:1-9" })).toBeInTheDocument();
    const stats = screen.getByTestId("run-stats");
    expect(stats).toHaveTextContent("3 s");
    expect(stats).toHaveTextContent("12k in · 850 out tokens");
    expect(screen.queryByRole("button", { name: /View run/ })).not.toBeInTheDocument();
  });

  it("aborts the request when Stop is pressed and settles as stopped", async () => {
    const stream = streamResponse();
    let signal: AbortSignal | null | undefined;
    installFetch({
      onStream: ({ init }) => {
        signal = init.signal;
        init.signal?.addEventListener("abort", () =>
          stream.fail(new DOMException("aborted", "AbortError")),
        );
        return stream.response;
      },
    });
    renderPage();
    await ask("slow question");
    await act(async () => {
      stream.push(sseBody([ev("tool_call", { call_id: "c1", tool: "search_code", arguments: '{"query":"slow"}' })]));
    });

    fireEvent.click(await screen.findByRole("button", { name: "Stop" }));

    expect(signal?.aborted).toBe(true);
    expect(await screen.findByText(/Stopped before the answer finished/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("shows 'connection lost' and keeps the partial answer when the stream drops", async () => {
    const stream = streamResponse();
    installFetch({ onStream: () => stream.response });
    renderPage();
    await ask("will drop");
    await act(async () => {
      stream.push(sseBody([ev("answer_delta", { text: "Partial" })]));
      stream.close();
    });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Connection lost");
    expect(screen.queryByRole("button", { name: /Replay/ })).not.toBeInTheDocument();
    expect(screen.getByTestId("answer")).toHaveTextContent("Partial");
  });

  it("renders an error and keeps a degradation out of sight", async () => {
    const stream = streamResponse();
    installFetch({ onStream: () => stream.response });
    renderPage();
    await ask("will fail");
    await act(async () => {
      stream.push(
        sseBody([
          ev("degraded", { stage: "planner", reason: "the decider was unreachable" }),
          ev("error", { message: "The model provider is unreachable.", kind: "unreachable", status: 502 }),
        ]),
      );
      stream.close();
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("The model provider is unreachable.");
    expect(screen.queryByText(/the decider was unreachable/)).not.toBeInTheDocument();
  });

  it("ignores an unknown event type mid-stream", async () => {
    const stream = streamResponse();
    installFetch({ onStream: () => stream.response });
    renderPage();
    await ask("future events");
    await act(async () => {
      stream.push(
        sseBody([
          ev("hologram", { anything: 1 }),
          ev("answer_delta", { text: "Still works" }),
          ev("done", { run_id: "run-1", answer: "Still works" }),
        ]),
      );
      stream.close();
    });
    expect(await screen.findByText("Still works")).toBeInTheDocument();
  });
});

describe("ChatPage history", () => {
  const HISTORY = [
    {
      id: "msg-1",
      question: "What is func_0?",
      answer: "It is the first function.",
      sources: [],
    },
  ];

  it("loads history with what each answer's run spent", async () => {
    installFetch({
      history: HISTORY,
      runs: [
        {
          id: "run-9",
          chat_message_id: "msg-1",
          question: "What is func_0?",
          preset: "classic",
          status: "done",
          tool_calls: 4,
          latency_ms: 21_000,
          input_tokens: 3_000,
          output_tokens: 400,
          created_at: "",
        },
      ],
    });
    renderPage();
    expect(await screen.findByText("What is func_0?")).toBeInTheDocument();
    expect(screen.getByText("It is the first function.")).toBeInTheDocument();
    const stats = await screen.findByTestId("run-stats");
    expect(stats).toHaveTextContent("4 tool calls");
    expect(stats).toHaveTextContent("21 s");
    expect(stats).toHaveTextContent("3k in · 400 out tokens");
    expect(screen.queryByRole("button", { name: /View run/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Suggested questions" })).not.toBeInTheDocument();
  });

  it("shows no figures for a stored answer with no recorded run", async () => {
    installFetch({ history: HISTORY });
    renderPage();
    await screen.findByText("What is func_0?");
    expect(screen.queryByTestId("run-stats")).not.toBeInTheDocument();
  });

  it("clears history from the options menu", async () => {
    const { fetchMock } = installFetch({ history: HISTORY });
    renderPage();
    await screen.findByText("What is func_0?");
    fireEvent.click(screen.getByRole("button", { name: "Chat options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Clear chat history/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/repository\/repo-1\/chat$/),
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    expect(await screen.findByText(/What would you like to know/)).toBeInTheDocument();
  });
});

describe("ChatPage graph", () => {
  it("loads the graph on wide screens", async () => {
    installFetch({});
    renderPage();
    expect(await screen.findByTestId("live-graph-stub")).toBeInTheDocument();
    expect(graphLoads.count).toBe(1);
  });

  it("never loads the graph module below the md breakpoint", async () => {
    setViewport(false);
    installFetch({});
    renderPage();
    await screen.findByText(/What would you like to know about acme/);
    // Give any lazy import the chance it would need to land.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.queryByTestId("live-graph-stub")).not.toBeInTheDocument();
    expect(graphLoads.count).toBe(0);
  });
});

describe("ChatPage stale answers", () => {
  const STALE_HISTORY = [
    {
      id: "msg-1",
      question: "How is a password checked?",
      answer: "In app/auth.py.",
      sources: [],
      stale_at: "2026-02-01T00:00:00Z",
      stale_paths: ["app/auth.py"],
      stale_commit_sha: "def456",
      answered_commit_sha: "abc123",
    },
    {
      id: "msg-2",
      question: "What is the license?",
      answer: "MIT.",
      sources: [],
      stale_at: null,
      stale_paths: null,
    },
  ];

  it("flags only the answers whose cited files changed", async () => {
    installFetch({ history: STALE_HISTORY });
    renderPage();
    await screen.findByText("MIT.");
    expect(screen.getAllByTestId("stale-notice")).toHaveLength(1);
    const turns = screen.getAllByTestId("turn");
    expect(within(turns[0]).getByText("May be out of date")).toBeInTheDocument();
    expect(within(turns[1]).queryByText("May be out of date")).not.toBeInTheDocument();
  });

  it("re-asks the same question as a new turn with the selected preset", async () => {
    const stream = streamResponse();
    const { requests } = installFetch({
      history: STALE_HISTORY,
      onStream: () => stream.response,
    });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("MIT.");
    await user.click(screen.getByRole("button", { name: /Deep agent/ }));
    await user.click(screen.getByRole("menuitemradio", { name: /Hybrid/ }));

    await user.click(screen.getByRole("button", { name: "Re-ask" }));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].body.question).toBe("How is a password checked?");
    expect(requests[0].body.preset).toBe("hybrid");
    expect(screen.getAllByTestId("turn")).toHaveLength(3);
    stream.close();
  });
});

describe("ChatPage free tier", () => {
  it("offers Classic by default and disables Auto", async () => {
    installFetch({});
    renderPage({ caps: { hasOwnKey: false, supportsTools: null }, freeChatRemaining: 5 });
    const user = userEvent.setup();
    const label = await screen.findByTestId("preset-label");
    expect(label).toHaveTextContent("Classic");
    await user.click(label);
    expect(screen.getByRole("menuitemradio", { name: /^Auto/ })).toBeDisabled();
  });

  it("disables the composer once the allowance is spent", async () => {
    installFetch({});
    renderPage({ caps: { hasOwnKey: false, supportsTools: null }, freeChatRemaining: 0 });
    expect(await screen.findByRole("textbox", { name: /Ask about the codebase/ })).toBeDisabled();
    expect(screen.getByRole("link", { name: /Add your own API key/ })).toHaveAttribute("href", "/settings");
  });
});
