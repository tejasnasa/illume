/**
 * The ingestion pipeline drawn as columns of stage cards.
 * @module PipelineBoard
 */

import type { NodeState, StageState, StageStateMap } from "@/types/ingest";
import {
  NODES,
  NODES_BY_ID,
  PIPELINE_COLUMNS,
  countLabel,
} from "@/utils/ingestFlow";

/** Glyph, glyph colour and card chrome for each state. */
const LOOK: Record<
  NodeState,
  { mark: string; markColor: string; border: string; background: string }
> = {
  pending: {
    mark: "·",
    markColor: "#3f3f46",
    border: "#ffffff0f",
    background: "#09090b",
  },
  active: {
    mark: "●",
    markColor: "var(--accent)",
    border: "#f6339a66",
    background: "#f6339a0d",
  },
  done: {
    mark: "✓",
    markColor: "var(--chart-2)",
    border: "#ffffff1a",
    background: "#09090b",
  },
  failed: {
    mark: "✕",
    markColor: "var(--destructive)",
    border: "#ef444480",
    background: "#ef44440d",
  },
};

/**
 * The one-line status under a stage's name.
 *
 * A finished stage shows its total when it published one, a running parse
 * shows its counter, and anything else falls back to the state itself.
 */
function metaLine(id: string, stage: StageState): string {
  const node = NODES_BY_ID[id];
  switch (stage.state) {
    case "done": {
      const total =
        stage.count === undefined ? null : countLabel(node, stage.count);
      return total ?? "Done";
    }
    case "active":
      if (stage.progress) {
        const { processed, total } = stage.progress;
        return `${processed.toLocaleString("en-US")} / ${total.toLocaleString("en-US")} files`;
      }
      return "Running";
    case "failed":
      return "Failed";
    default:
      return "Waiting";
  }
}

/** How full a stage's bar is, from 0 to 1. Null draws a moving bar instead. */
function fillOf(stage: StageState): number | null {
  if (stage.state === "done" || stage.state === "failed") return 1;
  if (stage.state === "pending") return 0;
  if (stage.progress) return stage.progress.processed / stage.progress.total;
  return null;
}

/** One stage card. */
function StageCard({ id, stage }: { id: string; stage: StageState }) {
  const look = LOOK[stage.state];
  const fill = fillOf(stage);
  const waiting = stage.state === "pending";

  return (
    <div
      className="flex min-w-0 flex-col gap-1.5 rounded-sm border px-3 py-2.5 transition-[border-color,background-color] duration-300 ease-[steps(2)]"
      style={{ borderColor: look.border, background: look.background }}
    >
      <span className="flex items-center justify-between gap-2">
        <span
          className={`truncate text-sm ${waiting ? "text-zinc-500" : "text-(--foreground)"}`}
        >
          {NODES_BY_ID[id].label}
        </span>
        <span
          aria-hidden="true"
          className={`font-pixel text-xs ${stage.state === "active" ? "blink" : ""}`}
          style={{ color: look.markColor }}
        >
          {look.mark}
        </span>
      </span>
      <span className="truncate font-pixel text-[11px] tracking-[0.05em] text-zinc-500 uppercase">
        {metaLine(id, stage)}
      </span>
      <span aria-hidden="true" className="block h-0.5 overflow-hidden bg-white/6">
        {fill === null ? (
          <span
            className="bar-fill block h-0.5 w-full"
            style={{ background: look.markColor }}
          />
        ) : (
          <span
            className="block h-0.5 transition-[width] duration-200 ease-[steps(3)]"
            style={{ width: `${Math.round(fill * 100)}%`, background: look.markColor }}
          />
        )}
      </span>
    </div>
  );
}

/**
 * The board.
 *
 * @param states - Current state of every stage.
 * @returns The pipeline card, with a screen-reader summary of every stage.
 */
export default function PipelineBoard({ states }: { states: StageStateMap }) {
  const stageOf = (id: string): StageState => states[id] ?? { state: "pending" };

  return (
    <section aria-label="Pipeline" className="panel flex flex-col gap-4 p-5.5">
      <p className="eyebrow m-0 flex flex-wrap items-center justify-between gap-3">
        <span>Pipeline</span>
        <span aria-hidden="true" className="flex gap-4 text-zinc-500">
          <span>
            <span className="text-(--chart-2)">✓</span> Done
          </span>
          <span>
            <span className="text-(--accent)">●</span> Running
          </span>
          <span>
            <span className="text-zinc-600">·</span> Waiting
          </span>
        </span>
      </p>

      {/* The cards are visual; the list below is what a screen reader gets. */}
      <div
        aria-hidden="true"
        className="custom-scrollbar grid grid-cols-[repeat(7,minmax(150px,1fr))] gap-3 overflow-x-auto pb-1 xl:grid-cols-7"
      >
        {PIPELINE_COLUMNS.map((column, index) => (
          <div key={column.label} className="relative flex min-w-0 flex-col gap-2">
            <span className="font-pixel text-[10px] tracking-[0.14em] text-zinc-600 uppercase">
              {column.label}
            </span>
            {column.stages.map((id) => (
              <StageCard key={id} id={id} stage={stageOf(id)} />
            ))}
            {index < PIPELINE_COLUMNS.length - 1 && (
              <span className="absolute top-11 -right-3 h-px w-3 bg-white/15" />
            )}
          </div>
        ))}
      </div>

      {/* Progress counters are deliberately left out: a ten-thousand-file
          parse would otherwise announce itself hundreds of times. A stage's
          total arrives once, so it rides along with the state change. */}
      <ol className="sr-only" aria-live="polite" aria-atomic="false">
        {NODES.map((node) => {
          const stage = stageOf(node.id);
          const total =
            stage.count === undefined ? null : countLabel(node, stage.count);
          return (
            <li key={node.id}>
              {node.label}: {stage.state}
              {total ? ` (${total})` : ""}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
