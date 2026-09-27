/**
 * Collapsible raw ingestion log.
 *
 * The animation is the primary view, but the raw stream stays one click away:
 * an animation cannot tell you why something broke, and the text can.
 *
 * @module IngestLogDrawer
 */

"use client";

import type { IngestFrame } from "@/types/ingest";
import { CaretRightIcon, TerminalWindowIcon } from "@phosphor-icons/react/dist/ssr";
import { useEffect, useRef } from "react";

/** Map a frame's event to its terminal colour. */
function getLogColor(type: string): string {
  if (type === "error" || type.includes("failed")) return "text-red-400";
  if (type === "success" || type === "done") return "text-(--success)";
  if (type.includes("started")) return "text-blue-400";
  if (type.includes("complete")) return "text-(--success)";
  if (type === "status_update") return "text-yellow-400 font-bold";
  return "text-[#c9d1d9]";
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
 * The drawer.
 *
 * @param frames - Every line received so far, oldest first.
 * @param open - Whether the pane is expanded.
 * @param onToggle - Called when the header is clicked.
 * @returns The drawer, collapsed to a summary bar or expanded to a log pane.
 */
export default function IngestLogDrawer({
  frames,
  open,
  onToggle,
}: {
  frames: IngestFrame[];
  open: boolean;
  onToggle: () => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  // Follow the tail only while the reader is already at the tail. Yanking the
  // viewport back down while someone is scrolling through history is worse
  // than missing a line.
  const stickToBottom = useRef(true);

  useEffect(() => {
    if (open && stickToBottom.current) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [frames, open]);

  const latest = frames.length > 0 ? frames[frames.length - 1].message : "";

  return (
    <section
      className="shrink-0 border-t border-(--border) bg-(--background)/40"
      aria-label="Ingestion logs"
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-2 text-left text-xs text-(--muted-foreground) hover:text-(--foreground) transition-colors"
      >
        <CaretRightIcon
          size={12}
          className={`shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <TerminalWindowIcon size={14} className="shrink-0 text-(--primary)" />
        <span className="shrink-0 font-semibold uppercase tracking-wide">
          Ingest logs ({frames.length})
        </span>
        {!open && latest && (
          <span className="truncate font-mono text-(--muted-foreground)/60">
            {latest}
          </span>
        )}
      </button>

      {open && (
        <div
          role="region"
          aria-label="Raw ingestion output"
          onScroll={(event) => {
            const el = event.currentTarget;
            stickToBottom.current =
              el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
          }}
          className="h-[38vh] overflow-y-auto px-4 pb-3 font-mono text-xs custom-scrollbar"
        >
          {frames.map((frame, index) => (
            <div key={index} className="flex gap-3 leading-relaxed">
              <span className="shrink-0 select-none text-(--foreground)/20">
                [{formatTime(frame.timestamp)}]
              </span>
              <span className="shrink-0 select-none text-(--foreground)/30">
                {">"}
              </span>
              <span className={getLogColor(frame.event)}>{frame.message}</span>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}
    </section>
  );
}
