/**
 * The repository's ingestion status, as a pill.
 *
 * @module RepoStatusBadge
 *
 * Port of the status badge in ``client/src/components/RepoNavbar.tsx``. The
 * web badge is green whatever the status -- including for a failed
 * repository -- so the mobile version colours by tone instead, matching the
 * dashboard's :component:`RepoCard` rather than contradicting it.
 *
 * A spinning indicator appears next to the text while a background sync is
 * running, because a sync deliberately leaves ``status='ready'`` alone and
 * the badge is the only place the reader can see that anything is
 * happening.
 */

import { ActivityIndicator, Text, View } from "react-native";

import { isSyncActive, statusTone } from "@/lib/repoStatus";
import { colors } from "@/theme/tokens";

/** Props for the {@link RepoStatusBadge} component. */
export interface RepoStatusBadgeProps {
  /** The repository's ingestion status. */
  status: string;
  /** The repository's background-sync status. */
  syncStatus?: string | null;
  /** Test hook. */
  testID?: string;
}

/**
 * Render the status pill.
 *
 * @param props - The status, the sync status and an optional test hook.
 * @returns The rendered pill.
 */
export function RepoStatusBadge({
  status,
  syncStatus,
  testID = "repo-status-badge",
}: RepoStatusBadgeProps) {
  const tone = statusTone(status);
  const syncing = isSyncActive(syncStatus);

  const pillClass =
    tone === "success"
      ? "bg-green-500/10"
      : tone === "destructive"
        ? "bg-red-500/10"
        : "bg-yellow-500/10";
  const labelClass =
    tone === "success"
      ? "text-green-500"
      : tone === "destructive"
        ? "text-red-500"
        : "text-yellow-500";

  return (
    <View
      testID={testID}
      accessibilityRole="text"
      accessibilityLabel={`Status: ${status}`}
      className={`flex-row items-center rounded-full px-2.5 py-1 ${pillClass}`}
    >
      {syncing ? (
        <ActivityIndicator
          size="small"
          color={colors.foreground}
          style={styles.spinner}
        />
      ) : null}
      <Text className={`text-[10px] font-bold uppercase tracking-widest ${labelClass}`}>
        {status}
      </Text>
    </View>
  );
}

// NativeWind has no spinner scale; the ``ActivityIndicator`` keeps an
// inline transform so the pill stays a tight horizontal row.
const styles = {
  spinner: { marginRight: 4, transform: [{ scale: 0.6 }] },
} as const;

export default RepoStatusBadge;
