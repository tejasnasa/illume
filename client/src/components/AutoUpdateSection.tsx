/**
 * Auto-update settings and live status for an ingested repository.
 * @module AutoUpdateSection
 */
"use client";

import triggerSyncAction from "@/actions/triggerSync";
import updateAutoUpdateAction from "@/actions/updateAutoUpdate";
import {
  ArrowsClockwiseIcon,
  CheckCircleIcon,
  CircleDashedIcon,
  ClockIcon,
  WarningIcon,
} from "@phosphor-icons/react/dist/ssr";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Repository from "@/types/repository";
import Button from "./ui/Button";
import OptionMenu from "./ui/OptionsMenu";
import Switch from "./ui/Switch";
import { timeAgo } from "@/utils/timeAgo";

/** Cadence choices the backend accepts; mirrors the picker in the PATCH route. */
const INTERVAL_OPTIONS: { hours: number; label: string }[] = [
  { hours: 1, label: "Every hour" },
  { hours: 3, label: "Every 3 hours" },
  { hours: 6, label: "Every 6 hours" },
  { hours: 12, label: "Every 12 hours" },
  { hours: 24, label: "Every 24 hours" },
];

/**
 * Shape of `last_sync_summary` as written by the backend `summarise()` helper.
 *
 * Pinning the surface here so the section renders exactly the fields it knows
 * about and silently ignores anything else the JSONB grows in the future.
 */
type SyncSummary = {
  files_upserted?: number;
  files_deleted?: number;
  files_changed?: number;
  new_commit_sha?: string;
  glossary_added?: number;
  embeddings_added?: number;
  status?: string;
};

/**
 * The six `sync_status` values the backend writes, narrowed to the ones the UI
 * actually surfaces. `checking` is treated as active -- a probe in flight is
 * still activity the user can see.
 */
const ACTIVE_SYNC_STATUSES = new Set(["queued", "checking", "updating"]);

/**
 * Props for AutoUpdateSection.
 */
type Props = {
  repo: Repository;
};

/**
 * Renders the auto-update switch, interval selector, sync-now action, and a
 * status line summarising the last sync.
 *
 * The whole panel mirrors the shape of the export/danger-zone sections in
 * `RepoSettings`. State changes PATCH the backend; the action throws on
 * failure, and the catch surfaces the backend's `detail` message inline. The
 * caller relies on `router.refresh()` (not `revalidatePath`) to repaint, which
 * is the codebase-wide convention.
 *
 * @param repo - Repository record carrying the auto-update fields.
 * @returns The rendered auto-update section.
 */
