/**
 * The landing page's walkthrough video, FAQ and closing call to action.
 * @module LandingExtras
 */
"use client";

import Link from "next/link";
import { useState } from "react";
import { typed, useTicker } from "./useTicker";

const VIDEO_ID = "ZKjFKBAj89g";
const VIDEO_LENGTH_S = 300;

/** Chapter start times in seconds, with their labels. */
const CHAPTERS: [number, string][] = [
  [0, "Paste a repo and ingest"],
  [40, "The 3D dependency graph"],
  [90, "Reading order and the brief"],
  [140, "Ask the codebase"],
  [200, "Glossary and who to ask"],
  [250, "MCP in your editor"],
];

/**
 * Formats seconds as `m:ss`.
 *
 * @param s Seconds.
 * @returns The timestamp.
 */
function stamp(s: number): string {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r < 10 ? "0" : ""}${r}`;
}

/**
 * The walkthrough player with its chapter list.
 *
 * The YouTube embed is not loaded until the visitor presses play, so the page
 * makes no request to YouTube on load; it uses the no-cookie domain when it
 * does. Until then a poster cycles through the chapters to show what is in it.
 *
 * @returns The tour block.
 */
export function Tour() {
  const [ref, k] = useTicker(100, 0);
  const [start, setStart] = useState<number | null>(null);
  const active = Math.floor((k % 60) / 10);
  const scanY = (k * 3) % 100;
  const pulse = k % 10 < 5;

  return (
    <div
      ref={ref}
      className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]"
    >
      <div className="relative aspect-video min-w-0 overflow-hidden rounded-md border border-(--border) bg-(--background)">
        {start !== null ? (
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${VIDEO_ID}?autoplay=1&rel=0&start=${start}`}
            title="Illume walkthrough"
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            className="absolute inset-0 h-full w-full border-0"
          />
        ) : (
          <button
            type="button"
            onClick={() => setStart(0)}
            aria-label="Play the five-minute walkthrough"
            className="absolute inset-0 h-full w-full bg-[radial-gradient(ellipse_at_50%_45%,#0092b826,transparent_60%),#09090b] hover:cursor-pointer"
          >
            <span
              aria-hidden="true"
              className="absolute inset-0 bg-[linear-gradient(#ffffff08_1px,transparent_1px),linear-gradient(90deg,#ffffff08_1px,transparent_1px)] bg-size-[16px_16px]"
            />
            <span
              aria-hidden="true"
              className="absolute inset-x-0 h-0.5 bg-[#53eafd33] shadow-[0_0_12px_#53eafd55]"
              style={{ top: `${scanY}%` }}
            />
            <span className="absolute top-5 left-6 font-pixel text-xs tracking-[0.12em] text-(--muted-foreground)">
              ILLUME · FULL WALKTHROUGH
            </span>
            <span className="absolute top-5 right-6 font-pixel text-xs tracking-[0.12em] text-(--accent)">
              <span className="blink">●</span> 5 MIN
            </span>
            <span className="absolute top-1/2 left-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-4.5">
              <span
                className="flex h-24 w-24 items-center justify-center"
                style={{
                  background: pulse ? "#a3004c" : "#c2185b",
                  boxShadow: `0 0 ${pulse ? 18 : 32}px #f6339a`,
                }}
              >
                <svg
                  width="30"
                  height="34"
                  viewBox="0 0 15 17"
                  shapeRendering="crispEdges"
                  fill="#fdf2f8"
                  aria-hidden="true"
                >
                  <path d="M0 0h3v1h3v1h3v1h3v1h3v9h-3v1H9v1H6v1H3v1H0z" />
                </svg>
              </span>
              <span className="font-pixel text-lg">Watch the tour</span>
            </span>
            <span
              aria-hidden="true"
              className="absolute inset-x-6 bottom-5.5 flex gap-1"
            >
              {CHAPTERS.map(([t], i) => {
                const next = CHAPTERS[i + 1]?.[0] ?? VIDEO_LENGTH_S;
                return (
                  <span
                    key={t}
                    className="h-1.5"
                    style={{
                      flex: `${next - t} 1 0`,
                      background:
                        i < active ? "#00b8db" : i === active ? "#f6339a" : "#27272a",
                    }}
                  />
                );
              })}
            </span>
          </button>
        )}
      </div>

      <div className="flex min-w-0 flex-col gap-2">
        <p className="eyebrow m-0 mb-1.5">Chapters</p>
        {CHAPTERS.map(([t, label], i) => {
          const current = start !== null ? start === t : i === active;
          return (
            <button
              key={t}
              type="button"
              onClick={() => setStart(t)}
              className={`flex items-center gap-3.5 rounded-sm border px-4 py-3.5 text-left hover:cursor-pointer ${current ? "border-(--accent) bg-(--accent)/5" : "border-(--border) bg-(--card) hover:border-(--border-strong)"}`}
            >
              <span
                className={`w-11 shrink-0 font-pixel text-sm ${current ? "text-(--accent)" : "text-(--muted-foreground)"}`}
              >
                {stamp(t)}
              </span>
              <span className="grow text-[15px]">{label}</span>
              <span
                aria-hidden="true"
                className={`font-pixel text-sm ${current ? "text-(--accent)" : "text-(--muted-foreground)"}`}
              >
                {current ? "▶" : "›"}
              </span>
            </button>
          );
        })}
        <a
          href={`https://www.youtube.com/watch?v=${VIDEO_ID}`}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 font-pixel text-[13px] text-(--muted-foreground) hover:text-(--foreground)"
        >
          Open on YouTube ↗
        </a>
      </div>
    </div>
  );
}

