/**
 * What an agent run did, shown inline above its answer.
 * @module ActivityBlock
 */
"use client";

import { decorateAnswer, keysFromHref, shortKeyLabel, trimPartialMarkup } from "@/lib/agent/answer";
import { laneColor } from "@/lib/agent/palette";
import { PRESET_DEFAULTS, type PresetId } from "@/lib/agent/presets";
import {
  type ActivityRow,
  type Lane,
  type PlanRow,
  type RouteRow,
  type RetrievalRow,
  type RunState,
  type ThinkingRow,
  type ToolRow,
} from "@/lib/agent/reducer";
import { readRange, shortArgs, statusLabel, toolLabel, type ShortArg } from "@/lib/agent/tools";
import {
  BookOpenTextIcon,
  BrainIcon,
  CaretDownIcon,
  CheckCircleIcon,
  ChatCircleDotsIcon,
  ClockCounterClockwiseIcon,
  DatabaseIcon,
  FileTextIcon,
  FlagCheckeredIcon,
  FolderOpenIcon,
  InfoIcon,
  ListChecksIcon,
  RobotIcon,
  SignpostIcon,
  MagnifyingGlassIcon,
  TerminalWindowIcon,
  TreeStructureIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type ComponentType, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CARET, PROSE } from "./AnswerView";

type IconType = ComponentType<{
  size?: number;
  weight?: "bold" | "regular" | "fill" | "duotone";
  className?: string;
}>;

const TOOL_ICONS: Record<string, IconType> = {
  search_code: MagnifyingGlassIcon,
  search_symbols: MagnifyingGlassIcon,
  grep_code: TerminalWindowIcon,
  search_history: ClockCounterClockwiseIcon,
  read_file: FileTextIcon,
  read_symbol: FileTextIcon,
  list_files: FolderOpenIcon,
  list_symbols: FolderOpenIcon,
  get_importers: TreeStructureIcon,
  get_importees: TreeStructureIcon,
  find_path: TreeStructureIcon,
  get_cochanged: TreeStructureIcon,
  get_file_info: InfoIcon,
  get_glossary: BookOpenTextIcon,
  get_overview: InfoIcon,
  finish: FlagCheckeredIcon,
};

function formatLatency(ms: number | null): string | null {
  if (ms == null) return null;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** Shared enter animation: a short fade and rise, a plain fade when motion is reduced. */
function useEnter(index = 0) {
  const reduced = useReducedMotion();
  return reduced
    ? { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: 0.15 } }
    : {
        initial: { opacity: 0, y: 6 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.22, delay: Math.min(index, 6) * 0.03 },
      };
}

/** Renders one tool argument in its short form. */
function ArgView({ arg }: { arg: ShortArg }) {
  if (arg.kind === "pattern") {
    return (
      <code className="min-w-0 truncate rounded bg-(--secondary)/70 px-1.5 py-0.5 font-mono text-[11px] text-(--foreground)">
        {arg.value}
      </code>
    );
  }
  if (arg.kind === "path") {
    return (
      <span
        className="inline-flex min-w-0 items-center gap-1 rounded-full border border-(--border) bg-(--secondary)/40 px-2 py-0.5 font-mono text-[11px]"
        title={arg.extra ? `${arg.value} ${arg.extra}` : arg.value}
      >
        <span className="min-w-0 truncate">{arg.value}</span>
        {arg.extra && (
          <span className="shrink-0 whitespace-nowrap text-(--muted-foreground)">
            {arg.extra}
          </span>
        )}
      </span>
    );
  }
  if (arg.kind === "query") {
    return (
      <span className="min-w-0 truncate text-xs text-(--foreground)/90" title={arg.value}>
        &ldquo;{arg.value}&rdquo;
      </span>
    );
  }
  return (
    <span className="min-w-0 truncate text-xs text-(--foreground)/90" title={arg.value}>
      {arg.value}
    </span>
  );
}

interface OutputPart {
  key: string | null;
  text: string;
}

const SOURCE_BLOCK = /<source key="([^"]*)"[^>]*>\n?([\s\S]*?)\n?<\/source>/g;

