/**
 * The scripted demos inside the landing page's feature cards.
 *
 * Each demo is a pure function of a tick counter from {@link useTicker}, so
 * the frames are deterministic and the loops pause off screen.
 * @module FeatureDemos
 */
"use client";

import { typed, useTicker } from "./useTicker";

const QUESTION = "Where does a repo get cloned, and what cleans it up?";

/** Search channels the agent fans out over, with the hits each one returns. */
const CHANNELS: [string, number][] = [
  ["dense", 12],
  ["lexical", 5],
  ["symbol", 3],
  ["grep", 4],
  ["graph", 6],
  ["co-change", 2],
  ["history", 1],
];

/** Files the agent reads, and the tick each one appears at. */
const READS: [string, string, number][] = [
  ["services/cloner.py", "clone_repository, cleanup_clone", 46],
  ["tasks/ingest.py", "ingest_repository", 51],
  ["services/repo_cache.py", "the persistent clone cache", 56],
];

const ASK_LOOP = 110;

/**
 * One row of the agent trace: a status square and a label.
 *
 * @param label The step name.
 * @param k The loop tick.
 * @param from The tick the step starts.
 * @param to The tick the step finishes.
 * @param aside Optional right-aligned text.
 * @returns The trace row heading.
 */
function TraceStep({
  label,
  k,
  from,
  to,
  aside,
}: {
  label: string;
  k: number;
  from: number;
  to: number;
  aside?: string;
}) {
  const done = k >= to;
  const on = k >= from && k < to;
  return (
    <div className="flex items-center gap-2.5">
      <span
        className={`h-2 w-2 ${on ? "blink" : ""}`}
        style={{ background: done ? "#00b8db" : on ? "#f6339a" : "#3f3f46" }}
      />
      <span
        className={`font-pixel text-sm ${done || on ? "text-(--foreground)" : "text-(--muted-foreground)"}`}
      >
        {label}
      </span>
      {aside && (
        <span className="ml-auto font-pixel text-xs text-(--muted-foreground)">
          {aside}
        </span>
      )}
    </div>
  );
}

/**
 * The "Ask the codebase" card: a question typed in, the agent's search and
 * read trace on the right, then a cited answer that is verified.
 *
 * @returns The chat demo.
 */
