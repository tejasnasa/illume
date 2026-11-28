/**
 * The steps of an agent run, inline in the message.
 *
 * @module ActivityBlock
 *
 * Port of ``client/src/components/chat/ActivityBlock.tsx``: tool calls,
 * searches, narration and reasoning in the order they happened. A route row
 * says which preset an Auto request ran with. A plan row heads the workers of
 * a deep agent run, and each worker has its own numbered lane, drawn like a
 * tool call: one row in the lane colour with its sub-question, what it is
 * doing or what it did, and a status mark. Opening a lane shows the
 * worker's own steps.
 */

import { useState, type ReactNode } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import { shortKeyLabel } from "@/lib/agent/answer";
import { laneColor } from "@/lib/agent/palette";
import { PRESET_DEFAULTS, type PresetId } from "@/lib/agent/presets";
import type {
  ActivityRow,
  Lane,
  PlanRow,
  RetrievalRow,
  RouteRow,
  RunState,
  ThinkingRow,
  ToolRow,
} from "@/lib/agent/reducer";
import { readRange, shortArgs, statusLabel, toolLabel } from "@/lib/agent/tools";
import { AgentMarkdown } from "@/components/chat/AgentMarkdown";

const FALLBACK_REASONS: Record<string, string> = {
  low_confidence: "low confidence",
  unavailable: "router unavailable",
  timeout: "router timed out",
  error: "routing failed",
  no_tool_support: "model cannot call tools",
};

/** One line saying which preset an Auto request ran with, and why. */
export function routeSummary(row: RouteRow): string {
  const preset =
    PRESET_DEFAULTS[row.resolvedPreset as PresetId]?.label ?? row.resolvedPreset;
  if (row.fallbackReason) {
    const why = FALLBACK_REASONS[row.fallbackReason] ?? row.fallbackReason;
    return `Fell back to ${preset} (${why})`;
  }
  const parts = [`Routed to ${preset}`];
  if (row.route) parts.push(row.route.replace(/_/g, " "));
  if (row.confidence !== null) parts.push(`${Math.round(row.confidence * 100)}%`);
  return parts.join(" · ");
}

/** The heading line of a plan: how many parts the question was split into. */
export function planSummary(row: PlanRow): string {
  const count = row.subquestions.length;
  return `Split into ${count} ${count === 1 ? "part" : "parts"}, worked on in parallel`;
}