/**
 * Splits a tool's output into the sources it found and the text between them.
 *
 * @param text - The output as the tool returned it.
 * @returns Each source under its key, and loose text with no key.
 */
export function splitOutput(text: string): OutputPart[] {
  const parts: OutputPart[] = [];
  let last = 0;
  for (const match of text.matchAll(SOURCE_BLOCK)) {
    const index = match.index ?? 0;
    const between = text.slice(last, index).trim();
    if (between) parts.push({ key: null, text: between });
    parts.push({
      key: match[1].replace(/&quot;/g, '"').replace(/&lt;/g, "<"),
      text: match[2],
    });
    last = index + match[0].length;
  }
  const rest = text.slice(last).trim();
  if (rest) parts.push({ key: null, text: rest });
  return parts;
}

/** What a tool returned, each source it found under its own label. */
function ToolOutput({ text }: { text: string }) {
  return (
    <div
      className="max-h-80 space-y-2 overflow-y-auto custom-scrollbar pr-1"
      data-testid="tool-output"
    >
      {splitOutput(text).map((part, i) => (
        <div key={i} className="min-w-0">
          {part.key && (
            <p
              className="mb-0.5 truncate font-mono text-[10px] text-(--chart-1)"
              title={part.key}
            >
              {shortKeyLabel(part.key)}
            </p>
          )}
          <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[10.5px] leading-relaxed text-(--muted-foreground)">
            {part.text}
          </pre>
        </div>
      ))}
    </div>
  );
}

