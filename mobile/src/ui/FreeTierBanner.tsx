/**
 * Dashboard banner for users on the keyless free tier.
 *
 * @module FreeTierBanner
 *
 * Port of ``client/src/components/FreeTierBanner.tsx``. Two states: free
 * ingestions are still available (call to action: add a key so the
 * allowance stops mattering), or the allowance is spent and there is no
 * BYOK key yet (call to action: add one in settings). BYOK users do not
 * see the banner at all -- the quota gate does not apply once a key is
 * set.
 *
 * The web version links to ``/settings``; the mobile equivalent is the
 * ``(app)/settings`` route.
 */

import { Pressable, Text, View } from "react-native";
import { router } from "expo-router";

import { PIXEL_FONT, SANS_FONT } from "@/lib/fonts";
import {
  resolveFreeTierMessage,
  shouldShowFreeTierBanner,
} from "@/lib/freeTier";
import type User from "@/types/user";

/** Props for the FreeTierBanner component. */
export interface FreeTierBannerProps {
  /** Current user; provides ``has_ai_key`` and the free-tier counters. */
  user: User | null;
  /** Test hook. */
  testID?: string;
}

/**
 * Renders the dashboard free-tier banner when the user is on the keyless
 * plan and has any allowance left.
 *
 * @param user - Current user; provides the quota counters and plan.
 * @param testID - Test hook.
 * @returns The rendered banner, or ``null`` when not applicable.
 */
export function FreeTierBanner({
  user,
  testID = "free-tier-banner",
}: FreeTierBannerProps) {
  if (!user || !shouldShowFreeTierBanner(user)) return null;

  const { title, ctaLabel, tone } = resolveFreeTierMessage(user);

  const palette =
    tone === "primary"
      ? "border-accent/30 bg-primary/10"
      : "border-border bg-card";

  return (
    <View
      testID={testID}
      accessibilityRole="text"
      accessibilityLabel={title}
      className={`mb-3 gap-3 rounded-sm border p-4 ${palette}`}
    >
      <Text
        className="text-sm leading-[21px] text-foreground"
        style={{ fontFamily: SANS_FONT }}
      >
        {title}
      </Text>
      <Pressable
        testID="free-tier-cta"
        accessibilityRole="link"
        accessibilityLabel={ctaLabel}
        onPress={() => router.push("/(app)/settings")}
        className="min-h-[44px] self-start justify-center rounded-sm border border-border-strong px-4 active:bg-secondary"
      >
        <Text
          className="text-xs uppercase tracking-[1px] text-accent"
          style={{ fontFamily: PIXEL_FONT }}
        >
          {ctaLabel}
        </Text>
      </Pressable>
    </View>
  );
}

export default FreeTierBanner;