/** A latency in a short form, or null when unknown. */
export function formatLatency(ms: number | null): string | null {
  if (ms == null) return null;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** The longest tool output shown inline. */
const OUTPUT_SHOWN_CHARS = 1500;

const QUERY_KINDS: Record<string, string> = {
  original: "Question",
  condensed: "Rewritten with the conversation",
  multi_query: "Rewrite",
  hyde: "Hypothetical code",
};

const RETRIEVED_SHOWN = 20;

/** Narration longer than this is a draft or an explanation, and folds once written. */
const SHORT_NARRATION = 280;

/** A step row with a leading mark and a tappable header. */
function Row({
  testID,
  mark,
  title,
  detail,
  right,
  borderColor,
  expandable = false,
  open = false,
  onToggle,
  children,
}: {
  testID?: string;
  mark: ReactNode;
  title: string;
  detail?: ReactNode;
  right?: ReactNode;
  borderColor?: string;
  expandable?: boolean;
  open?: boolean;
  onToggle?: () => void;
  children?: ReactNode;
}) {
  return (
    <View testID={testID}>
      <Pressable
        disabled={!expandable}
        accessibilityRole="button"
        accessibilityState={{ expanded: expandable ? open : undefined }}
        onPress={onToggle}
        className="flex-row items-center gap-2 rounded-sm px-2 py-2 active:bg-white/5"
        style={
          borderColor
            ? { borderLeftWidth: 2, borderLeftColor: borderColor }
            : undefined
        }
      >
        {mark}
        <Text className="font-pixel text-xs text-foreground">{title}</Text>
        <View className="min-w-0 flex-1 flex-row items-center gap-1.5 overflow-hidden">
          {detail}
        </View>
        <View className="flex-row items-center gap-2">{right}</View>
        {expandable ? (
          <Text className="font-pixel text-[11px] text-muted-foreground">
            {open ? "▴" : "▾"}
          </Text>
        ) : null}
      </Pressable>
      {open ? children : null}
    </View>
  );
}

/** The small status mark of a tool or worker. */
function Mark({ state }: { state: "running" | "ok" | "error" }) {
  if (state === "running") {
    return (
      <View
        accessibilityLabel="running"
        className="h-1.5 w-1.5 bg-accent"
      />
    );
  }
  return (
    <Text
      accessibilityLabel={state === "ok" ? "done" : "failed"}
      className={`font-pixel text-xs ${state === "ok" ? "text-success" : "text-destructive"}`}
    >
      {state === "ok" ? "✓" : "✕"}
    </Text>
  );
}

function ToolRowView({ row }: { row: ToolRow }) {
  const [open, setOpen] = useState(false);
  const args = shortArgs(row.tool, row.parsed);
  const range = row.tool === "read_file" ? readRange(row) : null;
  const latency = formatLatency(row.latencyMs);
  const expandable =
    row.status !== "running" &&
    (Boolean(row.output) || row.paths.length > 0 || Boolean(row.summary));

  return (
    <Row
      testID={`row-tool-${row.tool}`}
      mark={<Mark state={row.status} />}
      title={toolLabel(row.tool)}
      detail={args.map((arg, i) => (
        <Text
          key={i}
          numberOfLines={1}
          className={`shrink text-[11px] ${
            arg.kind === "query" ? "italic text-zinc-300" : "font-pixel text-zinc-400"
          }`}
        >
          {arg.kind === "query" ? `"${arg.value}"` : arg.value}
          {arg.extra ? ` ${arg.extra}` : ""}
        </Text>
      ))}
      right={
        <>
          {row.resultCount != null &&
          row.status === "ok" &&
          row.tool !== "finish" ? (
            <Text className="font-pixel text-[11px] text-subtle-foreground">
              {row.resultCount} found
            </Text>
          ) : null}
          {latency ? (
            <Text className="font-pixel text-[11px] text-subtle-foreground">
              {latency}
            </Text>
          ) : null}
        </>
      }
      expandable={expandable}
      open={open}
      onToggle={() => setOpen((v) => !v)}
    >
      <View className="mb-1.5 ml-6 mr-2 gap-1.5 rounded-sm border border-border bg-background/80 p-2.5">
        {range && row.paths[0] ? (
          <Text className="font-pixel text-[11px] text-muted-foreground">
            {row.paths[0]} · {range}
          </Text>
        ) : null}
        {row.output ? (
          <Text className="font-pixel text-[11px] leading-[17px] text-zinc-300">
            {row.output.length > OUTPUT_SHOWN_CHARS
              ? `${row.output.slice(0, OUTPUT_SHOWN_CHARS)}…`
              : row.output}
          </Text>
        ) : (
          <>
            {row.summary ? (
              <Text className="text-[11px] text-muted-foreground">
                {row.summary}
              </Text>
            ) : null}
            {row.tool !== "read_file"
              ? row.paths.slice(0, 12).map((path) => (
                  <Text
                    key={path}
                    numberOfLines={1}
                    className="font-pixel text-[11px] text-foreground/85"
                  >
                    {path}
                  </Text>
                ))
              : null}
            {row.paths.length > 12 && row.tool !== "read_file" ? (
              <Text className="text-[11px] text-muted-foreground">
                and {row.paths.length - 12} more
              </Text>
            ) : null}
          </>
        )}
      </View>
    </Row>
  );
}

function RouteRowView({ row }: { row: RouteRow }) {
  return (
    <Row
      testID="row-route"
      mark={<Text className="font-pixel text-xs text-chart-1">›</Text>}
      title={routeSummary(row)}
    />
  );
}

function PlanRowView({ row }: { row: PlanRow }) {
  return (
    <Row
      testID="row-plan"
      mark={<Text className="font-pixel text-xs text-chart-2">≡</Text>}
      title={planSummary(row)}
    />
  );
}

function RetrievalRowView({ row }: { row: RetrievalRow }) {
  const [open, setOpen] = useState(false);
  const channels = Object.entries(row.channels).filter(([, count]) => count > 0);
  const expandable =
    row.queries.length > 0 || channels.length > 0 || row.keys.length > 0;

  return (
    <Row
      testID="row-retrieval"
      mark={<Text className="font-pixel text-xs text-muted-foreground">⌕</Text>}
      title="Searched the codebase"
      detail={
        <Text className="text-[11px] text-muted-foreground" numberOfLines={1}>
          {row.queries.length > 1 ? `${row.queries.length} queries · ` : ""}
          {row.kept} {row.kept === 1 ? "result" : "results"}
        </Text>
      }
      expandable={expandable}
      open={open}
      onToggle={() => setOpen((v) => !v)}
    >
      <View
        testID="retrieval-details"
        className="mb-1.5 ml-6 mr-2 gap-3 rounded-sm bg-background/40 p-2.5"
      >
        {row.queries.length > 0 ? (
          <View className="gap-1">
            <Text className="text-[11px] font-sans-medium text-muted-foreground">
              Queries
            </Text>
            {row.queries.map((query, i) => (
              <Text key={i} className="text-[11px] text-foreground/90">
                <Text className="text-muted-foreground">
                  {QUERY_KINDS[query.kind] ?? query.kind}:{" "}
                </Text>
                {query.text}
              </Text>
            ))}
          </View>
        ) : null}
        {channels.length > 0 ? (
          <View className="gap-1">
            <Text className="text-[11px] font-sans-medium text-muted-foreground">
              Candidates per search
            </Text>
            <View className="flex-row flex-wrap gap-1.5">
              {channels.map(([channel, count]) => (
                <Text
                  key={channel}
                  className="rounded-sm border border-border px-2 py-0.5 text-[11px] text-foreground"
                >
                  {channel} {count}
                </Text>
              ))}
              {row.reranker && row.reranker !== "none" ? (
                <Text className="rounded-sm border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                  reranked by {row.reranker}
                </Text>
              ) : null}
            </View>
          </View>
        ) : null}
        {row.keys.length > 0 ? (
          <View className="gap-0.5">
            <Text className="text-[11px] font-sans-medium text-muted-foreground">
              Kept
            </Text>
            {row.keys.slice(0, RETRIEVED_SHOWN).map((key) => (
              <Text
                key={key}
                numberOfLines={1}
                className="font-pixel text-[11px] text-foreground/85"
              >
                {shortKeyLabel(key)}
              </Text>
            ))}
            {row.keys.length > RETRIEVED_SHOWN ? (
              <Text className="text-[11px] text-muted-foreground">
                and {row.keys.length - RETRIEVED_SHOWN} more
              </Text>
            ) : null}
          </View>
        ) : null}
      </View>
    </Row>
  );
}

/**
 * What the model said or thought between tool calls.
 *
 * Short narration stays as it is; reasoning and longer text are open while
 * they are being written and fold once the next step starts.
 */
function ThinkingRowView({ row, live }: { row: ThinkingRow; live: boolean }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const text = row.text.trim();
  const reasoning = row.mode === "reasoning";
  if (!text) return null;

  if (!reasoning && text.length <= SHORT_NARRATION && !text.includes("\n\n")) {
    return (
      <View testID="row-thinking" className="px-2 py-1.5">
        <Text className="text-[13px] leading-[19px] text-foreground/85">
          {text}
        </Text>
      </View>
    );
  }

  const open = userOpen ?? live;
  const label = reasoning ? (live ? "Thinking" : "Thought") : live ? "Writing" : "Wrote";
  const preview = text.replace(/\s+/g, " ").slice(0, 100);

  return (
    <Row
      testID={reasoning ? "row-reasoning" : "row-thinking"}
      mark={<Text className="font-pixel text-xs text-chart-2">{reasoning ? "◌" : "…"}</Text>}
      title={label}
      detail={
        open ? null : (
          <Text numberOfLines={1} className="text-[11px] text-muted-foreground">
            {preview}
          </Text>
        )
      }
      expandable
      open={open}
      onToggle={() => setUserOpen(!open)}
    >
      <ScrollView
        nestedScrollEnabled
        style={{ maxHeight: 280 }}
        className="mb-1.5 ml-6 mr-2"
      >
        {reasoning ? (
          <Text className="text-[13px] italic leading-[19px] text-muted-foreground">
            {text}
          </Text>
        ) : (
          <AgentMarkdown text={text} live={live} settled={!live} compact />
        )}
      </ScrollView>
    </Row>
  );
}

function RowView({ row, live }: { row: ActivityRow; live: boolean }) {
  switch (row.kind) {
    case "tool":
      return <ToolRowView row={row} />;
    case "route":
      return <RouteRowView row={row} />;
    case "plan":
      return <PlanRowView row={row} />;
    case "retrieval":
      return <RetrievalRowView row={row} />;
    case "thinking":
      return <ThinkingRowView row={row} live={live} />;
  }
}

/** Rows in order; only the last can still be live. */
function RowList({ rows, live }: { rows: ActivityRow[]; live: boolean }) {
  if (rows.length === 0) return null;
  return (
    <View>
      {rows.map((row, i) => (
        <RowView key={row.id} row={row} live={live && i === rows.length - 1} />
      ))}
    </View>
  );
}

/** What a running worker is doing, from its latest step. */
export function laneActivity(rows: ActivityRow[]): string | null {
  const last = rows[rows.length - 1];
  if (!last) return null;
  if (last.kind === "tool") {
    const [first] = shortArgs(last.tool, last.parsed);
    const label = toolLabel(last.tool);
    return first ? `${label} ${first.value}` : label;
  }
  if (last.kind === "thinking") {
    return last.mode === "reasoning" ? "Thinking" : last.text.trim().split("\n")[0];
  }
  if (last.kind === "retrieval") return "Searching the codebase";
  return null;
}

/**
 * One worker's lane, numbered by its place in the plan.
 *
 * @param props - The lane, its rows and its number, from 1.
 */
function LaneView({
  lane,
  rows,
  number,
}: {
  lane: Lane;
  rows: ActivityRow[];
  number: number;
}) {
  const [open, setOpen] = useState(false);
  const color = laneColor(lane.colorIndex);
  const running = lane.status === "running" || lane.status === "pending";
  const tools = rows.filter((row) => row.kind === "tool").length;
  const files = new Set(
    rows.flatMap((row) => (row.kind === "tool" ? row.paths : [])),
  ).size;
  const detail = running
    ? laneActivity(rows)
    : [
        lane.status === "failed" && "Stopped",
        tools > 0 && `${tools} ${tools === 1 ? "tool call" : "tool calls"}`,
        files > 0 && `${files} ${files === 1 ? "file" : "files"}`,
      ]
        .filter(Boolean)
        .join(" · ");

  return (
    <View testID={`lane-${lane.id}`} accessibilityLabel={`Worker ${number}: ${lane.question}`}>
      <Row
        borderColor={color}
        mark={<Text style={{ color }} className="font-pixel text-xs">#{number}</Text>}
        title="Worker"
        detail={
          <Text numberOfLines={1} className="shrink text-xs text-foreground/90">
            {lane.question || lane.id}
          </Text>
        }
        right={
          <>
            {detail ? (
              <Text
                numberOfLines={1}
                className="max-w-[90px] font-pixel text-[10px] text-subtle-foreground"
              >
                {detail}
              </Text>
            ) : null}
            <Mark
              state={running ? "running" : lane.status === "failed" ? "error" : "ok"}
            />
          </>
        }
        expandable
        open={open}
        onToggle={() => setOpen((v) => !v)}
      >
        <View
          testID="lane-steps"
          className="mb-1 ml-4 mr-2 rounded-sm bg-background/40 py-1 pl-1 pr-1"
          style={{ borderLeftWidth: 2, borderLeftColor: `${color}66` }}
        >
          {rows.length > 0 ? (
            <RowList rows={rows} live={lane.status === "running"} />
          ) : (
            <Text className="px-2 py-1 text-xs text-muted-foreground">
              {running ? "Starting…" : "No steps recorded."}
            </Text>
          )}
        </View>
      </Row>
    </View>
  );
}

/**
 * The steps of a run, with a status line while it is live.
 *
 * @param props - The run state to show.
 * @returns The steps, or null when the run recorded none and is not live.
 */
export function ActivityBlock({ run }: { run: RunState }) {
  const live = run.status === "connecting" || run.status === "live";
  if (run.rows.length === 0 && !live) return null;

  const laneRows = (laneId: string) =>
    run.rows.filter((row) => row.laneId === laneId);
  const firstLaneIndex = run.rows.findIndex((row) => row.laneId !== null);
  const before =
    firstLaneIndex === -1
      ? run.rows
      : run.rows.slice(0, firstLaneIndex).filter((r) => r.laneId === null);
  const after =
    firstLaneIndex === -1
      ? []
      : run.rows.slice(firstLaneIndex).filter((r) => r.laneId === null);
  const lanes = run.laneOrder.map((id) => run.lanes[id]).filter(Boolean);
  const last = run.rows[run.rows.length - 1];
  // Streaming text says what is happening on its own; a status line under it is noise.
  const streamingText = live && last?.kind === "thinking";
  const answering = run.answer.length > 0;

  return (
    <View testID="activity-block" className="gap-1">
      <RowList
        rows={before}
        live={live && lanes.length === 0 && after.length === 0}
      />
      {lanes.length > 0 ? (
        <View testID="lanes">
          {lanes.map((lane, i) => (
            <LaneView
              key={lane.id}
              lane={lane}
              rows={laneRows(lane.id)}
              number={i + 1}
            />
          ))}
        </View>
      ) : null}
      <RowList rows={after} live={live} />
      {live && !streamingText && !answering ? (
        <Text
          testID="run-status"
          accessibilityLiveRegion="polite"
          className="px-2 py-1 font-pixel text-xs text-muted-foreground"
        >
          {statusLabel(run)}…
        </Text>
      ) : null}
    </View>
  );
}