/** One tool call; opens to show what it returned. */
function ToolRowView({ row, index }: { row: ToolRow; index: number }) {
  const [open, setOpen] = useState(false);
  const enter = useEnter(index);
  const Icon = TOOL_ICONS[row.tool] ?? MagnifyingGlassIcon;
  const args = shortArgs(row.tool, row.parsed);
  const range = row.tool === "read_file" ? readRange(row) : null;
  const latency = formatLatency(row.latencyMs);
  const expandable =
    row.status !== "running" &&
    (Boolean(row.output) || row.paths.length > 0 || Boolean(row.summary));

  const state =
    row.status === "running" ? (
      <span
        className="inline-block h-1.5 w-1.5 rounded-full bg-(--chart-1) animate-pulse"
        aria-label="running"
      />
    ) : row.status === "error" ? (
      <XCircleIcon size={13} weight="fill" className="text-red-400" />
    ) : (
      <CheckCircleIcon size={13} weight="fill" className="text-(--success)" />
    );

  return (
    <motion.li {...enter} data-row="tool" data-tool={row.tool} className="@container">
      <button
        type="button"
        disabled={!expandable}
        aria-expanded={expandable ? open : undefined}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--secondary)/30 disabled:cursor-default disabled:hover:bg-transparent cursor-pointer"
      >
        <Icon size={14} className="shrink-0 text-(--muted-foreground)" weight="bold" />
        <span className="shrink-0 text-xs font-medium text-(--foreground)">
          {toolLabel(row.tool)}
        </span>
        <span className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
          {args.map((arg, i) => (
            <ArgView key={i} arg={arg} />
          ))}
        </span>
        <span className="flex shrink-0 items-center gap-2 whitespace-nowrap text-[11px] text-(--muted-foreground)">
          {row.resultCount != null && row.status === "ok" && row.tool !== "finish" && (
            <span>{row.resultCount} found</span>
          )}
          {latency && <span className="hidden @[22rem]:inline">{latency}</span>}
          {state}
          {expandable && (
            <CaretDownIcon
              size={12}
              className={`transition-transform ${open ? "rotate-180" : ""}`}
            />
          )}
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <div className="mx-2 mb-1 ml-8 space-y-1.5 rounded-md bg-(--background)/40 p-2 text-[11px]">
              {range && row.paths[0] && (
                <p className="font-mono text-(--muted-foreground)">
                  {row.paths[0]} · {range}
                </p>
              )}
              {row.output ? (
                <ToolOutput text={row.output} />
              ) : (
                <>
                  {row.summary && <p className="text-(--muted-foreground)">{row.summary}</p>}
                  {row.paths.length > 0 && row.tool !== "read_file" && (
                    <ul className="space-y-0.5" aria-label="Matched files">
                      {row.paths.slice(0, 12).map((path) => (
                        <li key={path} className="truncate font-mono text-(--foreground)/85">
                          {path}
                        </li>
                      ))}
                      {row.paths.length > 12 && (
                        <li className="text-(--muted-foreground)">
                          and {row.paths.length - 12} more
                        </li>
                      )}
                    </ul>
                  )}
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}

/** A caret that turns when its section opens. */
function Caret({ open }: { open: boolean }) {
  return (
    <CaretDownIcon
      size={12}
      className={`ml-auto shrink-0 text-(--muted-foreground) transition-transform ${open ? "rotate-180" : ""}`}
    />
  );
}

/** Opens and closes its body with a short height animation. */
function Fold({ open, children }: { open: boolean; children: ReactNode }) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="overflow-hidden"
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** A coloured, icon-led row for the non-tool steps. */
function NoteRow({
  icon: Icon,
  tone,
  index,
  kind,
  children,
}: {
  icon: IconType;
  tone: string;
  index: number;
  kind: string;
  children: ReactNode;
}) {
  const enter = useEnter(index);
  return (
    <motion.li
      {...enter}
      data-row={kind}
      className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs"
    >
      <Icon size={14} weight="bold" className={`mt-0.5 shrink-0 ${tone}`} />
      <div className="min-w-0 flex-1">{children}</div>
    </motion.li>
  );
}

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
  return parts.join(" \u00b7 ");
}

function RouteRowView({ row, index }: { row: RouteRow; index: number }) {
  return (
    <NoteRow icon={SignpostIcon} tone="text-(--chart-1)" index={index} kind="route">
      <span className="font-medium">{routeSummary(row)}</span>
    </NoteRow>
  );
}

function PlanRowView({ row, index }: { row: PlanRow; index: number }) {
  return (
    <NoteRow icon={ListChecksIcon} tone="text-(--chart-2)" index={index} kind="plan">
      {/* Each part's question heads its own lane just below. */}
      <span className="font-medium">
        Split into {row.subquestions.length} parts, worked on in parallel
      </span>
    </NoteRow>
  );
}

const QUERY_KINDS: Record<string, string> = {
  original: "Question",
  condensed: "Rewritten with the conversation",
  multi_query: "Rewrite",
  hyde: "Hypothetical code",
};

const RETRIEVED_SHOWN = 20;

/** A search of the index; opens to the queries it ran and what it kept. */
function RetrievalRowView({ row, index }: { row: RetrievalRow; index: number }) {
  const [open, setOpen] = useState(false);
  const enter = useEnter(index);
  const channels = Object.entries(row.channels).filter(([, count]) => count > 0);
  const expandable = row.queries.length > 0 || channels.length > 0 || row.keys.length > 0;

  return (
    <motion.li {...enter} data-row="retrieval" className="text-xs">
      <button
        type="button"
        disabled={!expandable}
        aria-expanded={expandable ? open : undefined}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--secondary)/30 disabled:cursor-default disabled:hover:bg-transparent cursor-pointer"
      >
        <DatabaseIcon size={14} weight="bold" className="shrink-0 text-(--muted-foreground)" />
        <span className="font-medium text-(--foreground)">Searched the codebase</span>
        <span className="text-(--muted-foreground)">
          {row.queries.length > 1 && `${row.queries.length} queries · `}
          {row.kept} {row.kept === 1 ? "result" : "results"}
        </span>
        {expandable && <Caret open={open} />}
      </button>
      <Fold open={open}>
        <div
          className="mx-2 mb-1 ml-8 space-y-3 rounded-md bg-(--background)/40 p-2.5 text-[11px]"
          data-testid="retrieval-details"
        >
          {row.queries.length > 0 && (
            <section>
              <h5 className="mb-1 font-medium text-(--muted-foreground)">Queries</h5>
              <ol className="space-y-1">
                {row.queries.map((query, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="w-28 shrink-0 text-(--muted-foreground)">
                      {QUERY_KINDS[query.kind] ?? query.kind}
                    </span>
                    <span
                      className={`min-w-0 flex-1 whitespace-pre-wrap break-words text-(--foreground)/90 ${query.kind === "hyde" ? "font-mono text-[10.5px]" : ""}`}
                    >
                      {query.text}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          )}
          {channels.length > 0 && (
            <section>
              <h5 className="mb-1 font-medium text-(--muted-foreground)">Candidates per search</h5>
              <ul className="flex flex-wrap gap-1.5">
                {channels.map(([channel, count]) => (
                  <li
                    key={channel}
                    className="rounded-full border border-(--border) bg-(--secondary)/40 px-2 py-0.5"
                  >
                    {channel} <span className="text-(--muted-foreground)">{count}</span>
                  </li>
                ))}
                {row.reranker && row.reranker !== "none" && (
                  <li className="rounded-full border border-(--border) px-2 py-0.5 text-(--muted-foreground)">
                    reranked by {row.reranker}
                  </li>
                )}
              </ul>
            </section>
          )}
          {row.keys.length > 0 && (
            <section>
              <h5 className="mb-1 font-medium text-(--muted-foreground)">Kept</h5>
              <ol className="space-y-0.5">
                {row.keys.slice(0, RETRIEVED_SHOWN).map((key) => (
                  <li key={key} className="truncate font-mono text-(--foreground)/85" title={key}>
                    {shortKeyLabel(key)}
                  </li>
                ))}
                {row.keys.length > RETRIEVED_SHOWN && (
                  <li className="text-(--muted-foreground)">
                    and {row.keys.length - RETRIEVED_SHOWN} more
                  </li>
                )}
              </ol>
            </section>
          )}
        </div>
      </Fold>
    </motion.li>
  );
}

/** Narration longer than this is a draft or an explanation, and folds once written. */
const SHORT_NARRATION = 280;

const markdownComponents = {
  a({ href, children }: { href?: string; children?: ReactNode }) {
    const keys = keysFromHref(href);
    if (keys) {
      return (
        <span className="text-[0.8em] text-(--muted-foreground)">
          [{keys.map(shortKeyLabel).join(", ")}]
        </span>
      );
    }
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
};

/** Model text set the way the answer is, with citations as quiet labels. */
function StreamedMarkdown({ text, live }: { text: string; live: boolean }) {
  const markdown = useMemo(
    () => decorateAnswer(live ? trimPartialMarkup(text) : text),
    [text, live],
  );
  return (
    <div className={`${PROSE} ${live ? CARET : ""}`} data-testid="streamed-text">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

/** Keeps a scrolling box pinned to its newest line while text streams in. */
function useFollow(active: boolean, text: string) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [active, text]);
  return ref;
}

/**
 * What the model said or thought between tool calls.
 *
 * Both stream in full while they are being written. Short narration stays as
 * it is; reasoning and longer text fold away once the next step starts, and
 * open again on a click.
 */
function ThinkingRowView({
  row,
  index,
  live,
}: {
  row: ThinkingRow;
  index: number;
  live: boolean;
}) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const enter = useEnter(index);
  const text = row.text.trim();
  const reasoning = row.mode === "reasoning";
  const follow = useFollow(live, text);
  if (!text) return null;

  if (!reasoning && text.length <= SHORT_NARRATION && !text.includes("\n\n")) {
    return (
      <NoteRow icon={ChatCircleDotsIcon} tone="text-(--chart-1)" index={index} kind="thinking">
        <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-(--foreground)/85">
          {text}
        </p>
      </NoteRow>
    );
  }

  const open = userOpen ?? live;
  const Icon = reasoning ? BrainIcon : ChatCircleDotsIcon;
  const label = reasoning ? (live ? "Thinking" : "Thought") : live ? "Writing" : "Wrote";
  const preview = text.replace(/\s+/g, " ").slice(0, 140);

  return (
    <motion.li
      {...enter}
      data-row={reasoning ? "reasoning" : "thinking"}
      data-open={open}
      className="rounded-md px-2 py-1.5 text-xs"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setUserOpen(!open)}
        className="flex w-full min-w-0 items-center gap-2 text-left cursor-pointer"
      >
        <Icon
          size={14}
          weight="bold"
          className={`shrink-0 ${reasoning ? "text-(--chart-2)" : "text-(--chart-1)"}`}
        />
        <span
          className={`shrink-0 font-medium ${live ? "bg-linear-to-r from-(--muted-foreground) via-(--foreground) to-(--muted-foreground) bg-clip-text text-transparent animate-shimmer" : "text-(--foreground)"}`}
        >
          {label}
        </span>
        {!open && (
          <span className="min-w-0 truncate text-(--muted-foreground)">{preview}</span>
        )}
        <Caret open={open} />
      </button>
      <Fold open={open}>
        <div
          ref={follow}
          className="mt-1.5 ml-5.5 max-h-96 overflow-y-auto custom-scrollbar pr-1"
        >
          {reasoning ? (
            <p
              className={`whitespace-pre-wrap text-[13px] italic leading-relaxed text-(--muted-foreground) ${live ? CARET : ""}`}
            >
              {text}
            </p>
          ) : (
            <StreamedMarkdown text={text} live={live} />
          )}
        </div>
      </Fold>
    </motion.li>
  );
}

function RowView({ row, index, live }: { row: ActivityRow; index: number; live: boolean }) {
  switch (row.kind) {
    case "tool":
      return <ToolRowView row={row} index={index} />;
    case "route":
      return <RouteRowView row={row} index={index} />;
    case "plan":
      return <PlanRowView row={row} index={index} />;
    case "retrieval":
      return <RetrievalRowView row={row} index={index} />;
    case "thinking":
      return <ThinkingRowView row={row} index={index} live={live} />;
  }
}

/** Rows in order; only the last can still be live. */
function RowList({ rows, live }: { rows: ActivityRow[]; live: boolean }) {
  if (rows.length === 0) return null;
  return (
    <ul className="space-y-0.5">
      {rows.map((row, i) => (
        <RowView key={row.id} row={row} index={i} live={live && i === rows.length - 1} />
      ))}
    </ul>
  );
}

/** What a running worker is doing, from its latest step. */
function laneActivity(rows: ActivityRow[]): string | null {
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
 * One worker, drawn like a tool call: a single row in its lane colour with its
 * sub-question, what it is doing or what it did, and a status mark. Closed by
 * default; opening it shows the worker's own steps in a fixed-height box that
 * follows the newest step while the worker runs.
 */
function LaneView({ lane, rows, index }: { lane: Lane; rows: ActivityRow[]; index: number }) {
  const [open, setOpen] = useState(false);
  const enter = useEnter(index);
  const box = useRef<HTMLDivElement>(null);
  const color = laneColor(lane.colorIndex);
  const running = lane.status === "running" || lane.status === "pending";
  const tools = rows.filter((row) => row.kind === "tool").length;
  const files = new Set(rows.flatMap((row) => (row.kind === "tool" ? row.paths : []))).size;
  const detail = running
    ? laneActivity(rows)
    : [
        lane.status === "failed" && "Stopped",
        tools > 0 && `${tools} ${tools === 1 ? "tool call" : "tool calls"}`,
        files > 0 && `${files} ${files === 1 ? "file" : "files"}`,
      ]
        .filter(Boolean)
        .join(" · ");

  useEffect(() => {
    if (open && running && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [open, running, rows]);

  const mark = running ? (
    <span
      className="inline-block h-1.5 w-1.5 rounded-full animate-pulse"
      style={{ backgroundColor: color }}
      aria-label="running"
    />
  ) : lane.status === "failed" ? (
    <XCircleIcon size={13} weight="fill" className="text-red-400" />
  ) : (
    <CheckCircleIcon size={13} weight="fill" className="text-(--success)" />
  );

  return (
    <motion.li
      {...enter}
      data-lane={lane.id}
      data-open={open}
      aria-label={`Worker ${lane.id}: ${lane.question}`}
      className="@container"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md border-l-2 px-2 py-1.5 text-left hover:bg-(--secondary)/30 cursor-pointer"
        style={{ borderLeftColor: color }}
      >
        <RobotIcon size={14} weight="bold" className="shrink-0" style={{ color }} />
        <span className="shrink-0 text-xs font-medium text-(--foreground)">
          Subagent
        </span>
        <span className="min-w-0 flex-1 truncate text-xs text-(--foreground)/90" title={lane.question}>
          {lane.question || lane.id}
        </span>
        <span className="flex shrink-0 items-center gap-2 whitespace-nowrap text-[11px] text-(--muted-foreground)">
          {detail && (
            <span className="hidden max-w-[16rem] truncate @[30rem]:inline" title={detail}>
              {detail}
            </span>
          )}
          {mark}
          <CaretDownIcon size={12} className={`transition-transform ${open ? "rotate-180" : ""}`} />
        </span>
      </button>
      <Fold open={open}>
        <div
          ref={box}
          className="mx-2 mb-1 ml-4 max-h-72 overflow-y-auto custom-scrollbar rounded-md border-l-2 bg-(--background)/40 py-1 pl-1 pr-1"
          style={{ borderLeftColor: `${color}66` }}
          data-testid="lane-steps"
        >
          {rows.length > 0 ? (
            <RowList rows={rows} live={lane.status === "running"} />
          ) : (
            <p className="px-2 py-1 text-xs text-(--muted-foreground)">
              {running ? "Starting…" : "No steps recorded."}
            </p>
          )}
        </div>
      </Fold>
    </motion.li>
  );
}

/** A small pulsing trio of dots. */
function Dots() {
  const reduced = useReducedMotion();
  return (
    <span className="inline-flex items-center gap-0.5" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-(--chart-1)"
          animate={reduced ? undefined : { opacity: [0.25, 1, 0.25], scale: [0.8, 1.1, 0.8] }}
          transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.18 }}
        />
      ))}
    </span>
  );
}

