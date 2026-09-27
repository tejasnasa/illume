/**
 * Dashboard banner for users on the keyless free tier.
 *
 * Two states: the free ingestion is still unused (call to action: start
 * now), or it has been burned and there is no BYOK key yet (call to action:
 * add one in settings). BYOK users do not see the banner at all -- the
 * quota gate does not apply once a key is set.
 *
 * @module FreeTierBanner
 */
"use client";

import { MoonStarsIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import User from "@/types/user";

/**
 * The numbers the entitlement layer grants on the dashboard / chat path.
 * Both must match the server-side `FREE_INGESTIONS` and `FREE_CHAT_MESSAGES`
 * in `app/services/entitlements.py` -- the banner mirrors them so a future
 * cap change moves both at once.
 */
const FREE_INGESTIONS = 1;
const FREE_CHAT_MESSAGES = 5;

/**
 * Props for the FreeTierBanner component.
 */
type Props = {
  user: User;
};

/**
 * Resolves whether the banner is worth showing at all.
 *
 * Hidden when:
 * - the user has a saved BYOK key (the gate no longer applies), or
 * - the free ingestion allowance is spent AND the free chat allowance is
 *   also spent (the user is functionally outside the free tier and the next
 *   step is /settings, which the navbar already surfaces; showing it twice
 *   is noise).
 *
 * `FREE_INGESTIONS` is the per-user grant: a value of 1 means the boolean
 * `free_ingest_used` flips to `true` the moment the slot is consumed, so the
 * banner stays up exactly while that one slot is still available. Should
 * the grant ever move to N, the same intent ("banner visible while any
 * slot remains") becomes `ingestSpent < FREE_INGESTIONS`, computed off the
 * same counter on the user row -- so the constant is what couples this
 * check to the server-side `FREE_INGESTIONS` in
 * `app/services/entitlements.py`.
 */
function shouldShow(user: User): boolean {
  if (user.has_ai_key) return false;
  // Boolean today: with the grant of 1, `free_ingest_used === true` means
  // the single slot has been spent. Casting through a number makes the
  // expression slot-comparable: 0 slots used when false, 1 when true.
  const ingestSpent = user.free_ingest_used ? FREE_INGESTIONS : 0;
  const chatSpent = user.free_chat_messages_used >= FREE_CHAT_MESSAGES;
  return !(ingestSpent >= FREE_INGESTIONS && chatSpent);
}

/**
 * Builds the copy and primary CTA based on what is left.
 *
 * The CTA is "/settings" once any allowance has been spent -- the next
 * meaningful action is "save a key" -- and otherwise points at the repo
 * picker so a fresh user lands on the path the product is laid out for.
 */
function resolveMessage(user: User) {
  if (!user.free_ingest_used) {
    return {
      title: "You're on the free tier",
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
  if (!shouldShow(user)) return null;

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
      <p className="font-semibold text-(--foreground) text-xl">{title}</p>
      <Link
        href={ctaHref}
        className="shrink-0 self-center text-xs font-semibold text-(--primary) underline-offset-2 hover:bg-(--card) transition border border-(--border) py-3 px-4 rounded-sm"
      >
        {ctaLabel}
      </Link>
    </div>
  );
}
