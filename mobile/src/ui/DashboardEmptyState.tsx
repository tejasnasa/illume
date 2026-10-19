/**
 * Empty state for the dashboard list.
 *
 * @module DashboardEmptyState
 *
 * Mirrors the dashed-bordered block in ``dashboard/page.tsx``: a centred
 * icon, a single line of copy ("No repositories found. Add your first one
 * to get started!"), and the same dashed card visual. ``Add New Repository``
 * is a separate affordance -- the screen routes the tap to that flow in
 * Phase 5; the empty state itself stays a status message, not a button, to
 * keep the connection between the two screens obvious.
 */

import { Text, View } from "react-native";

const ICON = "🗄️";

export interface DashboardEmptyStateProps {
  /** Optional override for the testID; default is a stable value for tests. */
  testID?: string;
}

/**
 * Render the empty state in place of the list.
 *
 * The dashed border + tinted background echoes the web version. The icon
 * is a single emoji rather than an icon library; the plan calls for the
 * "copy" to port, not the visual flourish, and the web version's
 * 40-px Phosphor icon needs no replacement at this scale.
 */
export function DashboardEmptyState({
  testID = "dashboard-empty",
}: DashboardEmptyStateProps) {
  return (
    <View
      testID={testID}
      accessibilityRole="text"
      accessibilityLabel="No repositories found"
      className="min-h-[144px] items-center justify-center gap-3 border-2 border-dashed border-border bg-secondary/5 px-6 py-8"
    >
      <Text className="text-[40px] opacity-40">{ICON}</Text>
      <Text className="text-center text-sm text-muted-foreground">
        No repositories found. Add your first one to get started!
      </Text>
    </View>
  );
}