const FAQS: [string, string][] = [
  [
    "Does Illume change my code?",
    "No. It only reads your repository. It never pushes, opens pull requests or needs write access.",
  ],
  [
    "Can I use it on private repositories?",
    "Yes. Sign in with GitHub and Illume clones with your own access, so it sees exactly the repositories you can.",
  ],
  [
    "Which languages does it understand?",
    "Thirteen, parsed with tree-sitter: Python (notebooks too), JavaScript and TypeScript (with JSX and TSX), Go, Rust, Java, C, C++, Ruby, C#, PHP, Swift and Kotlin.",
  ],
  [
    "Which AI model does it use?",
    "Bring your own key and model if you like, or use the default. Answers come from your code first: the chat only answers from what it retrieved, with sources.",
  ],
  [
    "How big a repository can it handle?",
    "Every file is parsed and mapped. History is read from the latest 500 commits and 200 merged pull requests, which is plenty to tell who owns what.",
  ],
  [
    "How does it stay up to date?",
    "Turn on auto-update and Illume checks the branch every 1, 3, 6, 12 or 24 hours, then re-reads only the files that changed.",
  ],
  [
    "Can my editor use it?",
    "Yes. Illume speaks MCP, so Claude Code, Cursor or any MCP client can ask it about the codebase while it works.",
  ],
];

const ASKS = [
  "what happens when a payment fails?",
  "where are the feature flags read?",
  "who should review changes to auth?",
];

/**
 * The FAQ: a typed "ask the repo" prompt on the left, an accordion on the
 * right with one answer open at a time.
 *
 * @returns The FAQ grid.
 */
