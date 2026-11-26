/**
 * The landing page's four-step "how it works" walkthrough.
 * @module HowItWorks
 */
"use client";

import { useState } from "react";
import { typed, useTicker } from "./useTicker";

const STEPS: { title: string; desc: string; facts: string[] }[] = [
  {
    title: "Paste a link",
    desc: "Any GitHub repository you can reach, public or private.",
    facts: [
      "Public repositories, or private ones through your GitHub login",
      "Pick a branch or pin an exact commit",
      "Nothing to install and no config files",
    ],
  },
  {
    title: "Illume reads it",
    desc: "Clone, parse, resolve imports and mine the history.",
    facts: [
      "Clones the repository and parses 13 languages with tree-sitter",
      "Resolves every import into a dependency edge",
      "Mines up to 500 commits and 200 merged pull requests",
    ],
  },
  {
    title: "It builds your guide",
    desc: "Graph, risk scores, reading order, glossary and brief.",
    facts: [
      "Scores how risky each file is to change",
      "Orders a reading path from the foundations up",
      "Writes the glossary and the architecture brief, then indexes it all for search",
    ],
  },
  {
    title: "Ask, and stay current",
    desc: "Explore, ask questions, and let it follow main.",
    facts: [
      "Fly through the 3D graph or ask the chat",
      "Use it from your editor over MCP",
      "Auto-update keeps it in step with main",
    ],
  },
];

/** Ticks each step plays for before the walkthrough moves on. */
const STEP_TICKS = 40;

const REPO = "acme/payments-api";
const BRANCHES = ["main", "release/2.4", "feat/ledger"];

const INGEST_LOG: [string, string, number][] = [
  ["clone", "done", 0],
  ["parse", "1,284 files", 6],
  ["resolve imports", "3,902 edges", 13],
  ["git history", "500 commits", 20],
  ["pull requests", "200 merged", 27],
];

const ARTEFACTS: [string, number][] = [
  ["Dependency graph", 6],
  ["Risk scores", 12],
  ["Reading order", 18],
  ["Glossary", 24],
  ["Architecture brief", 30],
  ["Search index", 35],
];

const OUTPUTS: [string, string, number][] = [
  ["Graph", "3D, every file", 4],
  ["Chat", "Answers with sources", 10],
  ["Editor", "Over MCP", 16],
];

/** A fixed shuffle of the 96 mosaic cells, so they fill in a scattered order. */
const CELL_ORDER = Array.from({ length: 96 }, (_, i) => (i * 37) % 96);

/**
 * Step one's visual: the URL typed in, a branch picked, then Ingest.
 *
 * @param p Ticks into the step.
 * @returns The link-pasting frame.
 */
function PasteFrame({ p }: { p: number }) {
  return (
    <div className="flex w-full max-w-[540px] flex-col gap-4">
      <span className="eyebrow">Repository</span>
      <div
        className={`border bg-(--card) px-4.5 py-4 font-pixel text-lg ${p >= REPO.length ? "border-(--chart-2)" : "border-(--input)"}`}
      >
        <span className="text-(--muted-foreground)">github.com/</span>
        {typed(REPO, p, 1)}
        <span className="caret text-(--accent)">▌</span>
      </div>
      {p >= 18 && (
        <div className="rise flex flex-col gap-2.5">
          <span className="eyebrow">Branch or commit</span>
          <div className="flex flex-wrap gap-2">
            {BRANCHES.map((b, i) => {
              const sel = i === 0 && p >= 24;
              return (
                <span
                  key={b}
                  className={`border px-3 py-2 font-pixel text-[13px] ${sel ? "border-(--accent) bg-(--accent)/8 text-(--foreground)" : "border-(--input) text-zinc-300"}`}
                >
                  {sel ? "✓ " : ""}
                  {b}
                </span>
              );
            })}
          </div>
        </div>
      )}
      {p >= 28 && (
        <div className="rise flex items-center gap-3 border-l-2 border-(--chart-2) bg-[#111114] px-3 py-2.5 font-pixel text-[13px]">
          <span className="text-(--muted-foreground)">a3f9c1</span>
          <span className="grow">fix: resolve imports with extensions</span>
          <span className="text-(--chart-1)">HEAD</span>
        </div>
      )}
      {p >= 33 && (
        <span className="rise self-start bg-(--primary) px-5.5 py-3 font-pixel text-[15px] tracking-[0.04em] text-(--primary-foreground)">
          Ingest →
        </span>
      )}
    </div>
  );
}

