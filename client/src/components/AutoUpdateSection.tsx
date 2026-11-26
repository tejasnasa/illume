/**
 * Auto-update settings and live status for an ingested repository.
 * @module AutoUpdateSection
 */
"use client";

import triggerSyncAction from "@/actions/triggerSync";
import updateAutoUpdateAction from "@/actions/updateAutoUpdate";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Repository from "@/types/repository";
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
 * State changes PATCH the backend; the action throws on
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
  /**
   * A sync diffs the repository against its recorded baseline commit, so a
   * repository ingested before that watermark existed has nothing to diff
   * against and the backend refuses the request outright. Offering the
   * controls anyway only turns a click into an error, so they are gated off
   * and the reason is stated in the panel instead.
   */
  const needsReingest = !repo.ingested_commit_sha;
  /**
   * The keyless free tier cannot pay for a sync -- the toggle / interval
   * picker / "Check now" button are all gated on `repo.sync_available`, which
   * is the backend's derived user-level signal rather than a derived value
   * computed here. Locking all three controls off a single flag is what keeps
   * the gate honest; otherwise one of them would slip through silently and
   * the user would learn from a 402 on submit.
   *
   * `locked` is the subset of reasons that are a standing property of the
   * repository rather than of an in-flight request. It is what greys out the
   * cadence trigger and its items; `disabled` additionally covers the
   * transient ones.
   */
  const locked = !repo.sync_available || needsReingest;
  const disabled = isSubmitting || isSyncing || isActive || locked;

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
   *
   * A refusal is a normal outcome, not an exception: the backend answers 409
   * when there is no baseline commit to diff against, and that reasoning is
   * exactly what the user needs to see.
   */
  const handleSyncNow = async () => {
    setError(null);
    setIsSyncing(true);
    try {
      const result = await triggerSyncAction(repo.id);
      if (!result.ok) {
        setError(result.detail);
        return;
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to queue sync");
    } finally {
      setIsSyncing(false);
    }
  };

  const status = statusTile(repo, summary);

  return (
    <div className="flex flex-col gap-5 rounded-md border border-(--border) bg-(--card) p-5.5">
      <div className="flex items-center justify-between gap-4">
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="text-[15px]">
            Follow {repo.ingested_branch ?? "the branch"}
          </span>
          <span className="font-pixel text-[11px] tracking-[0.06em] text-(--subtle-foreground) uppercase">
            {repo.auto_update_enabled
              ? `On · checks ${formatInterval(repo.auto_update_interval_hours).toLowerCase()}`
              : "Off · updates only when you re-ingest"}
          </span>
        </span>
        <Switch
          checked={repo.auto_update_enabled}
          disabled={disabled}
          onChange={(e) => handleToggle(e.target.checked)}
          aria-label="Enable auto-update"
        />
      </div>

      {repo.auto_update_enabled && (
        <div className="rise flex flex-wrap items-center justify-between gap-3">
          <span
            id={`interval-${repo.id}`}
            className="font-pixel text-xs tracking-[0.1em] text-(--muted-foreground) uppercase"
          >
            Check every
          </span>
          <div
            role="radiogroup"
            aria-labelledby={`interval-${repo.id}`}
            className="flex divide-x divide-(--border) overflow-hidden rounded-sm border border-(--border)"
          >
            {INTERVAL_OPTIONS.map((opt) => {
              const on = opt.hours === repo.auto_update_interval_hours;
              return (
                <button
                  key={opt.hours}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  aria-label={opt.label}
                  disabled={isSubmitting || locked}
                  onClick={() => handleIntervalChange(opt.hours)}
                  className={`px-3.5 py-2.25 font-pixel text-[13px] hover:cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 ${
                    on
                      ? "bg-(--accent)/15 text-(--foreground)"
                      : "text-(--muted-foreground) hover:text-(--foreground)"
                  }`}
                >
                  {opt.hours}h
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <StatusTile label="Last update" value={repo.last_synced_at ? timeAgo(repo.last_synced_at) : "Never synced"} />
        <StatusTile
          label="Next check"
          value={
            repo.auto_update_enabled && repo.next_sync_at && !isActive
              ? timeAgo(repo.next_sync_at)
              : "—"
          }
        />
        <StatusTile label="Status" value={status.value} color={status.color} live={status.live} />
      </div>

      <StatusLine repo={repo} summary={summary} />

      <button
        type="button"
        onClick={handleSyncNow}
        disabled={disabled}
        className="ghost self-start rounded-sm border border-(--input) px-3.5 py-2.25 font-pixel text-xs tracking-[0.06em] text-zinc-300 uppercase hover:cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isSyncing ? "Queuing…" : "↻ Check now"}
      </button>

      {needsReingest ? (
        <p className="m-0 flex items-start gap-2 border-t border-white/8 pt-4 text-[13px] leading-normal text-(--muted-foreground)">
          <span aria-hidden="true" className="font-pixel text-(--warning)">
            !
          </span>
          <span>
            This repository was ingested before sync tracking existed, so there
            is no baseline commit to update from. Re-ingest it to record one and
            enable auto-update.
          </span>
        </p>
      ) : (
        !repo.sync_available && (
          <p className="m-0 flex items-start gap-2 border-t border-white/8 pt-4 text-[13px] leading-normal text-(--muted-foreground)">
            <span aria-hidden="true" className="font-pixel text-(--accent)">
              ⚿
            </span>
            <span>
              Syncing runs on your own API key.{" "}
              <Link
                href="/settings"
                className="text-(--accent) underline-offset-2 hover:underline"
              >
                Add one in settings
              </Link>
              .
            </span>
          </p>
        )
      )}

      {error && (
        <p role="alert" className="m-0 text-[13px] text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * Picks a human label for an interval.
 */
function formatInterval(hours: number): string {
  const match = INTERVAL_OPTIONS.find((opt) => opt.hours === hours);
  if (match) return match.label;
  return `Every ${hours} hours`;
}

/**
 * The Status tile's value: what the background updater is doing now.
 *
 * @param repo The repository.
 * @param summary The last sync's summary, if any.
 * @returns The label, its colour, and whether it is live.
 */
function statusTile(
  repo: Repository,
  summary: SyncSummary | null,
): { value: string; color: string; live: boolean } {
  if (ACTIVE_SYNC_STATUSES.has(repo.sync_status)) {
    return { value: "Updating", color: "#53eafd", live: true };
  }
  if (repo.last_sync_error || repo.sync_status === "failed") {
    return { value: "Failed", color: "#ef4444", live: false };
  }
  if (!repo.auto_update_enabled) {
    return { value: "Off", color: "#71717a", live: false };
  }
  const head = summary?.new_commit_sha ?? repo.ingested_commit_sha;
  return {
    value: head ? `Up to date · ${head.slice(0, 7)}` : "Up to date",
    color: "#22c55e",
    live: false,
  };
}

/** One of the three status tiles. */
function StatusTile({
  label,
  value,
  color,
  live = false,
}: {
  label: string;
  value: string;
  color?: string;
  live?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-sm border border-white/8 p-3">
      <span className="font-pixel text-[10px] tracking-[0.12em] text-(--subtle-foreground) uppercase">
        {label}
      </span>
      <span
        className="flex min-w-0 items-center gap-2 font-pixel text-sm"
        style={color ? { color } : undefined}
      >
        {color && (
          <span
            aria-hidden="true"
            className={`h-1.5 w-1.5 shrink-0 ${live ? "blink" : ""}`}
            style={{ background: color }}
          />
        )}
        <span className="truncate">{value}</span>
      </span>
    </div>
  );
}

/**
 * Renders the line that explains the last sync when it needs explaining.
 *
 * Three cases, in priority order:
 * 1. `last_sync_error` is set -- surface it (the backend writes the error
 *    string after a failed attempt).
 * 2. Auto-update has been auto-paused after consecutive failures -- say so.
 * 3. The last sync changed files -- say how many.
 *
 * "Never synced" and "Syncing…" are covered by the tiles above.
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
      <p className="m-0 flex items-center gap-2 text-[13px] text-red-300">
        <span aria-hidden="true" className="font-pixel text-red-400">
          !
        </span>
        <span className="truncate">{repo.last_sync_error}</span>
      </p>
    );
  }

  if (
    !repo.auto_update_enabled &&
    repo.consecutive_sync_failures >= 3 &&
    repo.last_synced_at
  ) {
    return (
      <p className="m-0 text-[13px] text-(--muted-foreground)">
        Paused after {repo.consecutive_sync_failures} consecutive failures
      </p>
    );
  }

  if (repo.last_synced_at && summary?.files_changed) {
    return (
      <p className="m-0 font-pixel text-[11px] tracking-[0.06em] text-(--subtle-foreground) uppercase">
        Last update changed {summary.files_changed}{" "}
        {summary.files_changed === 1 ? "file" : "files"}
      </p>
    );
  }

  return null;
}
