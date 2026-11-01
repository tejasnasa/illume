/**
 * The onboarding route.
 *
 * @module OnboardingScreen
 *
 * Hosts the first-run carousel and decides where the reader lands when they
 * are done with it. Two destinations are possible:
 *
 * - ``/login`` -- the normal case. A first run has no account yet, so the
 *   carousel ends at the sign-in screen.
 * - ``/(app)/dashboard`` -- when a session is already held, for instance
 *   because the reader signed in on the web and then installed the app.
 *
 * Both exits record the "seen" flag before navigating. Skipping counts as
 * having seen it: the carousel is an introduction, and an introduction that
 * reappears on every launch is an irritation rather than a welcome.
 *
 * The carousel is reachable two ways, and they exit differently. On a fresh
 * install it is the app's first screen, so finishing it replaces itself
 * with the next destination. Reopened from the "?" on the sign-in screen it
 * sits on top of that screen, so finishing it just pops back -- replacing
 * would stack a second sign-in screen under the first.
 */

import { useCallback } from "react";
import { router } from "expo-router";

import { OnboardingCarousel } from "@/components/OnboardingCarousel";
import { useAuth } from "@/hooks/useAuth";
import { markOnboardingSeen } from "@/lib/onboardingFlag";

export default function OnboardingScreen() {
  const { token } = useAuth();

  /**
   * Record the carousel as seen and send the reader on their way.
   *
   * The flag is written first so a cold start during the navigation still
   * knows the carousel is done.
   */
  const finish = useCallback(async () => {
    await markOnboardingSeen();

    // Opened from the sign-in screen, there is somewhere to go back to.
    // On a fresh install the carousel replaced the entry route, so there is
    // not, and it has to name the destination itself.
    if (router.canGoBack()) {
      router.back();
      return;
    }

    router.replace(token ? "/(app)/dashboard" : "/login");
  }, [token]);

  return (
    <OnboardingCarousel
      onSkip={() => {
        void finish();
      }}
      onComplete={() => {
        void finish();
      }}
    />
  );
}
