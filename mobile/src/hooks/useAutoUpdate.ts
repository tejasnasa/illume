/**
 * Auto-update and manual-sync state for one repository.
 *
 * @module UseAutoUpdate
 *
 * Port of the state machine behind ``client/src/components/AutoUpdateSection.tsx``.
 * The web component holds the flags itself; on a phone the same three
 * requests are driven from one place so the screen, the row and the tests
 * all agree on what "busy" means.
 *
 * The three requests are:
 *
 * - ``PATCH /api/v1/repository/{id}/auto-update`` with ``enabled`` -- turn
 *   the background sync on or off.
 * - ``PATCH /api/v1/repository/{id}/auto-update`` with ``interval_hours`` --
 *   change the cadence. The server accepts 1, 3, 6, 12 or 24.
 * - ``POST /api/v1/repository/{id}/sync`` -- queue a sync right now.
 *
 * A refusal is a normal outcome rather than an exception: the server
 * answers 409 when a sync is already in flight, and 409 when the
 * repository has no baseline commit to diff against. Both messages are
 * worth showing, so the hook surfaces the server's own wording.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  triggerSync,
  updateAutoUpdate,
  type SettingsRequestOptions,
} from "@/api/settings";
import { ApiError } from "@/lib/apiError";
import type Repository from "@/types/repository";

/**
 * The sync statuses that mean a sync is in flight.
 *
 * ``checking`` counts as active: a probe in flight is still activity the
 * reader can see.
 */
export const ACTIVE_SYNC_STATUSES = new Set([
  "queued",
  "checking",
  "updating",
]);

/**
 * The cadences the server accepts, in the order the picker shows them.
 */
export const AUTO_UPDATE_INTERVALS: { hours: number; label: string }[] = [
  { hours: 1, label: "Every hour" },
  { hours: 3, label: "Every 3 hours" },
  { hours: 6, label: "Every 6 hours" },
  { hours: 12, label: "Every 12 hours" },
  { hours: 24, label: "Every 24 hours" },
];

/**
 * Args for {@link useAutoUpdate}.
 */
export interface UseAutoUpdateArgs {
  /** The repository's UUID. */
  repoId: string;
  /** Whether auto-update is currently on. */
  enabled: boolean;
  /** The current cadence, in hours. */
  intervalHours: number;
  /** The repository's current sync status. */
  syncStatus?: string;
  /** Transport overrides, so a test can inject a backend and a fetch. */
  options?: SettingsRequestOptions;
  /** Called with the updated repository after a successful change. */
  onChanged?: (repo: Repository) => void;
}

/**
 * State and actions returned by {@link useAutoUpdate}.
 */
export interface UseAutoUpdateResult {
  /** Whether auto-update is currently on. */
  enabled: boolean;
  /** The current cadence, in hours. */
  intervalHours: number;
  /** The repository's latest known sync status. */
  syncStatus: string;
  /** True while a sync is queued, checking or updating. */
  isSyncActive: boolean;
  /** True while an auto-update change is in flight. */
  isSubmitting: boolean;
  /** True while a manual sync request is in flight. */
  isSyncing: boolean;
  /** The failure message from the last request, if any. */
  error: string | null;
  /** Turn auto-update on or off. */
  setEnabled: (next: boolean) => Promise<boolean>;
  /** Change the cadence. A no-op when the cadence is already that value. */
  setIntervalHours: (hours: number) => Promise<boolean>;
  /** Queue a manual sync. */
  syncNow: () => Promise<boolean>;
  /** Dismiss the current request failure. */
  clearError: () => void;
}

/**
 * Pull the message out of a failed request.
 *
 * @param error - The failure the request raised.
 * @param fallback - The message to use when the failure carries none.
 * @returns The message to show.
 */
function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

/**
 * Manage a repository's auto-update settings.
 *
 * @param args - The repository's current settings and transport overrides.
 * @returns The settings, the busy flags and the three actions.
 */
export function useAutoUpdate({
  repoId,
  enabled: initialEnabled,
  intervalHours: initialIntervalHours,
  syncStatus: initialSyncStatus = "idle",
  options,
  onChanged,
}: UseAutoUpdateArgs): UseAutoUpdateResult {
  const [enabled, setEnabledState] = useState(initialEnabled);
  const [intervalHours, setIntervalHoursState] = useState(initialIntervalHours);
  const [syncStatus, setSyncStatus] = useState(initialSyncStatus);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The props this hook last adopted. A refetch that lands with new values
  // -- a server-side auto-pause, a sync advancing to ``updating``, a change
  // made on another device -- has to be mirrored here, but a refetch that
  // repeats the values we already hold must not overwrite the response of
  // the action that is still settling.
  const lastProps = useRef({
    enabled: initialEnabled,
    intervalHours: initialIntervalHours,
    syncStatus: initialSyncStatus,
  });

  useEffect(() => {
    const previous = lastProps.current;
    const changed =
      previous.enabled !== initialEnabled ||
      previous.intervalHours !== initialIntervalHours ||
      previous.syncStatus !== initialSyncStatus;
    if (!changed) return;
    lastProps.current = {
      enabled: initialEnabled,
      intervalHours: initialIntervalHours,
      syncStatus: initialSyncStatus,
    };
    setEnabledState(initialEnabled);
    setIntervalHoursState(initialIntervalHours);
    setSyncStatus(initialSyncStatus);
  }, [initialEnabled, initialIntervalHours, initialSyncStatus]);

  const setEnabled = useCallback(
    async (next: boolean): Promise<boolean> => {
      setError(null);
      setIsSubmitting(true);
      try {
        const repo = await updateAutoUpdate(
          repoId,
          { enabled: next },
          options,
        );
        setEnabledState(repo.auto_update_enabled);
        onChanged?.(repo);
        return true;
      } catch (cause) {
        setError(messageOf(cause, "Failed to update settings"));
        return false;
      } finally {
        setIsSubmitting(false);
      }
    },
    [onChanged, options, repoId],
  );

  const setIntervalHours = useCallback(
    async (hours: number): Promise<boolean> => {
      // The server treats a repeated value as a no-op, so the request is
      // skipped rather than sent and discarded.
      if (hours === intervalHours) return true;

      setError(null);
      setIsSubmitting(true);
      try {
        const repo = await updateAutoUpdate(
          repoId,
          { interval_hours: hours },
          options,
        );
        setIntervalHoursState(repo.auto_update_interval_hours);
        onChanged?.(repo);
        return true;
      } catch (cause) {
        setError(messageOf(cause, "Failed to update interval"));
        return false;
      } finally {
        setIsSubmitting(false);
      }
    },
    [intervalHours, onChanged, options, repoId],
  );

  const syncNow = useCallback(async (): Promise<boolean> => {
    setError(null);
    setIsSyncing(true);
    try {
      const result = await triggerSync(repoId, options);
      setSyncStatus(result.sync_status);
      return true;
    } catch (cause) {
      setError(messageOf(cause, "Failed to queue sync"));
      return false;
    } finally {
      setIsSyncing(false);
    }
  }, [options, repoId]);

  const clearError = useCallback(() => setError(null), []);

  return {
    enabled,
    intervalHours,
    syncStatus,
    isSyncActive: ACTIVE_SYNC_STATUSES.has(syncStatus),
    isSubmitting,
    isSyncing,
    error,
    setEnabled,
    setIntervalHours,
    syncNow,
    clearError,
  };
}

export default useAutoUpdate;
