/**
 * Background refresh for a repository page.
 *
 * @module RepoStatusPoller
 *
 * Port of ``client/src/components/RepoStatusPoller.tsx``. The web version
 * calls ``router.refresh()`` to re-render the server component tree; on
 * mobile the equivalent is invalidating the React Query cache, which
 * re-runs the detail query and repaints every screen reading it.
 *
 * It polls for the same two reasons the web version does:
 *
 * - The initial ingest has not settled, so ``status`` is not terminal yet.
 * - A background sync is running. A sync deliberately keeps
 *   ``status='ready'``, so the *only* signal that anything changed is
 *   ``sync_status`` -- without this the repository page would sit on stale
 *   data for the whole sync.
 *
 * The poller gives up after an hour: a sync that was killed rather than
 * failed (an OOM kill, a deploy) cannot clear its own status, and polling
 * that forever makes one wedged repository repaint every few seconds for
 * days.
 */

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/api/queryKeys";
import { shouldPoll } from "@/lib/repoStatus";

/** How often the repository is refetched while something is in flight. */
const POLL_INTERVAL_MS = 5000;

/**
 * How long to keep refreshing before giving up on a status that never
 * clears. The worker's sync lease runs for 60 minutes, so a sync that is
 * genuinely still going is always inside this window.
 */
const MAX_POLL_MS = 65 * 60 * 1000;

/** Props for the {@link RepoStatusPoller} component. */
export interface RepoStatusPollerProps {
  /** The repository's user-scoped number; the detail query is keyed on it. */
  repoNumber: string;
  /** The repository's current ingestion status. */
  status: string;
  /** The repository's current background-sync status. */
  syncStatus: string;
  /** Override the poll interval. Exposed so tests need not wait five seconds. */
  pollIntervalMs?: number;
  /** Override the give-up window. Exposed for the same reason. */
  maxPollMs?: number;
}

/**
 * Refetch the repository while an ingest or a sync is in flight.
 *
 * @param props - The repository's identifiers and current statuses.
 * @returns Nothing; the component only has side effects.
 */
export function RepoStatusPoller({
  repoNumber,
  status,
  syncStatus,
  pollIntervalMs = POLL_INTERVAL_MS,
  maxPollMs = MAX_POLL_MS,
}: RepoStatusPollerProps) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!shouldPoll(status, syncStatus)) return;
    if (!repoNumber) return;

    const startedAt = Date.now();
    const interval = setInterval(() => {
      if (Date.now() - startedAt > maxPollMs) {
        clearInterval(interval);
        return;
      }
      void queryClient.invalidateQueries({
        queryKey: queryKeys.repositories.detail(repoNumber),
      });
    }, pollIntervalMs);

    return () => clearInterval(interval);
  }, [repoNumber, status, syncStatus, queryClient, pollIntervalMs, maxPollMs]);

  return null;
}

export default RepoStatusPoller;
