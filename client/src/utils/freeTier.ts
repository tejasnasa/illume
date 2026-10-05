/**
 * Free-tier banner visibility policy, shared by the banner and the pages that
 * lay content out around it.
 * @module FreeTierVisibility
 */

import User from "@/types/user";

/**
 * Resolves whether the free-tier banner is worth showing at all.
 *
 * Hidden when:
 * - the user has a saved BYOK key (the gate no longer applies), or
 * - the free ingestion allowance is spent AND the free chat allowance is
 *   also spent (the user is functionally outside the free tier and the next
 *   step is /settings, which the navbar already surfaces; showing it twice
 *   is noise).
 *
 * The caps come from the server (`free_ingestions_limit` /
 * `free_chat_messages_limit` on /auth/me), so tuning the policy in
 * `app/services/entitlements.py` moves the banner's threshold with it.
 *
 * This lives outside the component because the dashboard has to know whether
 * the banner will occupy a grid cell before it renders the grid.
 *
 * @param user - Current user, carrying `has_ai_key` and the free-tier counters.
 * @returns True when the banner should render.
 */
export function shouldShowFreeTierBanner(user: User): boolean {
  if (user.has_ai_key) return false;
  const ingestSpent = user.free_ingestions_used >= user.free_ingestions_limit;
  const chatSpent =
    user.free_chat_messages_used >= user.free_chat_messages_limit;
  return !(ingestSpent && chatSpent);
}