/**
 * Step two's visual: the ingest log filling stage by stage.
 *
 * @param p Ticks into the step.
 * @returns The reading frame.
 */
function ReadFrame({ p }: { p: number }) {
  return (
    <div className="flex w-full max-w-[560px] flex-col gap-3.5">
      <span className="eyebrow">Ingest · {REPO} @ main</span>
      {INGEST_LOG.map(([name, meta, at]) => {
        const w = Math.round(Math.max(0, Math.min(1, (p - at) / 8)) * 10) / 10;
        const done = w >= 1;
        return (
          <div key={name} className="flex items-center gap-3.5">
            <span
              className={`w-34 shrink-0 font-pixel text-sm ${w > 0 ? "text-(--foreground)" : "text-(--muted-foreground)"}`}
            >
              {name}
            </span>
            <span className="h-2.5 grow bg-(--secondary)">
              <span
                className="block h-2.5"
                style={{
                  width: `${w * 100}%`,
                  background: done ? "#00b8db" : "#f6339a",
                }}
              />
            </span>
            <span
              className={`w-27.5 shrink-0 text-right font-pixel text-xs ${done ? "text-(--chart-1)" : w > 0 ? "text-(--accent)" : "text-(--muted-foreground)"}`}
            >
              {done ? meta : w > 0 ? "running" : "queued"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const MOSAIC_COLORS = ["#f6339a", "#53eafd", "#0092b8", "#00b8db"];

/**
 * Step three's visual: a mosaic filling in beside the artefacts it produces.
 *
 * @param p Ticks into the step.
 * @returns The building frame.
 */
function BuildFrame({ p }: { p: number }) {
  const filled = p * 3;
  return (
    <div className="flex w-full max-w-[580px] flex-wrap items-center gap-7">
      <div
        aria-hidden="true"
        className="grid min-w-0 flex-[1_1_260px] grid-cols-12 gap-[3px]"
      >
        {CELL_ORDER.map((order, i) => {
          let color = "#18181b";
          if (order < filled) {
            color =
              i % 11 === 0
                ? MOSAIC_COLORS[0]
                : i % 5 === 0
                  ? MOSAIC_COLORS[1]
                  : i % 3 === 0
                    ? MOSAIC_COLORS[2]
                    : MOSAIC_COLORS[3];
          }
          return (
            <span key={i} className="aspect-square" style={{ background: color }} />
          );
        })}
      </div>
      <ul className="m-0 flex flex-[1_1_200px] list-none flex-col gap-2.5 p-0">
        {ARTEFACTS.map(([label, at]) => {
          const ok = p >= at;
          return (
            <li
              key={label}
              className={`flex items-center gap-3 font-pixel text-[15px] ${ok ? "text-(--foreground)" : "text-(--muted-foreground)"}`}
            >
              <span
                className={`w-3.5 ${ok ? "text-(--chart-2)" : "text-(--faint-foreground)"}`}
              >
                {ok ? "✓" : "·"}
              </span>
              {label}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * Step four's visual: the three ways in, lighting up in turn.
 *
 * @param p Ticks into the step.
 * @returns The ready frame.
 */
function ReadyFrame({ p }: { p: number }) {
  return (
    <div className="flex w-full max-w-[560px] flex-col gap-4.5">
      <div className="grid grid-cols-3 gap-3">
        {OUTPUTS.map(([title, sub, at]) => {
          const on = p >= at;
          return (
            <div
              key={title}
              className={`flex flex-col gap-2 border p-4.5 ${on ? "border-(--chart-2) bg-[#003c4a40]" : "border-(--border)"}`}
            >
              <span
                className={`font-pixel text-[22px] ${on ? "text-(--foreground)" : "text-(--muted-foreground)"}`}
              >
                {title}
              </span>
              <span className="text-[13px] text-(--muted-foreground)">{sub}</span>
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-2.5 font-pixel text-sm text-zinc-300">
        <span className="blink h-2 w-2 bg-(--chart-1)" />
        Ready · auto-update follows main
      </div>
    </div>
  );
}

/**
 * Renders the progress rail, the four step buttons and the active step's
 * detail panel. It plays on its own; picking a step jumps the loop there.
 *
 * @returns The walkthrough.
 */
export default function HowItWorks() {
  const [ref, tick] = useTicker(100, STEPS.length * STEP_TICKS - 1);
  const [offset, setOffset] = useState(0);
  const loop = STEPS.length * STEP_TICKS;
  const k = (((tick + offset) % loop) + loop) % loop;
  const step = Math.floor(k / STEP_TICKS);
  const p = k % STEP_TICKS;
  const rail = Math.min(100, ((step + p / STEP_TICKS) / STEPS.length) * 100);

  /**
   * Jumps the loop to the start of a step.
   *
   * @param i The step index.
   */
  const pick = (i: number) => {
    const base = tick % loop;
    setOffset(i * STEP_TICKS - base);
  };

  const current = STEPS[step];

  return (
    <div ref={ref} className="flex flex-col gap-12">
      <div className="flex flex-col gap-4.5">
        <div aria-hidden="true" className="relative h-3">
          <span className="absolute inset-x-0 top-1.25 h-0.5 bg-(--muted)" />
          <span
            className="absolute top-1.25 left-0 h-0.5 bg-(--chart-2)"
            style={{ width: `${rail}%` }}
          />
          <span
            className="absolute top-0 h-3 w-3 bg-(--accent) shadow-[0_0_14px_#f6339a]"
            style={{ left: `calc(${rail}% - 6px)` }}
          />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => {
            const on = i === step;
            const done = i < step;
            return (
              <button
                key={s.title}
                type="button"
                onClick={() => pick(i)}
                aria-pressed={on}
                className={`flex flex-col gap-2.5 rounded-md border p-5.5 text-left hover:cursor-pointer ${on ? "border-(--accent) bg-(--accent)/5" : done ? "border-[#00b8db66] bg-(--card)" : "border-(--border) bg-(--card)"}`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span
                    className={`font-pixel text-[40px] leading-none ${on ? "text-(--accent)" : done ? "text-(--chart-2)" : "text-(--faint-foreground)"}`}
                  >
                    0{i + 1}
                  </span>
                  <span
                    className={`font-pixel text-[11px] tracking-[0.12em] ${on ? "text-(--accent)" : done ? "text-(--chart-2)" : "text-(--muted-foreground)"}`}
                  >
                    {done ? "DONE" : on ? "RUNNING" : "QUEUED"}
                  </span>
                </span>
                <span className="font-pixel text-[22px]">{s.title}</span>
                <span className="text-sm leading-normal text-zinc-400">
                  {s.desc}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex min-h-95 flex-wrap overflow-hidden rounded-md border border-(--border) bg-(--card)">
        <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-4.5 border-white/8 p-6 sm:p-9 md:border-r">
          <p className="m-0 font-pixel text-[13px] tracking-[0.12em] text-(--accent)">
            STEP 0{step + 1} / 04
          </p>
          <h3 className="m-0 font-pixel text-[32px] leading-tight">
            {current.title}
          </h3>
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {current.facts.map((fact) => (
              <li
                key={fact}
                className="rise flex items-start gap-3 text-[15px] leading-normal text-zinc-300"
              >
                <span className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-(--chart-2)" />
                {fact}
              </li>
            ))}
          </ul>
        </div>
        <div
          aria-hidden="true"
          className="flex min-w-0 flex-[1.6_1_440px] items-center justify-center bg-(--background) p-6 sm:p-9"
        >
          {step === 0 && <PasteFrame p={p} />}
          {step === 1 && <ReadFrame p={p} />}
          {step === 2 && <BuildFrame p={p} />}
          {step === 3 && <ReadyFrame p={p} />}
        </div>
      </div>
    </div>
  );
}
