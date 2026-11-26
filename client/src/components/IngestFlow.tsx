/**
 * Full-page live view of an in-progress ingestion.
 *
 * Owns the policy the stream itself should not know about: when the route
 * refreshes, when a run is considered stuck, and how a retry is recognised.
 *
 * @module IngestFlow
 */

"use client";

import regenerateRepoAction from "@/actions/regenerateRepo";
import IngestLog from "@/components/ingest/IngestLog";
import PipelineBoard from "@/components/ingest/PipelineBoard";
import PixelGraph from "@/components/PixelGraph";
import { useIngestStream, type IngestStream } from "@/hooks/useIngestStream";
import type { IngestFrame, StageStateMap } from "@/types/ingest";
import { runRedirectingAction } from "@/utils/redirectingAction";
import {
  NODES_BY_ID,
  STAGE_IDS,
  activeStage,
  doneCount,
  hasFailed,
  isComplete,
  reduceFrames,
  seedFromStatus,
} from "@/utils/ingestFlow";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, useTransition } from "react";

/**
 * How long the finished board stays up before the route re-renders into the
 * repository overview. Long enough to see every stage go green and read the
 * countdown; short enough that nobody reaches for a button that is not there.
 */
const COMPLETE_REFRESH_MS = 3000;

/** Longer than a step of the countdown: a failure is worth reading first. */
const FAILURE_REFRESH_MS = 2500;

/**
 * Silence after which a run is called stalled rather than slow.
 *
 * Sized against the parse stage's publish interval: a large repository emits a
 * progress frame only every few hundred files, which on a slow disk can take
 * minutes. Anything shorter would accuse a healthy run of being stuck.
 */
const IDLE_MS = 5 * 60 * 1000;

/** How long to wait for a retry to announce itself before calling it dead. */
const RETRY_GRACE_MS = 15 * 1000;

/** The task's first run plus its automatic retries. */
const MAX_ATTEMPTS = 4;

/** Find the last index matching a predicate, without relying on ES2023. */
function lastIndexOf(
  frames: readonly IngestFrame[],
  predicate: (frame: IngestFrame) => boolean,
): number {
  for (let i = frames.length - 1; i >= 0; i -= 1) {
    if (predicate(frames[i])) return i;
  }
  return -1;
}

const isFailureFrame = (frame: IngestFrame) =>
  frame.phase === "failed" ||
  frame.status === "failed" ||
  frame.event === "error";

const isCloneStart = (frame: IngestFrame) =>
  frame.stage === "clone" && frame.phase === "started";

/** Format elapsed milliseconds as ``m:ss``. */
function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** The error the task reported, which it prefixes with ``Error:``. */
function failureMessage(frames: readonly IngestFrame[]): string | null {
  const index = lastIndexOf(
    frames,
    (frame) => isFailureFrame(frame) && frame.message.startsWith("Error:"),
  );
  return index === -1 ? null : frames[index].message.slice(6).trim() || null;
}

/** A small labelled figure in the header. */
function Stat({
  label,
  children,
  tone,
}: {
  label: string;
  children: React.ReactNode;
  tone?: "accent";
}) {
  return (
    <div
      className={`flex min-w-24 flex-col justify-center gap-1 rounded-sm border px-4 py-2.5 ${
        tone === "accent"
          ? "rise border-(--accent)/40 bg-(--accent)/5"
          : "border-white/10 bg-(--card)"
      }`}
    >
      <span
        className={`font-pixel text-[10px] tracking-[0.14em] uppercase ${
          tone === "accent" ? "text-(--accent)" : "text-zinc-500"
        }`}
      >
        {label}
      </span>
      <span className="flex items-center gap-2.5 font-pixel text-[22px] leading-none">
        {children}
      </span>
    </div>
  );
}

