/**
 * Dashboard banner for users on the keyless free tier.
 *
 * Two states: free ingestions are still available (call to action: start
 * now), or the allowance is spent and there is no BYOK key yet (call to
 * action: add one in settings). BYOK users do not see the banner at all --
 * the quota gate does not apply once a key is set.
 *
 * @module FreeTierBanner
 */
"use client";

import { MoonStarsIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import User from "@/types/user";
import { shouldShowFreeTierBanner } from "@/utils/freeTier";

/**
 * Props for the FreeTierBanner component.
 */
type Props = {
  user: User;
};

/**
 * Builds the copy and primary CTA based on what is left.
 *
 * While ingestion slots remain the banner keeps the onboarding tone, counting
 * the slots once any have been spent. At the cap it switches to the muted
 * "add a key" prompt, since no free ingest is left to offer. Both branches
 * send the user to /settings -- the next meaningful action is to save a key.
 */
function resolveMessage(user: User) {
  const remaining = user.free_ingestions_limit - user.free_ingestions_used;

  if (remaining > 0) {
    return {
      title:
        user.free_ingestions_used === 0
          ? "You're on the free tier"
          : `${user.free_ingestions_used} of ${user.free_ingestions_limit} free ingestions used`,
      ctaLabel: "Add your own API key",
      ctaHref: "/settings",
      tone: "primary",
    } as const;
  }

  return {
    title: "Free Ingestions Used",
    ctaLabel: "Add your own API key to continue",
    ctaHref: "/settings",
    tone: "muted",
  } as const;
}

/**
 * Renders the dashboard free-tier banner when the user is on the keyless
 * plan and has any allowance left. Returns `null` otherwise -- the banner
 * is opt-in, not a panel that hides empty.
 *
 * @param user - Current user; provides `has_ai_key`, the free-tier
 *               counters, and the call to action surfaces.
 * @returns The rendered banner, or `null` when not applicable.
 */
export default function FreeTierBanner({ user }: Props) {
  if (!shouldShowFreeTierBanner(user)) return null;

  const { title, ctaLabel, ctaHref, tone } = resolveMessage(user);

  const palette =
    tone === "primary"
      ? "border-(--primary)/30 bg-(--primary)/5 text-(--primary)"
      : "border-(--primary)/20 bg-(--secondary)/30 text-(--muted-foreground)";

  return (
    <div
      role="status"
      data-testid="free-tier-banner"
      className={`group relative glass-card rounded-sm p-6 block hover:border-(--primary)/50 transition-all duration-300 hover:shadow-xl hover:shadow-(--primary)/5 ${palette} flex flex-col items-center justify-around `}
    >
      <MoonStarsIcon size={120} weight="duotone" className="mt-0.5 shrink-0" />
      <p className="font-semibold text-(--foreground) text-xl mb-2">{title}</p>
      <Link
        href={ctaHref}
        className="shrink-0 self-center text-xs font-semibold text-(--primary) underline-offset-2 hover:bg-(--card) transition border border-(--border) py-3 px-4 rounded-sm"
      >
        {ctaLabel}
      </Link>
    </div>
  );
}
