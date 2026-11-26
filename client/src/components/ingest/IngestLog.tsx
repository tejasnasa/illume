/**
 * The raw ingestion stream, shown as a terminal-style log.
 *
 * The board says where the run is; this says why. A failure's message only
 * ever reaches the reader through here.
 *
 * @module IngestLog
 */

"use client";

import type { IngestFrame } from "@/types/ingest";
import { useEffect, useRef } from "react";

/** Colour a line by what kind of frame it is. */
function toneOf(frame: IngestFrame): string {
  if (frame.phase === "failed" || frame.event === "error") return "text-red-400";
  if (frame.phase === "done") return "text-(--chart-2)";
  if (frame.phase === "started") return "text-(--accent)";
  return "text-zinc-300";
}

/** Render a frame's timestamp as a wall clock, falling back to nothing. */
function formatTime(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleTimeString([], {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/**
 * The log panel.
 *
 * @param frames - Every frame received so far, oldest first.
 * @param repoId - The run's repository, which names the channel the frames arrive on.
 * @param className - Grid placement from the parent.
 * @returns The panel.
 */
export default function IngestLog({
  frames,
  repoId,
  className = "",
}: {
  frames: readonly IngestFrame[];
  repoId?: string;
  className?: string;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  // Follow the tail only while the reader is already at the tail. Yanking the
  // viewport back down while someone is reading history is worse than
  // missing a line.
  const stickToBottom = useRef(true);

  useEffect(() => {
    const el = scroller.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [frames.length]);

  return (
    <section
      aria-label="Live log"
      className={`panel flex min-w-0 flex-col overflow-hidden ${className}`}
    >
      <p className="eyebrow m-0 flex items-center justify-between gap-3 border-b border-white/8 px-5 py-4">
        <span>Live log</span>
        <span className="truncate text-zinc-600" title={repoId ? `task:${repoId}:logs` : undefined}>
          {repoId ? `task:${repoId.slice(0, 4)}…:logs · ` : ""}
          {frames.length} lines
        </span>
      </p>
      <div
        ref={scroller}
        role="log"
        aria-label="Raw ingestion output"
        tabIndex={0}
        onScroll={(event) => {
          const el = event.currentTarget;
          stickToBottom.current =
            el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
        }}
        className="custom-scrollbar h-95 overflow-y-auto bg-[#060608] px-5 py-3.5 font-pixel text-xs tracking-[0.02em]"
      >
        {frames.length === 0 ? (
          <p className="blink m-0 text-zinc-600">Waiting for the first line…</p>
        ) : (
          frames.map((frame, index) => (
            <div
              key={index}
              className="grid grid-cols-[64px_minmax(0,1fr)] gap-3 py-0.75 sm:grid-cols-[64px_150px_minmax(0,1fr)]"
            >
              <span className="text-zinc-600">{formatTime(frame.timestamp)}</span>
              <span className="hidden truncate text-zinc-400 sm:block">
                {frame.stage ? `stage=${frame.stage}` : frame.event}
              </span>
              <span className={`break-words ${toneOf(frame)}`}>{frame.message}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
