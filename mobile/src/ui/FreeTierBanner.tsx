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

import { resolveFreeTierMessage, shouldShowFreeTierBanner } from "@/lib/freeTier";
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
export function FreeTierBanner({ user, testID = "free-tier-banner" }: FreeTierBannerProps) {
  if (!user || !shouldShowFreeTierBanner(user)) return null;

  const { title, ctaLabel, tone } = resolveFreeTierMessage(user);

  const palette =
    tone === "primary"
      ? "border-primary/30 bg-primary/10"
      : "border-primary/20 bg-secondary/30";

  return (
    <View
      testID={testID}
      accessibilityRole="text"
      accessibilityLabel={title}
      className={`mb-3 items-center justify-center rounded border p-5 ${palette}`}
    >
      <Text className="text-center text-[40px] opacity-40">✦</Text>
      <Text className="mb-2 mt-1 text-center text-base font-semibold text-foreground">
        {title}
      </Text>
      <Pressable
        testID="free-tier-cta"
        accessibilityRole="link"
        accessibilityLabel={ctaLabel}
        onPress={() => router.push("/(app)/settings")}
        className="shrink-0 rounded border border-border px-4 py-3"
      >
        <Text className="text-xs font-semibold text-primary">{ctaLabel}</Text>
      </Pressable>
    </View>
  );
}

export default FreeTierBanner;
