/**
 * The repository's ingestion status, as a pill.
 *
 * @module RepoStatusBadge
 *
 * A square-cornered chip with a status dot, in the pixel font.
 * Port of the status badge in ``client/src/components/RepoNavbar.tsx``. The
 * web badge is green whatever the status -- including for a failed
 * repository -- so the mobile version colours by status instead, matching the
 * dashboard's :component:`RepoCard` rather than contradicting it.
 *
 * A spinning indicator appears next to the text while a background sync is
 * running, because a sync deliberately leaves ``status='ready'`` alone and
 * the badge is the only place the reader can see that anything is
 * happening.
 */

import { ActivityIndicator, Text, View } from "react-native";

import { PIXEL_FONT } from "@/lib/fonts";
import { isSyncActive, statusView } from "@/lib/repoStatus";
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
  const view = statusView(status);
  const syncing = isSyncActive(syncStatus);

  return (
    <View
      testID={testID}
      accessibilityRole="text"
      accessibilityLabel={`Status: ${status}`}
      className="flex-row items-center gap-1.5 border px-2 py-1"
      style={{ borderColor: `${view.color}66` }}
    >
      {syncing ? (
        <ActivityIndicator
          size="small"
          color={colors.chart1}
          style={styles.spinner}
        />
      ) : (
        <View style={{ width: 6, height: 6, backgroundColor: view.color }} />
      )}
      <Text
        className="text-[11px] uppercase tracking-[1px]"
        style={{ fontFamily: PIXEL_FONT, color: view.color }}
      >
        {status}
      </Text>
    </View>
  );
}

// NativeWind has no spinner scale; the ``ActivityIndicator`` keeps an
// inline transform so the pill stays a tight horizontal row.
const styles = {
  spinner: { transform: [{ scale: 0.6 }] },
} as const;

export default RepoStatusBadge;
