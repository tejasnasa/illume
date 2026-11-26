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
          ? `You're on the free tier: ${user.free_ingestions_limit} ingestions on us. Add your own API key to keep going without limits.`
          : `${user.free_ingestions_used} of ${user.free_ingestions_limit} free ingestions used. Add your own API key to keep going without limits.`,
      ctaLabel: "Add a key",
      ctaHref: "/settings",
      tone: "primary",
    } as const;
  }

  return {
    title: `All ${user.free_ingestions_limit} free ingestions used. Add your own API key to ingest another repository.`,
    ctaLabel: "Add a key",
    ctaHref: "/settings",
    tone: "muted",
  } as const;
}

/**
 * Renders the dashboard's free-tier strip when the user is on the keyless
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
  const used = Math.min(user.free_ingestions_used, user.free_ingestions_limit);

  return (
    <div
      role="status"
      data-testid="free-tier-banner"
      className={`flex flex-wrap items-center gap-4 rounded-md border border-(--border) px-4 py-3.5 ${
        tone === "primary"
          ? "bg-[linear-gradient(90deg,#a3004c14,transparent_60%),var(--card)]"
          : "bg-(--card)"
      }`}
    >
      <span className="font-pixel text-xs tracking-[0.12em] text-(--accent) uppercase">
        Free tier
      </span>
      <span aria-hidden="true" className="flex gap-1">
        {Array.from({ length: user.free_ingestions_limit }, (_, i) => (
          <span
            key={i}
            className={`h-2 w-4.5 ${i < used ? "bg-(--accent)" : "bg-(--muted)"}`}
          />
        ))}
      </span>
      <p className="m-0 grow text-sm text-zinc-300">{title}</p>
      <Link
        href={ctaHref}
        className="font-pixel text-[13px] tracking-[0.06em] text-(--foreground) uppercase hover:text-(--accent)"
      >
        {ctaLabel} →
      </Link>
    </div>
  );
}
