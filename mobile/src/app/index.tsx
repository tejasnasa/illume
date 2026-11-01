/**
 * Entry route.
 *
 * Decides where a cold start lands. There are three destinations:
 *
 * - the dashboard, when a session is held;
 * - the onboarding carousel, when there is no session and the carousel has
 *   not been seen yet;
 * - the login screen, when there is no session and the carousel has been
 *   seen.
 *
 * Both facts arrive asynchronously, and the order matters. A returning
 * signed-in reader must not be held up by the carousel, so the session is
 * resolved first and the flag is only read when there is no session at all.
 * A signed-in cold start therefore costs one secure-store read and no more.
 */

import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { router } from "expo-router";

import { useAuth } from "@/hooks/useAuth";
import { hasSeenOnboarding } from "@/lib/onboardingFlag";
import { colors } from "@/theme/tokens";

/** Where a cold start can land. */
type EntryDestination = "/(app)/dashboard" | "/onboarding" | "/login";

export default function Index() {
  const { loading, token } = useAuth();
  const [onboardingSeen, setOnboardingSeen] = useState<boolean | null>(null);

  useEffect(() => {
    // The session has not resolved yet; there is nothing to decide.
    if (loading) return;
    // A session is held, so the carousel is irrelevant. Skipping the read
    // is what keeps the dashboard one step away instead of two.
    if (token) return;

    let cancelled = false;
    void (async () => {
      const seen = await hasSeenOnboarding();
      if (!cancelled) setOnboardingSeen(seen);
    })();

    return () => {
      cancelled = true;
    };
  }, [loading, token]);

  const destination = useMemo<EntryDestination | null>(() => {
    if (loading) return null;
    if (token) return "/(app)/dashboard";
    // The flag has not been read yet.
    if (onboardingSeen === null) return null;
    return onboardingSeen ? "/login" : "/onboarding";
  }, [loading, onboardingSeen, token]);

  useEffect(() => {
    if (!destination) return;
    router.replace(destination);
  }, [destination]);

  // The decision takes a moment (a secure-store read, and possibly the
  // seen-flag read). Render the app's own background and a spinner rather
  // than ``null``: on a cold start the splash has already been dismissed by
  // the time this screen mounts on some Android builds, and ``null`` leaves
  // a blank frame.
  return (
    <View
      testID="entry-loading"
      className="flex-1 items-center justify-center bg-background"
    >
      <ActivityIndicator size="large" color={colors.foreground} />
    </View>
  );
}
