/**
 * Full-screen live view of an in-progress ingestion.
 *
 * @module IngestFlow
 *
 * Port of ``client/src/components/IngestFlow.tsx``.
 *
 * It owns the policy the stream itself should not know about: when the
 * repository is refetched, when a run is considered stuck, and how a retry
 * is recognised.
 *
 * Two things differ from the web version, both because there is no server
 * render behind the app:
 *
 * - The web version refreshed the route when a run finished; here that is
 *   an invalidation of the repository's query, which repaints every screen
 *   reading it.
 * - The web version's page was replaced wholesale by this view while a
 *   repository was indexing. On a phone the repository overview is a tab
 *   inside the shell, so the live view takes over that tab instead.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";
import { useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/api/queryKeys";
import { IngestFlowCanvas } from "@/components/IngestFlowCanvas";
import { IngestLogDrawer } from "@/components/IngestLogDrawer";
import { useAuth } from "@/hooks/useAuth";
import { useIngestStream, type IngestStream } from "@/hooks/useIngestStream";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import {
  NODES_BY_ID,
  activeStage,
  hasFailed,
  isComplete,
  reduceFrames,
  seedFromStatus,
} from "@/lib/ingestFlow";
import { RepoStatusView } from "@/ui/RepoStatusView";
import { colors } from "@/theme/tokens";
import type { IngestFrame, StageStateMap } from "@/types/ingest";

/**
 * How long to hold the finished board before refetching the repository.
 *
 * This must stay longer than the canvas's own settle (the lit-edge draw and
 * the pulse, ~700ms), or the screen would swap out mid-animation. If either
 * number moves, move them together.
 */
const COMPLETE_REFRESH_MS = 900;

/** Longer than completion: a failure is worth reading before the screen moves. */
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

/**
 * Find the last index matching a predicate, without relying on ES2023.
 *
 * @param frames - The frames to search.
 * @param predicate - The test to apply.
 * @returns The index of the last match, or -1.
 */
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

/**
 * Format elapsed milliseconds as ``m:ss``.
 *
 * @param ms - The elapsed time in milliseconds.
 * @returns The formatted duration.
 */
export function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** Props for {@link IngestFlow}. */
export interface IngestFlowProps {
  /** Repository being ingested, as its UUID. The socket route is typed as one. */
  repoId: string;
  /** The repository's user-scoped number, which the detail query is keyed on. */
  repoNumber: string;
  /** The repository status as the server rendered it. */
  status: string;
  /**
   * How long the repository has been in the failed state, in milliseconds.
   *
   * The coarse status says the run failed but not which stage gave up, so
   * it is the only signal that separates "still retrying" from "given up"
   * for a failure that happened before the socket connected.
   */
  failureAgeMs?: number;
  /**
   * Pre-built frame source. Supplying one suppresses the socket and the
   * refetch, because a caller that owns the frames also owns the lifecycle
   * they describe.
   */
  stream?: IngestStream;
  /** Override for the stall threshold; exposed so it can be exercised. */
  idleMs?: number;
}

/**
 * The in-progress ingestion view.
 *
 * @param props - The repository being ingested and the frame source.
 * @returns The header, the flow canvas, and the raw-log drawer.
 */
