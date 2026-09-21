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

/** Statuses that mean "a sync is in flight, keep refreshing". */
const ACTIVE_SYNC_STATUSES = new Set(["queued", "checking", "updating"]);

/**
 * Triggers a server refresh every 5s while `sync_status` indicates activity.
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

    const interval = setInterval(() => {
      router.refresh();
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [sync_status, router]);

  return null;
}
