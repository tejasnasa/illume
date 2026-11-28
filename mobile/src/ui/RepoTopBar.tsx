/**
 * The repository's slim top bar.
 *
 * @module RepoTopBar
 *
 * A square back button, the repository's name with a one-line status
 * under it, and a square settings button. The name is split like the web
 * client's: the owner in grey, the repository in the foreground colour.
 */

import { Pressable, Text, View } from "react-native";

import { PIXEL_FONT } from "@/lib/fonts";
import { splitRepoName } from "@/lib/repoName";
import { isSyncActive, statusView } from "@/lib/repoStatus";
import { colors } from "@/theme/tokens";
import { PixelIcon } from "@/ui/PixelIcon";
import type Repository from "@/types/repository";

/** Side of the square buttons, in points. */
const BUTTON = 44;

/** Props for the {@link RepoTopBar} component. */
export interface RepoTopBarProps {
  /** The repository the bar describes. */
  repo: Repository;
  /** Called when the back button is pressed. */
  onBack: () => void;
  /** Called when the settings button is pressed. */
  onSettings: () => void;
}

/**
 * The status line text: state, then branch and short commit when known.
 *
 * @param repo - The repository.
 * @returns For example ``READY · main @ 3f2a91c``.
 */
export function statusLine(repo: Repository): string {
  const view = statusView(repo.status);
  const label = isSyncActive(repo.sync_status) ? "Updating" : view.label;
  const parts = [label.toUpperCase()];
  const sha = repo.ingested_commit_sha?.slice(0, 7);
  if (repo.ingested_branch) {
    parts.push(sha ? `${repo.ingested_branch} @ ${sha}` : repo.ingested_branch);
  } else if (sha) {
    parts.push(`@ ${sha}`);
  }
  return parts.join(" · ");
}

/**
 * A square bordered icon button.
 *
 * @param props - The test hook, accessible label, handler and icon.
 * @returns The button.
 */
function SquareButton({
  testID,
  label,
  onPress,
  icon,
}: {
  testID: string;
  label: string;
  onPress: () => void;
  icon: "back" | "gear";
}) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={{ width: BUTTON, height: BUTTON }}
      className="items-center justify-center rounded-sm border border-border bg-card active:bg-secondary"
    >
      <PixelIcon name={icon} size={16} color={colors.foreground} />
    </Pressable>
  );
}

/**
 * Render the top bar.
 *
 * @param props - The repository and the two handlers.
 * @returns The bar.
 */
export function RepoTopBar({ repo, onBack, onSettings }: RepoTopBarProps) {
  const { owner, name } = splitRepoName(repo.github_url, repo.name);
  const view = statusView(repo.status);

  return (
    <View
      testID="repo-top-bar"
      className="flex-row items-center gap-3 border-b border-border px-3 pb-2 pt-1"
    >
      <SquareButton
        testID="repo-back"
        label="Back to dashboard"
        onPress={onBack}
        icon="back"
      />

      <View className="min-w-0 flex-1">
        <Text
          testID="repo-name"
          numberOfLines={1}
          ellipsizeMode="tail"
          style={{ fontFamily: PIXEL_FONT }}
          className="text-base text-foreground"
        >
          {owner ? (
            <Text className="text-subtle-foreground">{owner}/</Text>
          ) : null}
          <Text>{name}</Text>
        </Text>
        <View
          testID="repo-header-status"
          accessibilityLabel={`Status: ${view.label}`}
          className="mt-0.5 flex-row items-center gap-1.5"
        >
          <View style={{ width: 6, height: 6, backgroundColor: view.color }} />
          <Text
            numberOfLines={1}
            style={{ fontFamily: PIXEL_FONT, color: colors.mutedForeground }}
            className="shrink text-[10px] uppercase tracking-[1px]"
          >
            {statusLine(repo)}
          </Text>
        </View>
      </View>

      <SquareButton
        testID="repo-settings"
        label="Repository settings"
        onPress={onSettings}
        icon="gear"
      />
    </View>
  );
}

export default RepoTopBar;