export function AskDemo() {
  const [ref, tick] = useTicker(100, ASK_LOOP - 1);
  const k = tick % ASK_LOOP;
  const verified = k >= 84;
  let hits = 0;
  const channels = CHANNELS.map(([name, n], i) => {
    const on = k >= 30 + i * 2;
    if (on) hits += n;
    return { name, n, on };
  });

  return (
    <div
      ref={ref}
      className="flex min-h-[430px] grow flex-col rounded-sm border border-white/8 bg-(--background)"
    >
      <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 bg-zinc-700" />
          <span className="h-2 w-2 bg-zinc-700" />
          <span className="h-2 w-2 bg-zinc-700" />
          <span className="ml-2.5 font-pixel text-xs text-(--muted-foreground)">
            illume / chat
          </span>
        </div>
        <span className="border border-[#00b8db66] px-2 py-0.5 font-pixel text-[11px] tracking-[0.1em] text-(--chart-1)">
          AGENT
        </span>
      </div>
      <div className="flex grow flex-wrap">
        <div className="flex min-w-0 flex-[1.5_1_300px] flex-col gap-3.5 p-5">
          <div className="max-w-[88%] self-end rounded-sm bg-[#1c1c21] px-4 py-3 font-pixel text-[15px] leading-normal">
            {typed(QUESTION, k)}
            {k < 27 && <span className="caret text-(--accent)">▌</span>}
          </div>
          {k >= 27 && k < 62 && (
            <div className="flex items-center gap-2.5 font-pixel text-[13px] text-(--chart-1)">
              <span className="blink h-2 w-2 bg-(--accent)" />
              {k < 46 ? "Searching 7 channels" : "Reading 3 files"}
            </div>
          )}
          {k >= 62 && (
            <p className="rise m-0 text-[15px] leading-relaxed text-zinc-300">
              <code className="font-pixel text-(--foreground)">
                clone_repository
              </code>{" "}
              in{" "}
              <code className="font-pixel text-(--foreground)">
                services/cloner.py
              </code>{" "}
              clones the repo into a cached or temporary directory{" "}
              <span className="font-pixel text-(--accent)">[1]</span>.
            </p>
          )}
          {k >= 67 && (
            <p className="rise m-0 text-[15px] leading-relaxed text-zinc-300">
              <code className="font-pixel text-(--foreground)">
                ingest_repository
              </code>{" "}
              calls{" "}
              <code className="font-pixel text-(--foreground)">
                cleanup_clone
              </code>{" "}
              in a{" "}
              <code className="font-pixel text-(--foreground)">finally</code>{" "}
              block, so the clone is removed whether the run succeeds or fails{" "}
              <span className="font-pixel text-(--accent)">[2]</span>.
            </p>
          )}
          {k >= 72 && (
            <div className="rise flex flex-col border-l-2 border-(--chart-2) bg-[#111114] px-3.5 py-2.5 font-pixel text-[13px] leading-relaxed">
              <span className="mb-1 text-[11px] tracking-[0.06em] text-(--muted-foreground)">
                server/app/tasks/ingest.py · L181–182
              </span>
              <span>
                <span className="text-(--accent)">finally</span>
                <span className="text-(--muted-foreground)">:</span>
              </span>
              <span className="pl-7">
                cleanup_clone
                <span className="text-(--muted-foreground)">(</span>
                <span className="text-(--chart-1)">tmp_dir</span>
                <span className="text-(--muted-foreground)">)</span>
              </span>
            </div>
          )}
          {k >= 78 && (
            <div className="rise mt-auto flex flex-wrap gap-2">
              {["services/cloner.py", "tasks/ingest.py"].map((path, i) => (
                <span
                  key={path}
                  className={`flex items-center gap-2 rounded-[3px] border px-3 py-1.5 font-pixel text-xs ${verified ? "border-(--accent)" : "border-(--input)"}`}
                >
                  {verified && <span className="text-(--accent)">✓</span>}
                  <span className="text-(--muted-foreground)">
                    [{i + 1}]
                  </span>{" "}
                  {path}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex min-w-0 flex-[1_1_230px] flex-col gap-4 border-l border-white/8 bg-[#0b0b0e] p-4.5">
          <span className="font-pixel text-[11px] tracking-[0.14em] text-(--muted-foreground)">
            TRACE
          </span>
          <div className="flex flex-col gap-1">
            <TraceStep label="Route" k={k} from={27} to={30} />
            <span className="pl-4.5 text-xs text-(--muted-foreground)">
              Agent mode, multi-file question
            </span>
          </div>
          <div className="flex flex-col gap-2">
            <TraceStep
              label="Search"
              k={k}
              from={30}
              to={46}
              aside={hits ? `${hits} hits` : ""}
            />
            <div className="flex flex-wrap gap-1 pl-4.5">
              {channels.map(({ name, n, on }) => (
                <span
                  key={name}
                  className={`border px-1.5 py-0.5 font-pixel text-[11px] ${on ? "border-(--chart-2) bg-[#003c4a] text-(--foreground)" : "border-(--muted) text-(--muted-foreground)"}`}
                >
                  {on ? `${name} ${n}` : name}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <TraceStep label="Read" k={k} from={46} to={62} />
            <div className="flex min-h-16.5 flex-col gap-1.5 pl-4.5">
              {READS.filter(([, , at]) => k >= at).map(([path, what]) => (
                <div key={path} className="rise flex flex-col gap-px">
                  <span className="font-pixel text-xs">{path}</span>
                  <span className="text-[11px] text-(--muted-foreground)">
                    {what}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <TraceStep label="Verify" k={k} from={62} to={84} />
            <span
              className={`pl-4.5 text-xs ${verified ? "text-(--accent)" : "text-(--muted-foreground)"}`}
            >
              {verified
                ? "2 of 2 citations supported"
                : k >= 62
                  ? "Checking each citation"
                  : "Waiting"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

const READING: [string, string][] = [
  ["server/app/core/config.py", "Settings every module reads"],
  ["server/app/models/repository.py", "The record everything hangs off"],
  ["server/app/services/scanner.py", "Walk, parse, persist"],
  ["server/app/tasks/ingest.py", "Where the pipeline runs"],
  ["server/app/api/v1/graph.py", "What the graph view draws"],
];

/**
 * The reading-order card: a five-file path with the current file highlighted
 * and the ones before it ticked off.
 *
 * @returns The reading-order demo.
 */
export function ReadingOrderDemo() {
  const [ref, k] = useTicker<HTMLOListElement>(100, 14 * 4);
  const idx = Math.floor(k / 14) % READING.length;
  return (
    <ol ref={ref} className="m-0 flex list-none flex-col gap-1 p-0">
      {READING.map(([path, note], i) => {
        const on = i === idx;
        const done = i < idx;
        return (
          <li
            key={path}
            className={`flex items-center gap-3.5 border-l-[3px] px-3 py-2.25 ${on ? "border-(--accent) bg-white/4" : "border-transparent"}`}
          >
            <span
              className={`w-5 font-pixel text-sm ${on ? "text-(--accent)" : "text-(--muted-foreground)"}`}
            >
              0{i + 1}
            </span>
            <span className="flex min-w-0 grow flex-col gap-px">
              <span
                className={`truncate font-pixel text-[13px] ${on ? "text-(--foreground)" : done ? "text-zinc-300" : "text-(--muted-foreground)"}`}
              >
                {path}
              </span>
              <span className="text-xs text-(--muted-foreground)">{note}</span>
            </span>
            <span className="font-pixel text-[13px] text-(--chart-2)">
              {done ? "✓" : ""}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

const STACK = ["FastAPI", "Celery", "Postgres", "Redis", "Next.js"];

/**
 * The architecture-brief card: stack badges arriving one by one over a
 * paragraph being written.
 *
 * @returns The brief demo.
 */
export function BriefDemo() {
  const [ref, k] = useTicker(100, 59);
  const shown = Math.floor((k % 60) / 7);
  return (
    <div
      ref={ref}
      className="flex grow flex-col gap-3.5 rounded-sm border border-white/8 bg-(--background) p-4.5"
    >
      <div className="flex min-h-6.5 flex-wrap gap-1.5">
        {STACK.map((label, i) => (
          <span
            key={label}
            className="border border-(--input) px-2.25 py-1 font-pixel text-xs text-zinc-200 transition-all duration-300 [transition-timing-function:steps(3)]"
            style={{
              opacity: i < shown ? 1 : 0,
              transform: i < shown ? "none" : "translateY(4px)",
            }}
          >
            {label}
          </span>
        ))}
      </div>
      <div aria-hidden="true" className="flex flex-col gap-2">
        <span className="line-fill h-2 w-[92%] bg-(--muted)" />
        <span className="line-fill h-2 w-[78%] bg-(--muted) [animation-delay:.4s]" />
        <span className="line-fill h-2 w-[86%] bg-(--muted) [animation-delay:.8s]" />
        <span className="line-fill h-2 w-[54%] bg-[#f6339a66] [animation-delay:1.2s]" />
      </div>
    </div>
  );
}

const TERMS: [string, string][] = [
  ["snapshot", "The branch plus the exact commit Illume read."],
  ["re-ingest", "Rebuild a repository from scratch, keeping its ID."],
  ["fan-in", "How many files import this one."],
  [
    "criticality",
    "How risky a file is to change, from its imports, churn and tests.",
  ],
];

/**
 * The glossary card: one term at a time, rotating.
 *
 * @returns The glossary demo.
 */
export function GlossaryDemo() {
  const [ref, k] = useTicker(100, 0);
  const [term, def] = TERMS[Math.floor(k / 24) % TERMS.length];
  return (
    <div
      ref={ref}
      className="flex min-h-30 grow flex-col justify-center gap-2 rounded-sm border border-white/8 bg-(--background) p-4.5"
    >
      <div key={term} className="rise flex flex-col gap-2">
        <span className="font-pixel text-[28px] text-(--chart-1)">{term}</span>
        <span className="text-sm leading-normal text-zinc-300">{def}</span>
      </div>
    </div>
  );
}

const MCP_LINES: { at: number; text: string; tone: string }[] = [
  { at: 3, text: "who calls into services/rag.py?", tone: "prompt" },
  { at: 14, text: '⏺ illume.ask(repo: "illume", question: …)', tone: "call" },
  {
    at: 24,
    text: "  ⎿ api/v1/chat.py imports answer_question [1]",
    tone: "out",
  },
  {
    at: 30,
    text: "  ⎿ mcp/ask.py wraps it for editor agents [2]",
    tone: "out",
  },
];

/**
 * The MCP card: an editor agent asking Illume a question and getting cited
 * results back.
 *
 * @returns The MCP demo.
 */
export function McpDemo() {
  const [ref, tick] = useTicker(100, 69);
  const k = tick % 70;
  return (
    <div
      ref={ref}
      className="flex flex-col gap-2.5 rounded-sm border border-white/8 bg-(--background) p-4.5 font-pixel text-[13px] leading-normal whitespace-pre"
    >
      {/* Every line is laid out from the start and the unrevealed ones stay
          invisible, so the card is its full height before the first one types in. */}
      {MCP_LINES.map((line) => (
        <span
          key={line.at}
          aria-hidden={k < line.at || undefined}
          className={`truncate ${k >= line.at ? "rise" : "invisible"} ${line.tone === "call" ? "text-(--chart-1)" : line.tone === "out" ? "text-zinc-300" : ""}`}
        >
          {line.tone === "prompt" && (
            <span className="text-(--accent)">&gt; </span>
          )}
          {line.text}
        </span>
      ))}
    </div>
  );
}