export function Faq() {
  const [ref, k] = useTicker(100, 39);
  const [open, setOpen] = useState(0);
  const loop = k % 120;
  const ask = typed(ASKS[Math.floor(loop / 40)], loop % 40);

  return (
    <div
      ref={ref}
      className="grid items-start gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.7fr)] lg:gap-16"
    >
      <div className="flex min-w-0 flex-col gap-5.5">
        <p className="m-0 font-pixel text-sm tracking-[0.14em] text-(--chart-2) uppercase">
          FAQ
        </p>
        <h2 className="m-0 font-pixel text-[clamp(2.2rem,4.2vw,3.8rem)] leading-[1.02] tracking-[-0.02em]">
          Questions,
          <br />
          <span className="gradient-text">answered</span>
        </h2>
        <p className="m-0 text-[17px] leading-relaxed text-zinc-400">
          The things people ask before they paste their first link.
        </p>
        <div className="mt-2.5 flex flex-col gap-3 rounded-sm border border-white/8 bg-(--card) p-4.5">
          <span className="eyebrow">Still stuck? Ask the repo</span>
          <span aria-hidden="true" className="min-h-11.5 font-pixel text-[15px] leading-normal">
            <span className="text-(--accent)">&gt;</span> {ask}
            <span className="caret text-(--accent)">▌</span>
          </span>
        </div>
      </div>

      <div className="flex min-w-0 flex-col border-t border-(--border)">
        {FAQS.map(([q, a], i) => {
          const isOpen = i === open;
          const id = `faq-${i}`;
          return (
            <div key={q} className="border-b border-(--border)">
              <h3 className="m-0">
                <button
                  type="button"
                  onClick={() => setOpen(isOpen ? -1 : i)}
                  aria-expanded={isOpen}
                  aria-controls={id}
                  className="flex w-full items-center gap-4.5 px-1 py-6 text-left hover:cursor-pointer"
                >
                  <span
                    className={`w-7 shrink-0 font-pixel text-[13px] ${isOpen ? "text-(--accent)" : "text-(--faint-foreground)"}`}
                  >
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span
                    className={`grow font-pixel text-xl leading-snug ${isOpen ? "text-(--foreground)" : "text-zinc-300"}`}
                  >
                    {q}
                  </span>
                  <span
                    aria-hidden="true"
                    className={`flex h-7 w-7 shrink-0 items-center justify-center border font-pixel ${isOpen ? "border-(--accent) text-(--accent)" : "border-(--border-strong) text-(--border-strong)"}`}
                  >
                    {isOpen ? "−" : "+"}
                  </span>
                </button>
              </h3>
              {isOpen && (
                <p
                  id={id}
                  className="rise m-0 pr-13 pb-6.5 pl-12.5 text-base leading-relaxed text-zinc-400"
                >
                  {a}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const END_REPOS = ["your/repo", "acme/payments-api", "team/monolith", "you/side-project"];

/**
 * The closing call to action over an animated bar wave.
 *
 * @returns The final section's content.
 */
export function EndCta() {
  const [ref, k] = useTicker(100, 29);
  const loop = k % 160;
  const repo = END_REPOS[Math.floor(loop / 40)];
  const p = loop % 40;
  // Type the name in, hold, then delete it three characters a tick.
  const shown = repo.slice(
    0,
    Math.min(repo.length, p < 30 ? p : Math.max(0, repo.length - (p - 30) * 3)),
  );
  const hot = Math.floor(k / 2) % 48;

  return (
    <div ref={ref}>
      <div
        aria-hidden="true"
        className="absolute inset-x-0 bottom-0 grid h-30 grid-cols-[repeat(48,minmax(0,1fr))] items-end gap-[3px]"
      >
        {Array.from({ length: 48 }, (_, i) => {
          const a = Math.sin(i * 0.35 - k * 0.25) * 0.5 + 0.5;
          const b = Math.sin(i * 0.13 + k * 0.11) * 0.5 + 0.5;
          const h = Math.round((a * 0.65 + b * 0.35) * 12) * 8 + 8;
          return (
            <span
              key={i}
              style={{
                height: h,
                background: i === hot ? "#f6339a55" : h > 72 ? "#00b8db33" : "#00b8db1a",
              }}
            />
          );
        })}
      </div>
      <div className="relative mx-auto flex max-w-7xl flex-col items-center gap-7 px-6 pt-35 pb-50 text-center">
        <p className="m-0 font-pixel text-[15px] tracking-[0.08em] text-(--muted-foreground)">
          &gt; illume ingest github.com/
          <span className="text-(--foreground)">{shown}</span>
          <span className="caret text-(--accent)">_</span>
        </p>
        <h2 className="m-0 font-pixel text-[clamp(2.6rem,6vw,5.4rem)] leading-none tracking-[-0.02em]">
          Your next repo,
          <br />
          <span className="gradient-text">understood by lunch</span>
        </h2>
        <p className="m-0 max-w-140 text-lg leading-relaxed text-zinc-400">
          Paste a link. Get the map, the guide and a teammate who has read every
          file.
        </p>
        <div className="flex flex-wrap justify-center gap-3.5">
          <Link
            href="/login"
            className="cta inline-flex items-center gap-3 rounded-sm bg-(--primary) px-7 py-4 font-pixel text-[17px] tracking-[0.04em] text-(--primary-foreground)"
          >
            Get started <span aria-hidden="true">→</span>
          </Link>
          <a
            href="#tour"
            className="ghost inline-flex items-center gap-3 rounded-sm border border-(--border-strong) bg-(--background)/60 px-7 py-4 font-pixel text-[17px] tracking-[0.04em] text-zinc-300"
          >
            Watch the tour
          </a>
        </div>
      </div>
    </div>
  );
}
