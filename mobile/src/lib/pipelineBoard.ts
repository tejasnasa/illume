/**
 * What the ingest pipeline board and log show, as pure functions.
 *
 * @module pipelineBoard
 *
 * Port of the board rules in ``client/src/utils/ingestFlow.ts``
 * (``PIPELINE_COLUMNS``, ``countLabel``, ``doneCount``) and of the card and
 * log formatting in ``client/src/components/ingest/``. The stage and phase
 * rules themselves -- seeding from the coarse status and folding frames into
 * node states -- live in :mod:`lib/ingestFlow`; this file only decides how
 * a state is worded and drawn.
 */

import { NODES_BY_ID, STAGE_IDS, type FlowNode } from "@/lib/ingestFlow";
import { colors } from "@/theme/tokens";
import type { IngestFrame, NodeState, StageState, StageStateMap } from "@/types/ingest";

/** One column of the board: a heading and the stages under it. */
export interface PipelineColumn {
  label: string;
  stages: readonly string[];
}

/**
 * The board columns, in order.
 *
 * Stages that share a column run at the same time -- the parse, the git
 * history mine and the PR fetch all start straight after the clone -- so the
 * columns read as "what can happen now" rather than as a strict sequence.
 */
export const PIPELINE_COLUMNS: readonly PipelineColumn[] = [
  { label: "Fetch", stages: ["clone"] },
  { label: "Read", stages: ["parse", "git_history", "pr_fetch"] },
  {
    label: "Connect",
    stages: ["resolve_dependencies", "compute_fan_metrics", "detect_stack"],
  },
  { label: "Score", stages: ["criticality"] },
  { label: "Write", stages: ["glossary", "reading_order"] },
  { label: "Index", stages: ["generate_embeddings", "brief"] },
  { label: "Done", stages: ["ready"] },
];

/** How a card of each state is drawn. */
export const CARD_LOOK: Record<
  NodeState,
  { mark: string; markColor: string; border: string; background: string }
> = {
  pending: { mark: "·", markColor: "#3f3f46", border: "#ffffff0f", background: colors.background },
  active: { mark: "●", markColor: colors.accent, border: "#f6339a66", background: "#f6339a0d" },
  done: { mark: "✓", markColor: colors.chart2, border: "#ffffff1a", background: colors.background },
  failed: { mark: "✕", markColor: colors.destructive, border: "#ef444480", background: "#ef44440d" },
};

/**
 * A stage total with its noun, such as `2,871 dependencies`.
 *
 * @param node - The stage the total belongs to.
 * @param count - The total it published.
 * @returns The label, or null for a stage whose totals carry no noun.
 */
export function countLabel(node: FlowNode, count: number): string | null {
  if (!node.unit) return null;
  const noun = count === 1 ? node.unit[0] : node.unit[1];
  return `${count.toLocaleString("en-US")} ${noun}`;
}

/**
 * The small line under a stage name.
 *
 * @param id - The stage id.
 * @param stage - Its state.
 * @returns For example `Waiting`, `120 / 400 files`, or `2,871 dependencies`.
 */
export function metaLine(id: string, stage: StageState): string {
  const node = NODES_BY_ID[id];
  switch (stage.state) {
    case "done": {
      const total = stage.count === undefined || !node ? null : countLabel(node, stage.count);
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

/**
 * How full a stage bar is.
 *
 * @param stage - The stage state.
 * @returns 0 to 1, or null for a running stage with no counter, which shows
 *   an indeterminate bar.
 */
export function fillOf(stage: StageState): number | null {
  if (stage.state === "done" || stage.state === "failed") return 1;
  if (stage.state === "pending") return 0;
  if (stage.progress && stage.progress.total > 0) {
    return Math.min(1, Math.max(0, stage.progress.processed / stage.progress.total));
  }
  return null;
}

/**
 * How many stages have finished.
 *
 * @param state - Every stage state.
 * @returns The count.
 */
export function doneCount(state: StageStateMap): number {
  return STAGE_IDS.filter((id) => state[id]?.state === "done").length;
}

/**
 * The text colour of a log line.
 *
 * @param frame - The frame.
 * @returns A hex colour.
 */
export function logTone(frame: IngestFrame): string {
  if (frame.phase === "failed" || frame.event === "error") return "#f87171";
  if (frame.phase === "done") return colors.chart2;
  if (frame.phase === "started") return colors.accent;
  return "#d4d4d8";
}

/**
 * A frame timestamp as a 24-hour clock time.
 *
 * @param timestamp - An ISO timestamp.
 * @returns `HH:MM:SS`, or an empty string when it does not parse.
 */
export function formatClock(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return "";
  const two = (n: number) => String(n).padStart(2, "0");
  return `${two(parsed.getHours())}:${two(parsed.getMinutes())}:${two(parsed.getSeconds())}`;
}

/**
 * The left-hand label of a log line.
 *
 * @param frame - The frame.
 * @returns `stage=<id>` for a stage frame, otherwise the event name.
 */
export function logLabel(frame: IngestFrame): string {
  return frame.stage ? `stage=${frame.stage}` : frame.event;
}
