/**
 * Polls while a background sync is running, so the repo page repaints when
 * `sync_status` clears. Mirrors `DashboardRefresh.tsx`, but on a different
 * predicate: the sync keeps `status='ready'`, so the dashboard component will
 * not notice it.
 * @module RepoStatusPoller
 */
"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Mirrors the `DashboardRefresh` interval; the dashboard and the repo layout
 * share a polling cadence so neither falls visibly behind.
 */
const POLL_INTERVAL_MS = 5000;

/**
 * How long to keep refreshing before giving up on a status that never clears.
 *
 * A sync that is *killed* rather than failed -- an OOM kill, or the
 * `docker stop` in a deploy -- cannot run its own cleanup, so the row goes on
 * reporting an in-flight status while nothing is running. Polling that forever
 * is what makes one wedged repository repaint the whole page every few seconds
 * for days on end. The worker's lease runs for 60 minutes, so a sync that is
 * genuinely still going is always inside this window; past it the honest thing
 * is to stop and let a reload find out.
 */
const MAX_POLL_MS = 65 * 60 * 1000;

/** Statuses that mean "a sync is in flight, keep refreshing". */
const ACTIVE_SYNC_STATUSES = new Set(["queued", "checking", "updating"]);

/**
 * Triggers a server refresh every 5s while `sync_status` indicates activity,
 * stopping after `MAX_POLL_MS` so a status that never clears cannot poll
 * indefinitely.
 *
 * @param sync_status - Current value of the repository's `sync_status` field.
 * @returns Null; only side-effects via router refresh.
 */
export default function RepoStatusPoller({
  sync_status,
}: {
  sync_status: string;
}) {
  const router = useRouter();

  useEffect(() => {
    if (!ACTIVE_SYNC_STATUSES.has(sync_status)) return;

    const startedAt = Date.now();
    const interval = setInterval(() => {
      if (Date.now() - startedAt > MAX_POLL_MS) {
        clearInterval(interval);
        return;
      }
      router.refresh();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [sync_status, router]);

  return null;
}
