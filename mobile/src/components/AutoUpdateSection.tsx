/**
 * Auto-update settings and live status for an ingested repository.
 *
 * @module AutoUpdateSection
 *
 * Port of ``client/src/components/AutoUpdateSection.tsx``. The web panel
 * renders the interval as a dropdown menu; on a phone that becomes a list
 * of radio rows inside a modal, which is the idiom that behaves the same
 * on both platforms.
 *
 * The panel is honest about what it cannot do:
 *
 * - A repository ingested before sync tracking existed has no baseline
 *   commit to diff against, so the controls are locked and the reason is
 *   stated rather than turning a click into a 409.
 * - A keyless free tier cannot pay for a sync, so the controls are locked
 *   and the panel points at the credentials screen.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  Switch,
  Text,
  View,
} from "react-native";

import { AUTO_UPDATE_INTERVALS, useAutoUpdate } from "@/hooks/useAutoUpdate";
import type { SettingsRequestOptions } from "@/api/settings";
import { timeAgo } from "@/lib/timeAgo";
import { colors } from "@/theme/tokens";
import type Repository from "@/types/repository";

/**
 * The shape of ``last_sync_summary`` as written by the backend.
 *
 * Narrowed here so the section renders exactly the fields it knows about
 * and ignores anything else the JSONB grows in the future.
 */
interface SyncSummary {
  /** How many files the sync changed. */
  files_changed?: number;
  /** How many files the sync added. */
  files_upserted?: number;
  /** How many files the sync removed. */
  files_deleted?: number;
}

/**
 * Props for the AutoUpdateSection component.
 */
export interface AutoUpdateSectionProps {
  /** The repository whose settings are shown. */
  repo: Repository;
  /** Transport overrides, so a test can inject a backend and a fetch. */
  options?: SettingsRequestOptions;
  /** Called after a successful change, so the caller can refresh. */
  onChanged?: (repo: Repository) => void;
}

/**
 * Draw the auto-update panel.
 *
 * @param props - The repository and the transport overrides.
 * @returns The rendered panel.
 */
export function AutoUpdateSection({
  repo,
  options,
  onChanged,
}: AutoUpdateSectionProps) {
  const {
    enabled,
    intervalHours,
    isSyncActive,
    isSubmitting,
    isSyncing,
    error,
    setEnabled,
    setIntervalHours,
    syncNow,
  } = useAutoUpdate({
    repoId: repo.id,
    enabled: repo.auto_update_enabled,
    intervalHours: repo.auto_update_interval_hours,
    syncStatus: repo.sync_status,
    options,
    onChanged,
  });

  const [pickerOpen, setPickerOpen] = useState(false);

  /**
   * A sync diffs the repository against its recorded baseline commit, so a
   * repository ingested before that watermark existed has nothing to diff
   * against and the backend refuses the request outright. Offering the
   * controls anyway only turns a click into an error.
   */
  const needsReingest = !repo.ingested_commit_sha;

  /**
   * The keyless free tier cannot pay for a sync. The backend reports this
   * as ``sync_available`` rather than leaving the client to work it out.
   */
  const locked = !repo.sync_available || needsReingest;
  const disabled = isSubmitting || isSyncing || isSyncActive || locked;

  const summary = (repo.last_sync_summary ?? null) as SyncSummary | null;

  return (
    <View
      testID="auto-update-section"
      className="rounded border border-primary/20 bg-card p-4"
    >
      <Text className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-primary">
        Auto-Update
      </Text>

      <View className="flex-row items-start justify-between gap-3">
        <View className="min-w-0 flex-1">
          <Text className="text-[13px] font-medium text-foreground">
            Keep analysis current
          </Text>
          <Text className="mt-0.5 text-xs text-muted-foreground">
            Periodically check the repository for new commits and update the
            graph, glossary, and embeddings in the background.
          </Text>
        </View>
        <Switch
          testID="auto-update-switch"
          accessibilityLabel="Enable auto-update"
          accessibilityRole="switch"
          accessibilityState={{ disabled }}
          value={enabled}
          disabled={disabled}
          onValueChange={(next) => {
            void setEnabled(next);
          }}
          trackColor={{ false: colors.secondary, true: colors.primary }}
          thumbColor={colors.foreground}
        />
      </View>

      {enabled ? (
        <View className="mt-4 flex-row items-center justify-between">
          <Text className="text-xs text-muted-foreground">Interval</Text>
          <Pressable
            testID="auto-update-interval"
            accessibilityRole="button"
            accessibilityLabel="Choose the auto-update interval"
            accessibilityState={{ disabled: locked }}
            disabled={locked}
            onPress={() => setPickerOpen(true)}
            className="min-h-[44px] flex-row items-center gap-1.5 rounded border border-border px-3 active:bg-secondary"
          >
            <Text className="text-xs text-foreground">
              {formatInterval(intervalHours)}
            </Text>
            <Text className="text-[10px] text-muted-foreground">▾</Text>
          </Pressable>
        </View>
      ) : null}

      <View className="mt-4 flex-row items-center justify-between gap-3 border-t border-border/60 pt-4">
        <View className="min-w-0 flex-1">
          <Text className="text-[13px] font-medium text-foreground">
            Sync now
          </Text>
          <StatusLine
            repo={repo}
            summary={summary}
            isSyncActive={isSyncActive}
          />
        </View>
        <Pressable
          testID="auto-update-sync-now"
          accessibilityRole="button"
          accessibilityLabel="Sync now"
          accessibilityState={{ disabled }}
          disabled={disabled}
          onPress={() => {
            // Refetch after queueing: the hook sets its own ``queued``
            // status, and without a server read that status would never
            // clear, leaving the controls disabled for the rest of the
            // session.
            void syncNow().then((ok) => {
              if (ok) onChanged?.(repo);
            });
          }}
          className="min-h-[44px] shrink-0 items-center justify-center rounded bg-primary px-3 active:opacity-80"
        >
          {isSyncing ? (
            <ActivityIndicator size="small" color={colors.primaryForeground} />
          ) : (
            <Text className="text-[13px] font-semibold text-primary-foreground">
              Sync now
            </Text>
          )}
        </Pressable>
      </View>

      {needsReingest ? (
        <Text className="mt-3 text-xs text-muted-foreground">
          This repository was ingested before sync tracking existed, so there is
          no baseline commit to update from. Re-ingest it to record one and
          enable auto-update.
        </Text>
      ) : !repo.sync_available ? (
        <Text className="mt-3 text-xs text-muted-foreground">
          Syncing runs on your own API key. Add one in AI credentials to enable
          it.
        </Text>
      ) : null}

      {error ? (
        <View
          testID="auto-update-error"
          className="mx-0 mb-0 mt-3 rounded border border-destructive/30 bg-destructive/10 p-3"
        >
          <Text className="text-xs text-destructive">{error}</Text>
        </View>
      ) : null}

      <IntervalPicker
        open={pickerOpen}
        selectedHours={intervalHours}
        disabled={disabled}
        onClose={() => setPickerOpen(false)}
        onSelect={(hours) => {
          setPickerOpen(false);
          void setIntervalHours(hours);
        }}
      />
    </View>
  );
}

