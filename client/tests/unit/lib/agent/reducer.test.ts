import { describe, expect, it } from "vitest";

import {
  initialRunState,
  runReducer,
  settledRunState,
  type RunAction,
  type RunState,
  type ToolRow,
} from "@/lib/agent/reducer";
import type { StreamEvent } from "@/lib/agent/types";
import { ev } from "./factories";

/** Runs events through the reducer from a freshly started run. */
function run(...events: StreamEvent[]): RunState {
  const actions: RunAction[] = [
    { type: "start", at: 1000 },
    ...events.map((event): RunAction => ({ type: "event", event, at: 2000 })),
  ];
  return actions.reduce(runReducer, initialRunState);
}

/** The first event of a run. */
function startedEvent() {
  return ev("run_started", {
    preset: "deep_agent",
    config_hash: "h",
    model: "m",
    execution: "agent",
  });
}

describe("the route event", () => {
  it("adds a row saying where an Auto request went", () => {
    const state = run(
      ev("route", {
        route: "relational",
        confidence: 0.82,
        probabilities: { relational: 0.82, local: 0.18 },
        resolved_preset: "structural",
        fallback_reason: null,
      }),
    );
    const [row] = state.rows;
    expect(row).toMatchObject({
      kind: "route",
      route: "relational",
      confidence: 0.82,
      resolvedPreset: "structural",
      fallbackReason: null,
    });
  });

  it("keeps the fallback reason", () => {
    const state = run(
      ev("route", {
        route: "global",
        confidence: 0.4,
        resolved_preset: "structural",
        fallback_reason: "low_confidence",
      }),
    );
    expect(state.rows[0]).toMatchObject({ kind: "route", fallbackReason: "low_confidence" });
  });

  it("tolerates a route event with no decision at all", () => {
    const state = run(
      ev("route", { resolved_preset: "structural", fallback_reason: "unavailable" }),
    );
    expect(state.rows[0]).toMatchObject({ route: null, confidence: null });
  });

  it("leaves the run live and the rows after it in order", () => {
    const state = run(
      startedEvent(),
      ev("route", { route: "local", confidence: 0.9, resolved_preset: "hybrid_rerank" }),
      ev("retrieval", { keys: ["F:a"] }),
    );
    expect(state.status).toBe("live");
    expect(state.rows.map((row) => row.kind)).toEqual(["route", "retrieval"]);
  });
});

