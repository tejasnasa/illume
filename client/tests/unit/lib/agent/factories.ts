import type { StreamEvent } from "@/lib/agent/types";

let seq = 0;

/** Builds one envelope for the agent tests. */
export function ev(
  type: string,
  data: Record<string, unknown> = {},
  workerId: string | null = null,
): StreamEvent {
  seq += 1;
  return {
    seq,
    ts: "2026-01-01T00:00:00Z",
    run_id: "run-1",
    worker_id: workerId,
    type,
    data,
  };
}

/** Encodes events as the text of a server-sent-events body. */
export function sseBody(events: StreamEvent[]): string {
  return events
    .map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`)
    .join("");
}
