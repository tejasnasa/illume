/**
 * Free-tier banner visibility policy and copy.
 *
 * @module FreeTierPolicy
 *
 * Port of ``client/src/utils/freeTier.ts`` plus the message resolution that
 * lives inside ``client/src/components/FreeTierBanner.tsx`` on the web. The
 * copy is contract: the server ships the counters on ``/auth/me`` and the
 * threshold lives in ``app/services/entitlements.py``, so the UI never
 * carries a second copy of the cap that could drift.
 *
 * Kept out of the component because the dashboard has to know whether the
 * banner will render before it lays the list out, and because the copy is
 * worth unit-testing without mounting a tree.
 */

import User from "@/types/user";

/**
 * Resolves whether the free-tier banner is worth showing at all.
 *
 * Hidden when:
 * - the user has a saved BYOK key (the quota gate no longer applies), or
 * - the free ingestion allowance is spent AND the free chat allowance is
 *   also spent (the user is functionally outside the free tier).
 *
 * The comparison is ``>=`` so a counter that has run past its cap still
 * counts as spent.
 *
 * @param user - Current user, carrying ``has_ai_key`` and the counters.
 * @returns True when the banner should render.
 */
export function shouldShowFreeTierBanner(user: User): boolean {
  if (user.has_ai_key) return false;
  const ingestSpent = user.free_ingestions_used >= user.free_ingestions_limit;
  const chatSpent =
    user.free_chat_messages_used >= user.free_chat_messages_limit;
  return !(ingestSpent && chatSpent);
}

/** Copy and tone for the free-tier banner. */
export interface FreeTierMessage {
  /** Headline shown in the banner. */
  title: string;
  /** Label of the call-to-action button. */
  ctaLabel: string;
  /**
   * ``primary`` while ingestion slots remain, ``muted`` once they are
   * spent. The banner tints its border and background from this.
   */
  tone: "primary" | "muted";
}

/**
 * Builds the copy and primary CTA based on what is left.
 *
 * While ingestion slots remain the banner keeps the onboarding tone, counting
 * the slots once any have been spent. At the cap it switches to the muted
 * "add a key" prompt, since no free ingest is left to offer. Both branches
 * send the user to settings -- the next meaningful action is to save a key.
 *
 * @param user - Current user, carrying the free-tier counters.
 * @returns The title, CTA label, and tone for the banner.
 */
export function resolveFreeTierMessage(user: User): FreeTierMessage {
  const remaining = user.free_ingestions_limit - user.free_ingestions_used;

  if (remaining > 0) {
    return {
      title:
        user.free_ingestions_used === 0
          ? "You're on the free tier"
          : `${user.free_ingestions_used} of ${user.free_ingestions_limit} free ingestions used`,
      ctaLabel: "Add your own API key",
      tone: "primary",
    };
  }

  return {
    title: "Free Ingestions Used",
    ctaLabel: "Add your own API key to continue",
    tone: "muted",
  };
}