describe("runReducer", () => {
  it("starts connecting and goes live on the first event", () => {
    const started = runReducer(initialRunState, { type: "start", at: 5 });
    expect(started.status).toBe("connecting");
    expect(started.startedAt).toBe(5);
    expect(run(startedEvent()).status).toBe("live");
  });

  it("records run_started metadata", () => {
    const state = run(
      ev("run_started", {
        preset: "deep_agent",
        config_hash: "h",
        model: "m",
        execution: "agent",
      }),
    );
    expect(state.meta?.execution).toBe("agent");
    expect(state.runId).toBe("run-1");
  });

  it("adds a plan row and lanes for sub-questions", () => {
    const state = run(
      ev("plan", {
        subquestions: [
          { id: "w1", question: "How is auth done?" },
          { id: "w2", question: "Where are tokens stored?" },
        ],
      }),
    );
    expect(state.rows[0].kind).toBe("plan");
    expect(state.laneOrder).toEqual(["w1", "w2"]);
    expect(state.lanes.w1.status).toBe("pending");
    expect(state.lanes.w2.colorIndex).toBe(1);
  });

  it("adds neither lanes nor a row for a skipped plan", () => {
    const state = run(ev("plan", { skipped: true, reason: "simple" }));
    expect(state.laneOrder).toEqual([]);
    expect(state.rows).toEqual([]);
  });

  it("moves a lane through started and done", () => {
    const planned = run(
      ev("plan", { subquestions: [{ id: "w1", question: "Q" }] }),
      ev("worker_started", { worker_id: "w1", question: "Q" }, "w1"),
    );
    expect(planned.lanes.w1.status).toBe("running");
    const done = runReducer(planned, {
      type: "event",
      event: ev("worker_done", { worker_id: "w1", status: "completed" }, "w1"),
    });
    expect(done.lanes.w1.status).toBe("done");
    expect(done.lanes.w1.question).toBe("Q");
  });

  it.each(["failed", "timed_out"] as const)(
    "marks a lane failed when its worker ended %s",
    (status) => {
      const state = run(
        ev("worker_started", { worker_id: "w1" }, "w1"),
        ev("worker_done", { worker_id: "w1", status }, "w1"),
      );
      expect(state.lanes.w1.status).toBe("failed");
    },
  );

  it.each(["completed", "partial"] as const)(
    "marks a lane done when its worker ended %s",
    (status) => {
      const state = run(
        ev("worker_started", { worker_id: "w1" }, "w1"),
        ev("worker_done", { worker_id: "w1", status }, "w1"),
      );
      expect(state.lanes.w1.status).toBe("done");
    },
  );

  it("adds a retrieval row and counts its keys as sources", () => {
    const state = run(
      ev("retrieval", {
        source: "seed",
        channels: { dense: 10 },
        keys: ["F:a.py:1-2", "F:b.py:3-4"],
      }),
    );
    expect(state.rows[0]).toMatchObject({ kind: "retrieval", kept: 2 });
    expect(state.evidenceKeys).toHaveLength(2);
  });

  it("merges consecutive thinking pieces into one row", () => {
    const state = run(
      ev("thinking", { text: "Let me " }),
      ev("thinking", { text: "look." }),
    );
    expect(state.rows).toHaveLength(1);
    expect(state.rows[0]).toMatchObject({
      kind: "thinking",
      mode: "text",
      text: "Let me look.",
    });
  });

  it("keeps each worker's streamed text in one row when workers interleave", () => {
    const state = run(
      ev("thinking", { text: "Worker one ", kind: "reasoning" }, "w1"),
      ev("thinking", { text: "Worker two ", kind: "reasoning" }, "w2"),
      ev("thinking", { text: "thinks.", kind: "reasoning" }, "w1"),
      ev("thinking", { text: "also thinks.", kind: "reasoning" }, "w2"),
    );
    expect(state.rows).toHaveLength(2);
    expect(state.rows.find((row) => row.laneId === "w1")).toMatchObject({
      text: "Worker one thinks.",
    });
    expect(state.rows.find((row) => row.laneId === "w2")).toMatchObject({
      text: "Worker two also thinks.",
    });
  });

  it("starts a new row for a worker once it has done something else", () => {
    const state = run(
      ev("thinking", { text: "Before.", kind: "reasoning" }, "w1"),
      ev("tool_call", { call_id: "c1", tool: "grep_code" }, "w1"),
      ev("thinking", { text: "After.", kind: "reasoning" }, "w1"),
    );
    expect(state.rows.map((row) => row.kind)).toEqual([
      "thinking",
      "tool",
      "thinking",
    ]);
  });

  it("keeps reasoning apart from what the model said", () => {
    const state = run(
      ev("thinking", { text: "The user wants ", kind: "reasoning" }),
      ev("thinking", { text: "the router.", kind: "reasoning" }),
      ev("thinking", { text: "Checking the router." }),
    );
    expect(state.rows).toHaveLength(2);
    expect(state.rows[0]).toMatchObject({
      mode: "reasoning",
      text: "The user wants the router.",
    });
    expect(state.rows[1]).toMatchObject({ mode: "text" });
  });

  it("keeps what a tool returned on its row", () => {
    const state = run(
      ev("tool_call", { call_id: "c1", tool: "read_file" }),
      ev("tool_result", {
        call_id: "c1",
        tool: "read_file",
        status: "ok",
        output: '<source key="F:a.py:1-2">x = 1</source>',
      }),
    );
    expect((state.rows[0] as ToolRow).output).toContain("x = 1");
  });

  it("pairs a tool_result with its tool_call by call id", () => {
    const state = run(
      ev("tool_call", {
        call_id: "c1",
        tool: "grep_code",
        arguments: '{"pattern":"login"}',
      }),
      ev("tool_call", { call_id: "c2", tool: "read_file", arguments: "{}" }),
      ev("tool_result", {
        call_id: "c2",
        tool: "read_file",
        status: "ok",
        result_count: 1,
        latency_ms: 12,
      }),
    );
    const [grep, read] = state.rows as ToolRow[];
    expect(grep.status).toBe("running");
    expect(grep.parsed).toEqual({ pattern: "login" });
    expect(read).toMatchObject({ status: "ok", resultCount: 1, latencyMs: 12 });
  });

  it("marks a failing tool as an error with its status", () => {
    const state = run(
      ev("tool_call", { call_id: "c1", tool: "read_file" }),
      ev("tool_result", {
        call_id: "c1",
        tool: "read_file",
        status: "not_found",
      }),
    );
    expect(state.rows[0]).toMatchObject({
      status: "error",
      failure: "not_found",
    });
  });

  it("tolerates arguments that are not valid JSON", () => {
    const state = run(
      ev("tool_call", { call_id: "c1", tool: "grep_code", arguments: '{"pat' }),
    );
    expect((state.rows[0] as ToolRow).parsed).toBeNull();
  });

  it("highlights nodes, attaches paths to the call and tracks the trail", () => {
    const state = run(
      ev("tool_call", { call_id: "c1", tool: "grep_code" }),
      ev("nodes", {
        call_id: "c1",
        tool: "grep_code",
        paths: ["a.py", "b.py"],
      }),
      ev("tool_call", { call_id: "c2", tool: "read_file" }),
      ev("nodes", { call_id: "c2", tool: "read_file", paths: ["c.py"] }, "w1"),
    );
    expect(state.highlight.touched).toEqual(["a.py", "b.py", "c.py"]);
    expect(state.highlight.current).toEqual(["c.py"]);
    expect(state.highlight.focus).toBe("c.py");
    expect(state.highlight.focusSeq).toBe(2);
    expect(state.highlight.edges).toEqual([["a.py", "c.py"]]);
    expect(state.highlight.laneOf["c.py"]).toBe("w1");
    expect((state.rows[0] as ToolRow).paths).toEqual(["a.py", "b.py"]);
  });

  it("follows a reported path edge by edge", () => {
    const state = run(
      ev("nodes", {
        tool: "find_path",
        action: "path",
        paths: ["a", "b", "c"],
      }),
    );
    expect(state.highlight.edges).toEqual([
      ["a", "b"],
      ["b", "c"],
    ]);
  });

  it("ignores a nodes event with no paths", () => {
    const before = run(startedEvent());
    const after = runReducer(before, {
      type: "event",
      event: ev("nodes", { paths: [] }),
    });
    expect(after.highlight).toBe(before.highlight);
  });

  it("collects evidence keys without duplicates", () => {
    const state = run(
      ev("evidence", { keys: ["F:a", "F:b"] }),
      ev("evidence", { keys: ["F:b", "F:c"] }),
    );
    expect(state.evidenceKeys).toEqual(["F:a", "F:b", "F:c"]);
  });

  it("adds no row for a degradation", () => {
    const state = run(
      ev("degraded", {
        stage: "budget",
        limit: "max_seconds",
        used: 120,
        allowed: 120,
      }),
    );
    expect(state.rows).toEqual([]);
  });

  it("appends answer deltas", () => {
    const state = run(
      ev("answer_delta", { text: "Hello " }),
      ev("answer_delta", { text: "world" }),
    );
    expect(state.answer).toBe("Hello world");
    expect(state.phase).toBe("answering");
  });

  it("settles on error with the server's message", () => {
    const state = run(
      ev("error", { message: "provider down", kind: "provider", status: 502 }),
    );
    expect(state.status).toBe("error");
    expect(state.error).toEqual({
      message: "provider down",
      kind: "provider",
      status: 502,
    });
    expect(state.endedAt).toBe(2000);
  });

  it("settles on done with the final answer, citations and cited nodes", () => {
    const state = run(
      ev("answer_delta", { text: "draft" }),
      ev("done", {
        run_id: "run-1",
        answer: "Final [F:a.py:1-2]",
        citations: [
          { key: "F:a.py:1-2", source_type: "symbol", file_path: "a.py" },
        ],
        unresolved: ["F:ghost.py"],
        stop_reason: "finished",
        usage: { elapsed_seconds: 9 },
        chat_message_id: "msg-1",
        limits_reached: ["max_seconds"],
      }),
    );
    expect(state.status).toBe("done");
    expect(state.answer).toBe("Final [F:a.py:1-2]");
    expect(state.highlight.cited).toEqual(["a.py"]);
    expect(state.highlight.current).toEqual([]);
    expect(state.unresolved).toEqual(["F:ghost.py"]);
    expect(state.chatMessageId).toBe("msg-1");
    expect(state.usage?.elapsed_seconds).toBe(9);
  });

  it("ignores an unknown event type without crashing or changing anything", () => {
    const before = run(startedEvent());
    const after = runReducer(before, {
      type: "event",
      event: ev("brand_new_event", { anything: true }),
    });
    expect(after).toBe(before);
  });

  it("ignores events after the run has finished", () => {
    const done = run(ev("done", { run_id: "run-1", answer: "x" }));
    const after = runReducer(done, {
      type: "event",
      event: ev("answer_delta", { text: "late" }),
    });
    expect(after.answer).toBe("x");
  });

  it("cancels a live run but not a finished one", () => {
    const live = run(startedEvent());
    expect(runReducer(live, { type: "cancelled", at: 9 })).toMatchObject({
      status: "cancelled",
      endedAt: 9,
    });
    const done = run(ev("done", { run_id: "r", answer: "x" }));
    expect(runReducer(done, { type: "cancelled", at: 9 }).status).toBe("done");
  });

  it("records a lost connection and keeps what arrived", () => {
    const live = run(ev("answer_delta", { text: "part" }));
    const lost = runReducer(live, { type: "connection_lost", at: 7 });
    expect(lost.status).toBe("connection_lost");
    expect(lost.answer).toBe("part");
    expect(lost.runId).toBe("run-1");
  });

  it("records an HTTP failure", () => {
    const failed = runReducer(
      runReducer(initialRunState, { type: "start", at: 1 }),
      {
        type: "failed",
        message: "Agent presets run on your own API key.",
        status: 402,
      },
    );
    expect(failed).toMatchObject({ status: "error", error: { status: 402 } });
  });

  it("builds a settled state for stored history", () => {
    const state = settledRunState("Stored [F:a.py]", [
      { file_path: "a.py", source_type: "file" },
    ]);
    expect(state.status).toBe("done");
    expect(state.highlight.cited).toEqual(["a.py"]);
  });

  it("resets", () => {
    expect(runReducer(run(startedEvent()), { type: "reset" })).toBe(
      initialRunState,
    );
  });
});