export function IngestFlow({
  repoId,
  repoNumber,
  status,
  failureAgeMs,
  stream: injected,
  idleMs = IDLE_MS,
}: IngestFlowProps) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const reducedMotion = useReducedMotion();
  const { enable: enablePush } = usePushNotifications();

  const own = useIngestStream({
    repoId,
    token: token ?? "",
    enabled: Boolean(token) && !injected,
  });
  const { frames, closed, reconnect } = injected ?? own;

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [stalled, setStalled] = useState(false);

  // Seeded once, lazily. An effect would run after frames may already have
  // arrived and could clobber them.
  const [seed, setSeed] = useState<StageStateMap>(() => seedFromStatus(status));
  const seedStatus = useRef(status);

  // The coarse status advances as the pipeline moves, and each advance
  // proves more of the chain. Re-seeding on the change keeps the board
  // honest when the socket connected after the fact and missed the early
  // frames -- which is exactly what happens to a screen opened two minutes
  // into an ingest.
  useEffect(() => {
    if (status === seedStatus.current) return;
    seedStatus.current = status;
    setSeed(seedFromStatus(status));
  }, [status]);

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
  // A repository that is already ``failed`` when the screen opens has no
  // failure frame to read -- the socket only carries frames published after
  // it connects -- so the coarse status has to carry the failure on its
  // own.
  const failed =
    !retrying &&
    (hasFailed(states) || failureIndex >= 0 || status === "failed");

  /* ── Permission for notifications ──
     Asked for here rather than at launch: by the time a repository has
     finished indexing, the reader knows what the app does, and a prompt
     that arrives with something to say is a prompt that gets allowed. */
  const askedForPermission = useRef(false);
  useEffect(() => {
    if (!complete) return;
    if (askedForPermission.current) return;
    askedForPermission.current = true;
    void enablePush();
  }, [complete, enablePush]);

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

  useEffect(() => {
    const timer = setInterval(() => {
      const tick = Date.now();
      setElapsed(tick - startedAt.current);
      setStalled(tick - lastFrameAt.current > idleMs);
    }, 1000);
    return () => clearInterval(timer);
  }, [idleMs]);

  useEffect(() => {
    lastFrameAt.current = Date.now();
  }, [frames.length]);

  /* ── Refresh policy ──
     Fired at most once per outcome, and never on the intermediate status
     updates, which would otherwise re-render the screen mid-animation. */
  const fired = useRef<Set<string>>(new Set());
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // An injected stream means the caller supplied the frames, so there is
    // no server state behind them for a refetch to pick up.
    if (injected) return;

    const outcome = failed ? "failed" : complete ? "complete" : null;
    if (!outcome || fired.current.has(outcome)) return;
    fired.current.add(outcome);
    refreshTimer.current = setTimeout(
      () => {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.repositories.detail(repoNumber),
        });
      },
      outcome === "failed" ? FAILURE_REFRESH_MS : COMPLETE_REFRESH_MS,
    );
  }, [complete, failed, queryClient, injected, repoNumber]);

  // Cleared only on unmount: dep-driven cleanup would cancel a pending
  // refetch the moment the other outcome flipped.
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
  const [graceExpiredAtAttempt, setGraceExpiredAtAttempt] = useState<
    number | null
  >(null);

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

  const retryExpired =
    graceExpiredAtAttempt !== null && graceExpiredAtAttempt >= attempt;

  // Two ways to know the failure is final rather than mid-retry: the
  // socket closed and the grace period elapsed, or the repository has been
  // sitting in the failed state for longer than the grace period.
  const failureFinal =
    retryExpired ||
    (failureAgeMs !== undefined && failureAgeMs >= RETRY_GRACE_MS);

  const active = activeStage(states);
  const activeLabel = active ? NODES_BY_ID[active]?.label : null;

  // `pending` means no worker has claimed the job, so nothing is lit and
  // there is no pipeline to watch: the static list says it better than an
  // empty board would.
  const queued = status === "pending" && !active && !complete && !failed;

  const headline = queued
    ? "Queued — waiting for a worker"
    : failed && failureFinal
      ? "Ingestion failed"
      : failed
        ? "Failed, retrying…"
        : complete
          ? "Ready"
          : stalled
            ? "Still working…"
            : (activeLabel ?? "Starting…");

  const toggleDrawer = useCallback(() => {
    setDrawerOpen((value) => !value);
  }, []);

  if (queued) {
    // The static view keeps its own testID, so a screen that reaches this
    // branch is indistinguishable from the one that renders it directly.
    return <RepoStatusView status={status} />;
  }

  const tone = failed
    ? colors.destructive
    : complete
      ? colors.success
      : colors.chart1;

  return (
    <View testID="ingest-flow" className="flex-1 bg-background">
      <View className="flex-row items-center justify-between px-4 py-2">
        <Text
          testID="ingest-flow-headline"
          className="flex-1 text-sm font-bold uppercase tracking-wide"
          style={{ color: tone }}
          numberOfLines={1}
        >
          {headline}
        </Text>

        {attempt > 1 ? (
          <Text className="ml-2 font-mono text-[10px] text-muted-foreground">
            attempt {attempt} of 4
          </Text>
        ) : null}

        <Text className="ml-3 font-mono text-xs text-muted-foreground">
          {formatElapsed(elapsed)}
        </Text>
      </View>

      <IngestFlowCanvas
        states={states}
        live={!stalled}
        attempt={attempt}
        reducedMotion={reducedMotion}
      />

      <IngestLogDrawer
        frames={frames}
        open={drawerOpen}
        onToggle={toggleDrawer}
      />
    </View>
  );
}

export default IngestFlow;