/** What the run has turned up, from the totals the stages published. */
function FoundSoFar({
  states,
  className = "",
}: {
  states: StageStateMap;
  className?: string;
}) {
  const files = states.parse?.progress;
  const figures = [
    {
      label: "Files read",
      value: files?.processed,
      of: files?.total,
    },
    { label: "Connections", value: states.resolve_dependencies?.count },
    { label: "Files with history", value: states.git_history?.count },
    { label: "Pull requests", value: states.pr_fetch?.count },
    { label: "Vectors", value: states.generate_embeddings?.count },
  ];

  return (
    <section
      aria-label="Map so far"
      className={`panel flex min-w-0 flex-col overflow-hidden ${className}`}
    >
      <p className="eyebrow m-0 flex items-center justify-between gap-3 border-b border-white/8 px-5 py-4">
        <span>Map so far</span>
        <span className="text-zinc-600">Totals as each stage reports</span>
      </p>
      <div
        aria-hidden="true"
        className="relative min-h-60 grow bg-[radial-gradient(ellipse_at_50%_45%,#0092b812,transparent_65%)]"
      >
        <PixelGraph
          source="sample"
          spin
          cell={3}
          hubLabels={false}
          focusLabel={false}
          spreadY={0.42}
          lightRadius={0.34}
          reveal={mapReveal(states)}
        />
      </div>
      <dl className="m-0 grid grid-cols-2 border-t border-white/8">
        {figures.map((figure, index) => (
          <div
            key={figure.label}
            className={`flex flex-col justify-end gap-1.5 border-white/6 px-5 py-4.5 ${
              index % 2 === 1 ? "border-l" : ""
            } ${index > 1 ? "border-t" : ""} ${
              index === figures.length - 1 && figures.length % 2 === 1
                ? "col-span-2"
                : ""
            }`}
          >
            <dt className="font-pixel text-[10px] tracking-[0.12em] text-zinc-500 uppercase">
              {figure.label}
            </dt>
            <dd
              className={`m-0 font-pixel text-[26px] leading-none ${
                figure.value === undefined ? "text-zinc-700" : "text-(--foreground)"
              }`}
            >
              {figure.value === undefined ? "—" : figure.value.toLocaleString("en-US")}
              {figure.of !== undefined && (
                <span className="text-base text-zinc-600">
                  {" "}
                  / {figure.of.toLocaleString("en-US")}
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/**
 * How much of the illustrative map to draw: files fill in as the parse
 * counts them, and connections as imports resolve.
 *
 * @param states - Stage states from the stream.
 * @returns Fractions of files and links to show.
 */
export function mapReveal(states: StageStateMap): { files: number; links: number } {
  const fraction = (id: string, counted?: { processed: number; total: number }) => {
    const state = states[id]?.state;
    if (state === "done") return 1;
    if (counted && counted.total > 0) return Math.min(1, counted.processed / counted.total);
    return state === "active" ? 0.5 : 0;
  };
  return {
    files: fraction("parse", states.parse?.progress),
    links: fraction("resolve_dependencies"),
  };
}

/**
 * The panel shown once a run has failed for good.
 *
 * @param stage - Label of the stage that was running, if one was.
 * @param message - The error the task reported, if it reached the page.
 * @param attempts - How many runs were made.
 * @param retryable - Whether a fresh run can be started from here.
 */
function FailurePanel({
  stage,
  message,
  attempts,
  repoId,
  retryable,
}: {
  stage: string | null;
  message: string | null;
  attempts: number;
  repoId: string;
  retryable: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const retry = () =>
    startTransition(async () => {
      setError(
        await runRedirectingAction(
          () => regenerateRepoAction(repoId),
          "Could not start a new run",
        ),
      );
    });

  return (
    <section
      role="alert"
      className="rise flex flex-col gap-4 rounded-sm border border-(--destructive)/50 bg-(--destructive)/5 p-5.5 md:flex-row md:items-center md:justify-between"
    >
      <div className="flex min-w-0 flex-col gap-2">
        <p className="m-0 font-pixel text-xs tracking-[0.12em] text-(--destructive) uppercase">
          ✕ {stage ? `Stopped at ${stage}` : "The run stopped"}
          {attempts > 1 ? ` · ${attempts} attempts` : ""}
        </p>
        <p className="m-0 text-[15px] text-zinc-300">
          {message ??
            "The worker reported a failure without a message. The live log has everything that reached this page."}
        </p>
        <p className="m-0 text-sm text-zinc-500">
          A new run starts from a fresh clone, so a passing problem such as a
          network timeout usually clears on its own.
        </p>
      </div>
      <div className="flex shrink-0 flex-col items-start gap-2 md:items-end">
        <div className="flex gap-2.5">
          <Link
            href="/dashboard"
            className="ghost rounded-sm border border-white/15 px-4 py-2.5 font-pixel text-xs tracking-[0.08em] text-zinc-300 uppercase"
          >
            Dashboard
          </Link>
          {retryable && (
            <button
              type="button"
              onClick={retry}
              disabled={pending}
              className="cta rounded-sm bg-(--primary) px-4 py-2.5 font-pixel text-xs tracking-[0.08em] text-white uppercase disabled:opacity-60"
            >
              {pending ? "Starting…" : "↻ Try again"}
            </button>
          )}
        </div>
        {error && (
          <p className="m-0 text-xs text-(--destructive)">{error}</p>
        )}
      </div>
    </section>
  );
}

/**
 * The in-progress ingestion view.
 *
 * @param repoId - Repository being ingested.
 * @param token - Auth token for the WebSocket.
 * @param repoLabel - ``owner/name`` shown in the header.
 * @param branch - Branch being ingested, if known.
 * @param commitSha - Commit being ingested, if known.
 * @param status - The repository status as the server rendered it.
 * @param stream - Pre-built frame source. Supplying one suppresses the
 *   socket and the route refresh, because a caller that owns the frames also
 *   owns the lifecycle they describe.
 * @returns The header, the pipeline board, the live log and the totals.
 */
export default function IngestFlow({
  repoId,
  token,
  repoLabel,
  branch,
  commitSha,
  status,
  stream: injected,
  idleMs = IDLE_MS,
}: {
  repoId: string;
  token: string;
  repoLabel: string;
  branch: string | null;
  commitSha: string | null;
  status: string;
  stream?: IngestStream;
  /** Override for the stall threshold; exposed so it can be exercised. */
  idleMs?: number;
}) {
  const router = useRouter();
  const own = useIngestStream({ repoId, token, enabled: !injected });
  const { frames, closed, reconnect } = injected ?? own;

  const [elapsed, setElapsed] = useState(0);
  const [stalled, setStalled] = useState(false);

  // Seeded once, lazily. An effect would run after frames may already have
  // arrived and could clobber them.
  const [seed] = useState<StageStateMap>(() => seedFromStatus(status));

  const failureIndex = useMemo(
    () => lastIndexOf(frames, isFailureFrame),
    [frames],
  );
  const cloneIndex = useMemo(() => lastIndexOf(frames, isCloneStart), [frames]);

  // A page rendered after the run failed has no failure frame to go on, only
  // the status.
  const failedBeforeMount = status === "failed";

  // A clone start after a failure is a retry: the task re-runs from the top,
  // so the board is rebuilt from that frame rather than left showing the
  // failure, which the monotonic reducer would otherwise never undo.
  const retrying =
    cloneIndex > failureIndex && (failureIndex >= 0 || failedBeforeMount);

  const states = useMemo(() => {
    if (retrying)
      return reduceFrames(seedFromStatus("cloning"), frames.slice(cloneIndex));
    return reduceFrames(seed, frames);
  }, [seed, frames, retrying, cloneIndex]);

  const complete = isComplete(states);
  const failed =
    !retrying && (hasFailed(states) || failureIndex >= 0 || failedBeforeMount);

  const attempt = useMemo(() => frames.filter(isCloneStart).length, [frames]);

  /* ── Elapsed clock and stall detection ──
     One tick drives both. Idleness is derived from how long ago the last
     frame landed rather than stored, so nothing has to be reset when one
     arrives -- a stalled run is simply one whose gap has grown. */
  // Seeded to 0 and stamped on mount rather than at declaration: reading the
  // clock during render would be an impure call in a component body.
  const startedAt = useRef(0);
  const lastFrameAt = useRef(0);

  // Stamped on mount only. Folding this into the ticking effect below would
  // restart the elapsed clock whenever the stall threshold changed.
  useEffect(() => {
    const now = Date.now();
    startedAt.current = now;
    lastFrameAt.current = now;
  }, []);

  // The clock stops with the run, so the figure left on screen is how long
  // it took rather than how long the tab has been open.
  const running = !complete && !failed;

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      const tick = Date.now();
      setElapsed(tick - startedAt.current);
      setStalled(tick - lastFrameAt.current > idleMs);
    }, 1000);
    return () => clearInterval(timer);
  }, [idleMs, running]);

  useEffect(() => {
    lastFrameAt.current = Date.now();
  }, [frames.length]);

  /* ── Refresh policy ──
     Fired at most once per outcome, and never on the intermediate status
     updates, which would otherwise re-render the route mid-run. A completed
     run re-renders into the overview, which is the redirect the countdown
     announces. */
  const fired = useRef<Set<string>>(new Set());
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // An injected stream means the caller supplied the frames, so there is no
    // server render behind them for a refresh to pick up.
    if (injected) return;

    const outcome = failed ? "failed" : complete ? "complete" : null;
    if (!outcome || fired.current.has(outcome)) return;
    // A page that opened on an already-failed run is already the server's
    // latest word; refreshing it would only repaint the same failure.
    if (outcome === "failed" && failedBeforeMount && failureIndex < 0) return;
    fired.current.add(outcome);
    refreshTimer.current = setTimeout(
      () => router.refresh(),
      outcome === "failed" ? FAILURE_REFRESH_MS : COMPLETE_REFRESH_MS,
    );
  }, [complete, failed, router, injected, failedBeforeMount, failureIndex]);

  // Cleared only on unmount: dep-driven cleanup would cancel a pending
  // refresh the moment the other outcome flipped.
  useEffect(
    () => () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    },
    [],
  );

  /* ── Redirect countdown ──
     Purely a display of the pending refresh above, so it never navigates by
     itself. */
  const [countdown, setCountdown] = useState(COMPLETE_REFRESH_MS / 1000);
  useEffect(() => {
    if (!complete) return;
    const timer = setInterval(
      () => setCountdown((value) => Math.max(1, value - 1)),
      1000,
    );
    return () => clearInterval(timer);
  }, [complete]);

  /* ── Retry grace ──
     The socket closes on the terminal marker, so a retry publishes into a
     channel nobody is listening to. Re-open it once the backoff has had time
     to elapse; if nothing arrives, the run really is over. A page opened onto
     a failed run waits the same grace, because a retry may be on its way. */
  // Records which attempt the grace expired on, rather than a plain boolean:
  // a later retry bumps `attempt` past it and the flag clears itself, with no
  // reset effect to fire on every new attempt.
  const [graceExpiredAtAttempt, setGraceExpiredAtAttempt] = useState<
    number | null
  >(null);

  useEffect(() => {
    if (complete || (!closed && !failed)) return;
    const atAttempt = attempt;
    const timer = setTimeout(() => {
      setGraceExpiredAtAttempt(atAttempt);
      if (closed) reconnect();
    }, RETRY_GRACE_MS);
    // `attempt` is a dependency so a retry cancels the pending grace rather
    // than racing it.
    return () => clearTimeout(timer);
  }, [closed, failed, complete, reconnect, attempt]);

  const retryExpired =
    graceExpiredAtAttempt !== null && graceExpiredAtAttempt >= attempt;
  const finalFailure = failed && retryExpired;

  const active = activeStage(states);
  const activeLabel = active ? NODES_BY_ID[active]?.label : null;
  const failedStage = STAGE_IDS.find((id) => states[id]?.state === "failed");

  // `pending` means no worker has claimed the job, so nothing is lit and the
  // header has to say so rather than name a stage that has not begun.
  const queued = status === "pending" && !active && !complete && !failed;

  const headline = queued
    ? "Queued — waiting for a worker"
    : finalFailure
      ? "Ingestion failed"
      : failed
        ? "Failed, retrying…"
        : complete
          ? "Ready"
          : stalled
            ? "Still working…"
            : (activeLabel ?? "Starting…");

  const name = repoLabel.split("/").pop() || repoLabel;
  const finished = doneCount(states);
  const total = STAGE_IDS.length;

  const [lead, emphasis] = complete
    ? ["Your map is", "ready"]
    : finalFailure
      ? ["Could not read", name]
      : queued
        ? ["Waiting to read", name]
        : ["Reading", name];

  const command = [
    `> illume ingest ${repoLabel}`,
    branch ? ` --branch ${branch}` : "",
    commitSha ? ` @${commitSha.slice(0, 7)}` : "",
  ].join("");

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 pt-10 pb-16 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div className="flex min-w-0 flex-col gap-3">
          <p
            aria-hidden="true"
            className="m-0 truncate font-pixel text-[13px] tracking-[0.12em] text-(--muted-foreground)"
          >
            {command}
            <span className="caret text-(--accent)">_</span>
          </p>
          <h1 className="m-0 font-pixel text-[clamp(2.2rem,4.6vw,3.8rem)] leading-none font-normal tracking-[-0.02em] break-words">
            {lead}{" "}
            <span
              className={
                finalFailure ? "text-(--destructive)" : "gradient-text pb-[0.06em]"
              }
            >
              {emphasis}
            </span>
          </h1>
          <p
            role="status"
            className={`m-0 flex flex-wrap items-center gap-x-2 text-base ${
              failed ? "text-(--destructive)" : "text-zinc-400"
            }`}
          >
            {running && !queued && !stalled && activeLabel && (
              <span className="text-zinc-500">Now:</span>
            )}
            <span>{headline}</span>
            {attempt > 1 && !complete && (
              <span className="font-pixel text-xs tracking-[0.08em] text-zinc-500 uppercase">
                · attempt {attempt} of {MAX_ATTEMPTS}
              </span>
            )}
          </p>
        </div>

        <div className="flex items-stretch gap-2.5">
          <Stat label="Elapsed">{formatElapsed(elapsed)}</Stat>
          <Stat label="Stages">
            {finished}
            <span className="text-zinc-600">/ {total}</span>
          </Stat>
          {complete && (
            <Stat label="Redirecting" tone="accent">
              <span aria-hidden="true" className="blink size-2 bg-(--accent)" />
              {countdown}s
            </Stat>
          )}
        </div>
      </header>

      <div aria-hidden="true" className="flex h-1.5 bg-zinc-900">
        <span
          className={`block h-1.5 transition-[width] duration-200 ease-[steps(3)] ${
            failed
              ? "bg-(--destructive)"
              : "bg-linear-to-r from-(--primary) to-(--accent)"
          }`}
          style={{ width: `${Math.round((finished / total) * 100)}%` }}
        />
      </div>

      {finalFailure && (
        <FailurePanel
          stage={failedStage ? NODES_BY_ID[failedStage].label : null}
          message={failureMessage(frames)}
          attempts={Math.max(attempt, 1)}
          repoId={repoId}
          retryable={!injected}
        />
      )}

      <PipelineBoard states={states} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <IngestLog frames={frames} repoId={repoId} className="xl:col-span-7" />
        <FoundSoFar states={states} className="xl:col-span-5" />
      </div>

      <p className="m-0 font-pixel text-xs tracking-[0.06em] text-zinc-500 uppercase">
        {finalFailure
          ? "Nothing from this run was kept. Trying again starts over from the clone."
          : "Safe to close this tab. The work keeps running, and the dashboard shows when it is ready."}
      </p>
    </main>
  );
}