export default function AutoUpdateSection({ repo }: Props) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isActive = ACTIVE_SYNC_STATUSES.has(repo.sync_status);
  const disabled = isSubmitting || isSyncing || isActive;

  const summary = (repo.last_sync_summary ?? null) as SyncSummary | null;

  /**
   * Sends a PATCH for the switch and refreshes the page so the parent layout
   * re-fetches with the new `auto_update_enabled` value.
   */
  const handleToggle = async (next: boolean) => {
    setError(null);
    setIsSubmitting(true);
    try {
      await updateAutoUpdateAction({ repoId: repo.id, enabled: next });
      router.refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update settings",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  /**
   * Sends a PATCH for the chosen cadence and refreshes the page. The selector
   * is also locked while a sync is active -- changing the cadence mid-sync
   * would race the next claim.
   */
  const handleIntervalChange = async (hours: number) => {
    if (hours === repo.auto_update_interval_hours) return;
    setError(null);
    setIsSubmitting(true);
    try {
      await updateAutoUpdateAction({
        repoId: repo.id,
        intervalHours: hours,
      });
      router.refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update interval",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  /**
   * POSTs /sync and refreshes the page so the layout picks up the new
   * `sync_status='queued'` and `next_sync_at`.
   */
  const handleSyncNow = async () => {
    setError(null);
    setIsSyncing(true);
    try {
      await triggerSyncAction(repo.id);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to queue sync");
    } finally {
      setIsSyncing(false);
    }
  };

  return (
    <div className="mt-8 rounded-sm border border-(--primary)/20 divide-y divide-(--primary)/10">
      <div className="px-5 py-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-(--primary)">
          Auto-Update
        </p>
      </div>

      <div className="px-5 py-4 space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-(--foreground)">
              Keep analysis current
            </p>
            <p className="text-xs text-(--muted-foreground) mt-0.5 max-w-[320px]">
              Periodically check the repository for new commits and update the
              graph, glossary, and embeddings in the background.
            </p>
          </div>
          <Switch
            checked={repo.auto_update_enabled}
            disabled={disabled}
            onChange={(e) => handleToggle(e.target.checked)}
            aria-label="Enable auto-update"
          />
        </div>

        {repo.auto_update_enabled && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-(--muted-foreground)">Interval</span>
            <OptionMenu
              size="sm"
              direction="left"
              trigger={
                <span className="inline-flex items-center gap-1.5 text-xs text-(--foreground) bg-(--muted)/40 border border-(--border) rounded-sm px-3 py-1.5 hover:bg-(--muted)/60 transition-colors">
                  <ClockIcon size={12} />
                  {formatInterval(repo.auto_update_interval_hours)}
                  <span className="text-(--muted-foreground)">▾</span>
                </span>
              }
              items={INTERVAL_OPTIONS.map((opt) => ({
                label: opt.label,
                disabled: isSubmitting,
                onClick: () => handleIntervalChange(opt.hours),
              }))}
            />
          </div>
        )}
      </div>

      <div className="flex items-center justify-between px-5 py-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-(--foreground)">Sync now</p>
          <StatusLine repo={repo} summary={summary} />
        </div>
        <Button
          size="sm"
          onClick={handleSyncNow}
          loading={isSyncing}
          disabled={disabled}
          className="gap-1.5 shrink-0"
        >
          <ArrowsClockwiseIcon weight="duotone" size={15} />
          Sync now
        </Button>
      </div>

      {error && (
        <div className="px-5 py-3 text-xs text-red-400 border-t border-red-500/10">
          {error}
        </div>
      )}
    </div>
  );
}

/**
 * Picks a human label for the cadence picker.
 */
function formatInterval(hours: number): string {
  const match = INTERVAL_OPTIONS.find((opt) => opt.hours === hours);
  if (match) return match.label;
  return `Every ${hours} hours`;
}

/**
 * Renders the one-line summary of the last sync's outcome.
 *
 * Three branches, in priority order:
 * 1. `last_sync_error` is set -- surface it (the backend writes the error
 *    string after a failed attempt).
 * 2. A sync is currently in flight -- show "Syncing…".
 * 3. Auto-update has been auto-paused after consecutive failures -- say so.
 * 4. Otherwise: relative time of the last sync plus a count of files touched.
 */
function StatusLine({
  repo,
  summary,
}: {
  repo: Repository;
  summary: SyncSummary | null;
}) {
  if (repo.last_sync_error) {
    return (
      <p className="text-xs text-red-400 mt-0.5 flex items-center gap-1.5">
        <WarningIcon size={12} weight="fill" />
        <span className="truncate">{repo.last_sync_error}</span>
      </p>
    );
  }

  if (ACTIVE_SYNC_STATUSES.has(repo.sync_status)) {
    return (
      <p className="text-xs text-(--muted-foreground) mt-0.5 flex items-center gap-1.5">
        <CircleDashedIcon size={12} className="animate-spin" />
        Syncing…
      </p>
    );
  }

  if (
    !repo.auto_update_enabled &&
    repo.consecutive_sync_failures >= 3 &&
    repo.last_synced_at
  ) {
    return (
      <p className="text-xs text-(--muted-foreground) mt-0.5 flex items-center gap-1.5">
        <WarningIcon size={12} />
        Paused after {repo.consecutive_sync_failures} consecutive failures
      </p>
    );
  }

  if (!repo.last_synced_at) {
    return (
      <p className="text-xs text-(--muted-foreground) mt-0.5">Never synced</p>
    );
  }

  return (
    <p className="text-xs text-(--muted-foreground) mt-0.5 flex items-center gap-1.5">
      <CheckCircleIcon size={12} weight="fill" className="text-green-500" />
      Updated {timeAgo(repo.last_synced_at)}
      {summary &&
      summary.files_changed !== undefined &&
      summary.files_changed > 0
        ? ` · ${summary.files_changed} file${summary.files_changed === 1 ? "" : "s"} changed`
        : ""}
    </p>
  );
}
