import { describe, expect, it } from "vitest";

import {
  MAX_HISTORY_CONTENT_CHARS,
  MAX_HISTORY_ITEMS,
  MAX_QUESTION_CHARS,
  boundHistory,
} from "@/lib/agent/limits";

const turn = (i: number, content = `turn ${i}`) => ({
  role: i % 2 === 0 ? ("user" as const) : ("assistant" as const),
  content,
});

describe("limits", () => {
  it("matches what the server accepts", () => {
    expect([
      MAX_QUESTION_CHARS,
      MAX_HISTORY_ITEMS,
      MAX_HISTORY_CONTENT_CHARS,
    ]).toEqual([4000, 40, 20000]);
  });
});

describe("boundHistory", () => {
  it("leaves a short history alone", () => {
    const history = [turn(0), turn(1)];

    expect(boundHistory(history)).toEqual(history);
  });

  it("keeps the newest items when there are too many", () => {
    const history = Array.from({ length: 50 }, (_, i) => turn(i));

    const bounded = boundHistory(history);

    expect(bounded).toHaveLength(MAX_HISTORY_ITEMS);
    expect(bounded[0].content).toBe("turn 10");
    expect(bounded.at(-1)?.content).toBe("turn 49");
  });

  it("cuts a turn that is too long and keeps its role", () => {
    const [bounded] = boundHistory([
      turn(1, "x".repeat(MAX_HISTORY_CONTENT_CHARS + 5)),
    ]);

    expect(bounded.content).toHaveLength(MAX_HISTORY_CONTENT_CHARS);
    expect(bounded.role).toBe("assistant");
  });

  it("keeps a turn exactly at the limit", () => {
    const content = "y".repeat(MAX_HISTORY_CONTENT_CHARS);

    expect(boundHistory([turn(0, content)])[0].content).toBe(content);
  });
});
