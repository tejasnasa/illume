/**
 * A small server-sent-events parser for `fetch` response bodies.
 *
 * `EventSource` cannot send a POST body, so the stream is read with `fetch` and
 * fed through this parser chunk by chunk. A chunk boundary may fall anywhere,
 * including inside a field name or between the `\r` and `\n` of a line ending,
 * so the parser buffers whatever has not yet formed a complete line.
 * @module Sse
 */

/** One dispatched server-sent event. */
export interface SseMessage {
  /** The `event:` name; `message` when the frame names none. */
  event: string;
  /** The `data:` lines joined with a line feed. */
  data: string;
  /** The last `id:` seen, when the frame carried one. */
  id?: string;
}

/**
 * Incremental SSE parser.
 *
 * Follows the field rules of the specification: lines starting with `:` are
 * comments (the server's keep-alive pings), one leading space after the colon
 * is dropped, repeated `data:` lines join with `\n`, and a blank line
 * dispatches the frame. A frame with no data is dropped.
 */
export class SseParser {
  private buffer = "";
  private event = "";
  private data: string[] = [];
  private id: string | undefined;
  private sawCarriageReturn = false;

  /**
   * Consumes the next chunk of text.
   *
   * @param chunk - Decoded text, split anywhere.
   * @returns The frames completed by this chunk, in order.
   */
  push(chunk: string): SseMessage[] {
    const out: SseMessage[] = [];
    let text = chunk;

    // A previous chunk ended in `\r`; if this one starts with `\n` it was the
    // second half of a `\r\n` pair and must not count as a second line break.
    if (this.sawCarriageReturn) {
      this.sawCarriageReturn = false;
      if (text.startsWith("\n")) text = text.slice(1);
    }

    this.buffer += text;
    let start = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const ch = this.buffer[i];
      if (ch !== "\n" && ch !== "\r") continue;
      if (ch === "\r") {
        if (i + 1 === this.buffer.length) {
          this.sawCarriageReturn = true;
        } else if (this.buffer[i + 1] === "\n") {
          this.consumeLine(this.buffer.slice(start, i), out);
          i += 1;
          start = i + 1;
          continue;
        }
      }
      this.consumeLine(this.buffer.slice(start, i), out);
      start = i + 1;
    }
    this.buffer = this.buffer.slice(start);
    return out;
  }

  /**
   * Flushes a trailing frame the server closed without a blank line.
   *
   * @returns The pending frame, if one has data.
   */
  flush(): SseMessage[] {
    const out: SseMessage[] = [];
    if (this.buffer.length > 0) {
      this.consumeLine(this.buffer, out);
      this.buffer = "";
    }
    this.dispatch(out);
    return out;
  }

  private consumeLine(line: string, out: SseMessage[]) {
    if (line === "") {
      this.dispatch(out);
      return;
    }
    if (line.startsWith(":")) return;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    else if (field === "id") this.id = value;
  }

  private dispatch(out: SseMessage[]) {
    if (this.data.length > 0) {
      out.push({
        event: this.event || "message",
        data: this.data.join("\n"),
        ...(this.id !== undefined ? { id: this.id } : {}),
      });
    }
    this.event = "";
    this.data = [];
  }
}
