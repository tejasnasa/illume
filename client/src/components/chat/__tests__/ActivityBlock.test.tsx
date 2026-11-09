import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ActivityBlock from "@/components/chat/ActivityBlock";
import {
  initialRunState,
  runReducer,
  type RunAction,
  type RunState,
} from "@/lib/agent/reducer";
import type { StreamEvent } from "@/lib/agent/types";
import { ev } from "../../../../tests/unit/lib/agent/factories";

function stateOf(...events: StreamEvent[]): RunState {
  const actions: RunAction[] = [
    { type: "start", at: Date.now() },
    ...events.map((event): RunAction => ({ type: "event", event })),
  ];
  return actions.reduce(runReducer, initialRunState);
}

describe("ActivityBlock", () => {
  it("shows the steps inline with a live status line under them", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("tool_call", {
            call_id: "c1",
            tool: "read_file",
            arguments: '{"path":"app/auth.py"}',
          }),
        )}
      />,
    );
    const status = screen.getByTestId("run-status");
    expect(status).toHaveTextContent(/Reading app\/auth\.py/);
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(document.querySelector('[data-row="tool"]')).toBeInTheDocument();
    // No header to fold the steps away behind.
    expect(screen.queryByRole("button", { expanded: true })).not.toBeInTheDocument();
  });

  it("drops the status line once the run is done", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("tool_call", { call_id: "c1", tool: "grep_code", arguments: '{"pattern":"zzz"}' }),
          ev("tool_result", { call_id: "c1", tool: "grep_code", status: "ok" }),
          ev("done", { run_id: "run-1", answer: "Answer" }),
        )}
      />,
    );
    expect(screen.getByText("zzz")).toBeInTheDocument();
    expect(screen.queryByTestId("run-status")).not.toBeInTheDocument();
  });

  it("renders a grep row with its pattern in monospace and the matched files", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("tool_call", {
            call_id: "c1",
            tool: "grep_code",
            arguments: '{"pattern":"def login"}',
          }),
          ev("tool_result", {
            call_id: "c1",
            tool: "grep_code",
            status: "ok",
            result_count: 2,
            latency_ms: 40,
          }),
          ev("nodes", { call_id: "c1", paths: ["app/auth.py", "app/users.py"] }),
        )}
      />,
    );
    const pattern = screen.getByText("def login");
    expect(pattern.tagName).toBe("CODE");
    expect(screen.getByText("2 found")).toBeInTheDocument();
    expect(screen.getByText("40 ms")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Grep/ }));
    const files = screen.getByRole("list", { name: "Matched files" });
    expect(within(files).getByText("app/auth.py")).toBeInTheDocument();
    expect(within(files).getByText("app/users.py")).toBeInTheDocument();
  });

  it("renders a read row with the path and line range", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("tool_call", {
            call_id: "c1",
            tool: "read_file",
            arguments: '{"path":"app/main.py","start_line":10,"end_line":40}',
          }),
          ev("tool_result", { call_id: "c1", tool: "read_file", status: "ok", summary: "30 lines" }),
          ev("nodes", { call_id: "c1", paths: ["app/main.py"] }),
        )}
      />,
    );
    expect(screen.getByText("app/main.py")).toBeInTheDocument();
    expect(screen.getByText("L10-40")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Read file/ }));
    expect(screen.getByText(/lines 10-40/)).toBeInTheDocument();
  });

  it("renders a search row with the query in quotes", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("tool_call", {
            call_id: "c1",
            tool: "search_code",
            arguments: '{"query":"token refresh"}',
          }),
        )}
      />,
    );
    expect(screen.getByText(/“token refresh”/)).toBeInTheDocument();
  });

  it("shows what a failed tool returned when it is opened", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("tool_call", { call_id: "c1", tool: "read_file", arguments: '{"path":"x"}' }),
          ev("tool_result", {
            call_id: "c1",
            tool: "read_file",
            status: "not_found",
            output: "No file at x.",
          }),
        )}
      />,
    );
    expect(screen.queryByText("No file at x.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Read file/ }));
    expect(screen.getByText("No file at x.")).toBeInTheDocument();
  });

  it("opens a tool to the sources it returned, each under its label", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("tool_call", { call_id: "c1", tool: "grep_code", arguments: '{"pattern":"login"}' }),
          ev("tool_result", {
            call_id: "c1",
            tool: "grep_code",
            status: "ok",
            output:
              'Found 1 match.\n<source key="F:app/auth.py:3-9" type="Code">def login():\n    pass\n</source>',
          }),
        )}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Grep/ }));
    const output = screen.getByTestId("tool-output");
    expect(within(output).getByText("Found 1 match.")).toBeInTheDocument();
    expect(within(output).getByText("auth.py:3-9")).toBeInTheDocument();
    expect(within(output).getByText(/def login\(\)/)).toBeInTheDocument();
    expect(output).not.toHaveTextContent("<source");
  });

  it("notes the split and nothing for a limit that was reached", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("plan", {
            subquestions: [
              { id: "w1", question: "How does login work?" },
              { id: "w2", question: "Where are sessions stored?" },
            ],
          }),
          ev("degraded", { stage: "budget", limit: "max_seconds", used: 120, allowed: 120 }),
        )}
      />,
    );
    expect(document.querySelector('[data-row="plan"]')).toHaveTextContent(
      "Split into 2 parts",
    );
    expect(document.querySelectorAll("[data-row]")).toHaveLength(1);
  });

  it("streams reasoning in full, then folds it once the next step starts", () => {
    const thinking = ev("thinking", { text: "one\ntwo\nthree\nfour", kind: "reasoning" });
    const { rerender } = render(<ActivityBlock run={stateOf(thinking)} />);
    let reasoning = document.querySelector('[data-row="reasoning"]') as HTMLElement;
    expect(reasoning).toHaveAttribute("data-open", "true");
    expect(reasoning).toHaveTextContent("Thinking");
    expect(reasoning.querySelector("p")).toHaveTextContent(/one\s*two\s*three\s*four/);

    rerender(
      <ActivityBlock
        run={stateOf(
          thinking,
          ev("tool_call", { call_id: "c1", tool: "grep_code", arguments: '{"pattern":"x"}' }),
        )}
      />,
    );
    reasoning = document.querySelector('[data-row="reasoning"]') as HTMLElement;
    expect(reasoning).toHaveAttribute("data-open", "false");
    expect(reasoning).toHaveTextContent("Thought");
    fireEvent.click(within(reasoning).getByRole("button"));
    expect(reasoning).toHaveAttribute("data-open", "true");
  });

  it("shows short narration as it is", () => {
    render(<ActivityBlock run={stateOf(ev("thinking", { text: "Checking the router." }))} />);
    expect(screen.getByText("Checking the router.")).toBeInTheDocument();
  });

  it("renders long streamed text as markdown, not as raw symbols", () => {
    const text = `## Steps\n\nThe pipeline has **nine** stages.\n\n${"More detail. ".repeat(30)}`;
    render(<ActivityBlock run={stateOf(ev("thinking", { text }))} />);
    const streamed = screen.getByTestId("streamed-text");
    expect(within(streamed).getByRole("heading", { name: "Steps" })).toBeInTheDocument();
    expect(streamed).not.toHaveTextContent("**");
  });

  it("opens a search to the queries it ran, what each search found and what it kept", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("retrieval", {
            source: "seed",
            channels: { dense: 40, lexical: 12, grep: 0 },
            keys: ["F:app/auth.py:1-20", "S:app/auth.py#login"],
            reranker: "jev",
            queries: [
              { text: "how does login work", kind: "original" },
              { text: "authentication flow", kind: "multi_query" },
            ],
          }),
        )}
      />,
    );
    const row = document.querySelector('[data-row="retrieval"]') as HTMLElement;
    expect(row).toHaveTextContent("2 queries");
    expect(row).toHaveTextContent("2 results");
    fireEvent.click(within(row).getByRole("button"));
    const details = screen.getByTestId("retrieval-details");
    expect(details).toHaveTextContent("how does login work");
    expect(details).toHaveTextContent("Rewrite");
    expect(details).toHaveTextContent("authentication flow");
    expect(details).toHaveTextContent("dense 40");
    expect(details).not.toHaveTextContent("grep");
    expect(details).toHaveTextContent("reranked by jev");
  });

  it("shows each worker as one closed row that opens to its own steps", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("plan", {
            subquestions: [
              { id: "w1", question: "How does login work?" },
              { id: "w2", question: "Where are sessions stored?" },
            ],
          }),
          ev("worker_started", { worker_id: "w1" }, "w1"),
          ev("worker_started", { worker_id: "w2" }, "w2"),
          ev("tool_call", { call_id: "a", tool: "grep_code", arguments: '{"pattern":"login"}' }, "w1"),
          ev("tool_call", { call_id: "b", tool: "grep_code", arguments: '{"pattern":"session"}' }, "w2"),
        )}
      />,
    );
    const first = document.querySelector('[data-lane="w1"]') as HTMLElement;
    const second = document.querySelector('[data-lane="w2"]') as HTMLElement;
    expect(within(first).getByText("How does login work?")).toBeInTheDocument();
    expect(first).toHaveAttribute("data-open", "false");
    expect(within(first).queryByTestId("lane-steps")).not.toBeInTheDocument();

    fireEvent.click(within(first).getByRole("button", { expanded: false }));
    const steps = within(first).getByTestId("lane-steps");
    expect(within(steps).getByText("login")).toBeInTheDocument();
    expect(within(steps).queryByText("session")).not.toBeInTheDocument();
    expect(within(second).queryByTestId("lane-steps")).not.toBeInTheDocument();
  });

  it("says what a running worker is doing while its row is closed", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("plan", { subquestions: [{ id: "w1", question: "Q1" }, { id: "w2", question: "Q2" }] }),
          ev("worker_started", { worker_id: "w1" }, "w1"),
          ev("tool_call", { call_id: "a", tool: "read_file", arguments: '{"path":"app/auth.py"}' }, "w1"),
        )}
      />,
    );
    const lane = document.querySelector('[data-lane="w1"]') as HTMLElement;
    expect(lane).toHaveTextContent("app/auth.py");
    expect(within(lane).getByLabelText("running")).toBeInTheDocument();
  });

  it("sums up a finished worker in its row", () => {
    render(
      <ActivityBlock
        run={stateOf(
          ev("plan", { subquestions: [{ id: "w1", question: "Q1" }, { id: "w2", question: "Q2" }] }),
          ev("worker_started", { worker_id: "w1" }, "w1"),
          ev("tool_call", { call_id: "a", tool: "grep_code", arguments: '{"pattern":"login"}' }, "w1"),
          ev("tool_result", { call_id: "a", tool: "grep_code", status: "ok" }, "w1"),
          ev("worker_done", { worker_id: "w1", status: "done" }, "w1"),
          ev("worker_done", { worker_id: "w2", status: "failed" }, "w2"),
        )}
      />,
    );
    expect(document.querySelector('[data-lane="w1"]')).toHaveTextContent("1 tool call");
    expect(document.querySelector('[data-lane="w2"]')).toHaveTextContent("Stopped");
  });

  it("drops text the agent wrote as its answer once that answer arrives", () => {
    const answer =
      "The router registers each handler at import time [F:app/router.py:1-9], and the app mounts it on startup.";
    const run = stateOf(
      ev("tool_call", { call_id: "c1", tool: "grep_code", arguments: '{"pattern":"zzz"}' }),
      ev("tool_result", { call_id: "c1", tool: "grep_code", status: "ok" }),
      ev("thinking", { text: "Checking the router." }),
      ev("tool_call", { call_id: "c2", tool: "read_file", arguments: '{"path":"a.py"}' }),
      ev("tool_result", { call_id: "c2", tool: "read_file", status: "ok" }),
      ev("thinking", { text: answer }),
      ev("done", { run_id: "run-1", answer }),
    );
    render(<ActivityBlock run={run} />);
    expect(screen.getByText("Checking the router.")).toBeInTheDocument();
    expect(screen.queryByText(/registers each handler/)).not.toBeInTheDocument();
  });

  it("renders nothing for a stored turn that recorded no steps", () => {
    const { container } = render(
      <ActivityBlock run={{ ...initialRunState, status: "done" }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