/**
 * Props for the repository chooser.
 */
export interface RepositoryPickerProps {
  /** The repositories to choose from. */
  repositories: Repository[];
  /** The UUID of the chosen repository, if one is chosen. */
  selectedId?: string | null;
  /** Called with the chosen repository. */
  onSelect: (repo: Repository) => void;
  /** The heading shown above the list. */
  label?: string;
  /** Whether the list is still loading. */
  isLoading?: boolean;
  /** The failure message when the list could not be read, if it failed. */
  error?: string | null;
  /** Retry the failed list request. */
  onRetry?: () => void;
}

/**
 * A list of the caller's repositories, one of which is chosen.
 *
 * The repository-scoped settings screens -- auto-update and the danger
 * zone -- both act on one repository, and the phone has no repository
 * context of its own the way the web navbar does, so the choice is made
 * here.
 *
 * @param props - The repositories, the selection and the callback.
 * @returns The rendered list.
 */
export function RepositoryPicker({
  repositories,
  selectedId,
  onSelect,
  label = "Repository",
  isLoading = false,
  error = null,
  onRetry,
}: RepositoryPickerProps) {
  if (isLoading) {
    return (
      <View className="items-center justify-center py-8">
        <ActivityIndicator size="small" color={colors.foreground} />
      </View>
    );
  }

  // A failed request is not an empty account. Saying "no repositories" here
  // would send the reader to ingest one they already have.
  if (error) {
    return (
      <View testID="repository-picker-error" className="py-4">
        <Text className="text-center text-[13px] text-destructive">
          {error}
        </Text>
        {onRetry ? (
          <Pressable
            testID="repository-picker-retry"
            accessibilityRole="button"
            accessibilityLabel="Try loading the repositories again"
            onPress={onRetry}
            className="mt-3 min-h-[44px] items-center justify-center self-center rounded border border-border px-4 py-2 active:bg-secondary"
          >
            <Text className="text-[13px] font-semibold text-foreground">
              Try again
            </Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  if (repositories.length === 0) {
    return (
      <Text
        testID="repository-picker-empty"
        className="py-6 text-center text-[13px] text-muted-foreground"
      >
        No repositories yet. Ingest one from the dashboard first.
      </Text>
    );
  }

  return (
    <View testID="repository-picker">
      <Text className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </Text>
      {repositories.map((repo) => {
        const selected = repo.id === selectedId;
        return (
          <Pressable
            key={repo.id}
            testID={`repository-picker-item-${repo.repo_number}`}
            accessibilityRole="radio"
            accessibilityLabel={repo.name}
            accessibilityState={{ selected }}
            onPress={() => onSelect(repo)}
            className="min-h-[44px] flex-row items-center justify-between border-b border-border/60 active:bg-secondary"
          >
            <View className="min-w-0 flex-1 pr-3">
              <Text
                className="text-sm font-medium text-foreground"
                numberOfLines={1}
              >
                {repo.name}
              </Text>
              <Text className="mt-0.5 text-[11px] text-muted-foreground">
                {repo.status.charAt(0).toUpperCase() + repo.status.slice(1)}
              </Text>
            </View>
            <Text
              className={`text-sm ${
                selected ? "text-primary" : "text-muted-foreground"
              }`}
            >
              {selected ? "●" : "○"}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/**
 * Pick a human label for a cadence.
 *
 * @param hours - The cadence, in hours.
 * @returns The label to show.
 */
function formatInterval(hours: number): string {
  const match = AUTO_UPDATE_INTERVALS.find((option) => option.hours === hours);
  if (match) return match.label;
  return `Every ${hours} hours`;
}

/**
 * Props for the status line.
 */
interface StatusLineProps {
  /** The repository the line describes. */
  repo: Repository;
  /** The summary of the last sync, if there was one. */
  summary: SyncSummary | null;
  /** Whether a sync is in flight. */
  isSyncActive: boolean;
}

/**
 * The one-line summary of the last sync's outcome.
 *
 * Four branches, in priority order:
 *
 * 1. ``last_sync_error`` is set -- surface it; the backend writes the
 *    error string after a failed attempt.
 * 2. A sync is in flight -- say so.
 * 3. Auto-update was auto-paused after consecutive failures -- say so.
 * 4. Otherwise: when the repository was last updated, and how many files
 *    the sync touched.
 *
 * @param props - The repository and the status to render.
 * @returns The rendered line.
 */
function StatusLine({ repo, summary, isSyncActive }: StatusLineProps) {
  if (repo.last_sync_error) {
    return (
      <Text
        testID="auto-update-status"
        className="mt-0.5 text-xs text-destructive"
        numberOfLines={2}
      >
        {repo.last_sync_error}
      </Text>
    );
  }

  if (isSyncActive) {
    return (
      <Text
        testID="auto-update-status"
        className="mt-0.5 text-xs text-muted-foreground"
      >
        Syncing…
      </Text>
    );
  }

  if (
    !repo.auto_update_enabled &&
    repo.consecutive_sync_failures >= 3 &&
    repo.last_synced_at
  ) {
    return (
      <Text
        testID="auto-update-status"
        className="mt-0.5 text-xs text-muted-foreground"
      >
        Paused after {repo.consecutive_sync_failures} consecutive failures
      </Text>
    );
  }

  if (!repo.last_synced_at) {
    return (
      <Text
        testID="auto-update-status"
        className="mt-0.5 text-xs text-muted-foreground"
      >
        Never synced
      </Text>
    );
  }

  const changed = summary?.files_changed ?? 0;

  return (
    <Text
      testID="auto-update-status"
      className="mt-0.5 text-xs text-muted-foreground"
    >
      Updated {timeAgo(repo.last_synced_at)}
      {changed > 0
        ? ` · ${changed} file${changed === 1 ? "" : "s"} changed`
        : ""}
    </Text>
  );
}

/**
 * Props for the interval picker modal.
 */
interface IntervalPickerProps {
  /** Whether the modal is on screen. */
  open: boolean;
  /** The cadence currently in force. */
  selectedHours: number;
  /** Whether the picker is locked. */
  disabled: boolean;
  /** Called when the modal is dismissed. */
  onClose: () => void;
  /** Called with the chosen cadence, in hours. */
  onSelect: (hours: number) => void;
}

/**
 * The cadence chooser.
 *
 * @param props - The modal's state and its two callbacks.
 * @returns The rendered modal.
 */
function IntervalPicker({
  open,
  selectedHours,
  disabled,
  onClose,
  onSelect,
}: IntervalPickerProps) {
  return (
    <Modal
      visible={open}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close interval picker"
        onPress={onClose}
        className="flex-1 justify-end bg-black/60"
      >
        <Pressable
          accessibilityRole="none"
          onPress={() => {}}
          className="rounded-t-2xl border-t border-border bg-card p-4"
        >
          <Text className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Sync interval
          </Text>

          {AUTO_UPDATE_INTERVALS.map((option) => {
            const selected = option.hours === selectedHours;
            return (
              <Pressable
                key={option.hours}
                testID={`auto-update-interval-option-${option.hours}`}
                accessibilityRole="radio"
                accessibilityLabel={option.label}
                accessibilityState={{ selected, disabled }}
                disabled={disabled}
                onPress={() => onSelect(option.hours)}
                className="min-h-[44px] flex-row items-center justify-between border-b border-border/60 active:bg-secondary"
              >
                <Text className="text-sm text-foreground">{option.label}</Text>
                <Text
                  className={`text-sm ${
                    selected ? "text-primary" : "text-muted-foreground"
                  }`}
                >
                  {selected ? "●" : "○"}
                </Text>
              </Pressable>
            );
          })}

          <Pressable
            testID="auto-update-interval-close"
            accessibilityRole="button"
            accessibilityLabel="Close interval picker"
            onPress={onClose}
            className="mt-3 min-h-[44px] items-center justify-center rounded border border-border active:bg-secondary"
          >
            <Text className="text-[13px] font-medium text-foreground">
              Cancel
            </Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

export default AutoUpdateSection;