/**
 * The steps of an agent run, inline in the message: tool calls, searches,
 * narration and reasoning, in the order they happened. While the run is live a
 * status line under the last step says what it is doing.
 *
 * @param run - The run state to show.
 * @returns The steps, or null when the run recorded none and is not live.
 */
export default function ActivityBlock({ run }: { run: RunState }) {
  const live = run.status === "connecting" || run.status === "live";
  if (run.rows.length === 0 && !live) return null;

  const laneRows = (laneId: string) => run.rows.filter((row) => row.laneId === laneId);
  const firstLaneIndex = run.rows.findIndex((row) => row.laneId !== null);
  const before =
    firstLaneIndex === -1
      ? run.rows
      : run.rows.slice(0, firstLaneIndex).filter((r) => r.laneId === null);
  const after =
    firstLaneIndex === -1 ? [] : run.rows.slice(firstLaneIndex).filter((r) => r.laneId === null);
  const lanes = run.laneOrder.map((id) => run.lanes[id]);
  const last = run.rows[run.rows.length - 1];
  // Streaming text says what is happening on its own; a status line under it is noise.
  const streamingText = live && last?.kind === "thinking";
  const answering = run.answer.length > 0;

  return (
    <div className="space-y-2" data-testid="activity-block">
      <RowList rows={before} live={live && lanes.length === 0 && after.length === 0} />
      {lanes.length > 0 && (
        <ul className="space-y-0.5" data-testid="lanes">
          {lanes.map((lane, i) => (
            <LaneView key={lane.id} lane={lane} rows={laneRows(lane.id)} index={i} />
          ))}
        </ul>
      )}
      <RowList rows={after} live={live} />
      {live && !streamingText && !answering && (
        <p
          className="flex items-center gap-2.5 px-2 py-1 text-xs"
          aria-live="polite"
          data-testid="run-status"
        >
          <Dots />
          <span className="bg-linear-to-r from-(--muted-foreground) via-(--foreground) to-(--muted-foreground) bg-clip-text text-transparent animate-shimmer">
            {statusLabel(run)}…
          </span>
        </p>
      )}
    </div>
  );
}
