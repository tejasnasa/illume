/**
 * Full-page live view of an in-progress ingestion.
 *
 * Owns the policy the stream itself should not know about: when the route
 * refreshes, when a run is considered stuck, and how a retry is recognised.
 *
 * @module IngestFlow
 */

"use client";

import IngestFlowCanvas from "@/components/IngestFlowCanvas";
import IngestLogDrawer from "@/components/IngestLogDrawer";
import { useIngestStream } from "@/hooks/useIngestStream";
import type { IngestFrame, StageStateMap } from "@/types/ingest";
import {
  NODES_BY_ID,
  activeStage,
  hasFailed,
  isComplete,
  reduceFrames,
  seedFromStatus,
} from "@/utils/ingestFlow";
import {
  CheckCircleIcon,
  ClockIcon,
  GitBranchIcon,
  GithubLogoIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react/dist/ssr";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

/**
 * How long to hold the finished board before asking the route to re-render.
 *
 * This must stay longer than the canvas's own settle (the lit-edge draw and
 * the pulse, ~700ms), or the page would swap out mid-animation. If either
 * number moves, move them together.
 */
const COMPLETE_REFRESH_MS = 900;

/** Longer than completion: a failure is worth reading before the page moves. */
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

/**
 * The in-progress ingestion view.
 *
 * @param repoId - Repository being ingested.
 * @param token - Auth token for the WebSocket.
 * @param repoLabel - ``owner/name`` shown in the header.
 * @param branch - Branch being ingested, if known.
 * @param commitSha - Commit being ingested, if known.
 * @param status - The repository status as the server rendered it.
 * @returns The header, the flow canvas, and the raw-log drawer.
 */
export default function IngestFlow({
  repoId,
  token,
  repoLabel,
  branch,
  commitSha,
  status,
}: {
  repoId: string;
  token: string;
  repoLabel: string;
  branch: string | null;
  commitSha: string | null;
  status: string;
}) {
  const router = useRouter();
  const { frames, closed, reconnect } = useIngestStream({ repoId, token });

  const [drawerOpen, setDrawerOpen] = useState(false);
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

  // A clone start after a failure is a retry: the task re-runs from the top,
  // so the board is rebuilt from that frame rather than left showing the
  // failure, which the monotonic reducer would otherwise never undo.
  const retrying = failureIndex >= 0 && cloneIndex > failureIndex;

  const states = useMemo(() => {
    if (retrying)
      return reduceFrames(seedFromStatus("cloning"), frames.slice(cloneIndex));
    return reduceFrames(seed, frames);
  }, [seed, frames, retrying, cloneIndex]);

  const complete = isComplete(states);
  const failed = !retrying && (hasFailed(states) || failureIndex >= 0);

  const attempt = useMemo(() => frames.filter(isCloneStart).length, [frames]);

  /* ── Elapsed clock and stall detection ──
     One tick drives both. Idleness is derived from how long ago the last
     frame landed rather than stored, so nothing has to be reset when one
     arrives -- a stalled run is simply one whose gap has grown. */
  // Seeded to 0 and stamped on mount rather than at declaration: reading the
  // clock during render would be an impure call in a component body.
  const startedAt = useRef(0);
  const lastFrameAt = useRef(0);

  useEffect(() => {
    const now = Date.now();
    startedAt.current = now;
    lastFrameAt.current = now;

    const timer = setInterval(() => {
      const tick = Date.now();
      setElapsed(tick - startedAt.current);
      setStalled(tick - lastFrameAt.current > IDLE_MS);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    lastFrameAt.current = Date.now();
  }, [frames.length]);

  /* ── Refresh policy ──
     Fired at most once per outcome, and never on the intermediate status
     updates, which would otherwise re-render the route mid-animation. */
  const fired = useRef<Set<string>>(new Set());
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const outcome = failed ? "failed" : complete ? "complete" : null;
    if (!outcome || fired.current.has(outcome)) return;
    fired.current.add(outcome);
    refreshTimer.current = setTimeout(
      () => router.refresh(),
      outcome === "failed" ? FAILURE_REFRESH_MS : COMPLETE_REFRESH_MS,
    );
  }, [complete, failed, router]);

  // Cleared only on unmount: dep-driven cleanup would cancel a pending
  // refresh the moment the other outcome flipped.
  useEffect(
    () => () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    },
    [],
  );

  /* ── Retry grace ──
     The socket closes on the terminal marker, so a retry publishes into a
     channel nobody is listening to. Re-open it once the backoff has had time
     to elapse; if nothing arrives, the run really is over. */
  // Records which attempt the grace expired on, rather than a plain boolean:
  // a later retry bumps `attempt` past it and the flag clears itself, with no
  // reset effect to fire on every new attempt.
  const [graceExpiredAtAttempt, setGraceExpiredAtAttempt] = useState<number | null>(null);

  useEffect(() => {
    if (!closed || complete) return;
    const atAttempt = attempt;
    const timer = setTimeout(() => {
      setGraceExpiredAtAttempt(atAttempt);
      reconnect();
    }, RETRY_GRACE_MS);
    // `attempt` is a dependency so a retry cancels the pending grace rather
    // than racing it.
    return () => clearTimeout(timer);
  }, [closed, complete, reconnect, attempt]);

  const retryExpired = graceExpiredAtAttempt !== null && graceExpiredAtAttempt >= attempt;

  const active = activeStage(states);
  const activeLabel = active ? NODES_BY_ID[active]?.label : null;

  // `pending` means no worker has claimed the job, so nothing is lit and the
  // header has to say so rather than name a stage that has not begun.
  const queued = status === "pending" && !active && !complete && !failed;

  const headline = queued
    ? "Queued — waiting for a worker"
    : failed && retryExpired
      ? "Ingestion failed"
      : failed
        ? "Failed, retrying…"
        : complete
          ? "Ready"
          : stalled
            ? "Still working…"
            : (activeLabel ?? "Starting…");

  return (
    <main className="flex h-[calc(100vh-64px)] flex-col overflow-hidden">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-(--border) px-4 text-sm">
        <GithubLogoIcon
          size={18}
          weight="fill"
          className="shrink-0 text-(--primary)"
        />
        <span className="truncate font-semibold text-(--foreground)">
          {repoLabel}
        </span>

        {branch && (
          <span className="flex shrink-0 items-center gap-1 rounded border border-(--primary)/20 bg-(--primary)/10 px-2 py-0.5 font-mono text-[10px] text-(--primary)">
            <GitBranchIcon size={11} />
            {branch}
            {commitSha && (
              <span className="opacity-75">@{commitSha.substring(0, 7)}</span>
            )}
          </span>
        )}

        <span
          className={`ml-auto flex shrink-0 items-center gap-2 font-semibold uppercase tracking-wide ${
            failed
              ? "text-(--destructive)"
              : complete
                ? "text-(--success)"
                : "text-(--chart-1)"
          }`}
        >
          {failed ? (
            <WarningCircleIcon size={16} weight="fill" />
          ) : complete ? (
            <CheckCircleIcon size={16} weight="fill" />
          ) : (
            <ClockIcon size={16} />
          )}
          {headline}
        </span>

        {attempt > 1 && (
          <span className="shrink-0 font-mono text-[10px] text-(--muted-foreground)">
            attempt {attempt} of 4
          </span>
        )}

        <span className="shrink-0 font-mono text-xs text-(--muted-foreground)">
          {formatElapsed(elapsed)}
        </span>
      </header>

      <div className="min-h-0 flex-1 p-2">
        <IngestFlowCanvas states={states} />
      </div>

      <IngestLogDrawer
        frames={frames}
        open={drawerOpen}
        onToggle={() => setDrawerOpen((value) => !value)}
      />
    </main>
  );
}
