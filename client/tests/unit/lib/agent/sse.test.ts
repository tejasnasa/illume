import { describe, expect, it } from "vitest";

import { SseParser } from "@/lib/agent/sse";

const FRAME = 'event: tool_call\ndata: {"a":1}\n\nevent: done\ndata: {"b":2}\n\n';

/** Feeds the text in chunks of `size` characters and returns every message. */
function parseInChunks(text: string, size: number) {
  const parser = new SseParser();
  const out = [];
  for (let i = 0; i < text.length; i += size) {
    out.push(...parser.push(text.slice(i, i + size)));
  }
  out.push(...parser.flush());
  return out;
}

describe("SseParser", () => {
  it("parses whole frames", () => {
    const messages = new SseParser().push(FRAME);
    expect(messages).toEqual([
      { event: "tool_call", data: '{"a":1}' },
      { event: "done", data: '{"b":2}' },
    ]);
  });

  it.each([1, 2, 3, 5, 7, 11])(
    "yields the same frames when split into %i-character chunks",
    (size) => {
      expect(parseInChunks(FRAME, size)).toEqual(new SseParser().push(FRAME));
    },
  );

  it("handles a chunk boundary in the middle of an event name", () => {
    const parser = new SseParser();
    expect(parser.push("eve")).toEqual([]);
    expect(parser.push("nt: gate\nda")).toEqual([]);
    expect(parser.push('ta: {"x":1}\n')).toEqual([]);
    expect(parser.push("\n")).toEqual([{ event: "gate", data: '{"x":1}' }]);
  });

  it("treats CRLF split across chunks as one line break", () => {
    const parser = new SseParser();
    const out = [
      ...parser.push("event: a\r"),
      ...parser.push("\ndata: 1\r"),
      ...parser.push("\n\r"),
      ...parser.push("\n"),
    ];
    expect(out).toEqual([{ event: "a", data: "1" }]);
  });

  it("ignores comment pings and joins multi-line data", () => {
    const messages = new SseParser().push(
      ": ping\n\nevent: x\ndata: one\ndata: two\n\n",
    );
    expect(messages).toEqual([{ event: "x", data: "one\ntwo" }]);
  });

  it("defaults the event name to message", () => {
    expect(new SseParser().push("data: hi\n\n")).toEqual([
      { event: "message", data: "hi" },
    ]);
  });

  it("flushes a final frame the server closed without a blank line", () => {
    const parser = new SseParser();
    expect(parser.push("event: done\ndata: end")).toEqual([]);
    expect(parser.flush()).toEqual([{ event: "done", data: "end" }]);
  });

  it("drops a frame with no data", () => {
    expect(new SseParser().push("event: lonely\n\n")).toEqual([]);
  });
});
