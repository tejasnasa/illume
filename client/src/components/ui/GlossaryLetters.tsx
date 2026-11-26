/**
 * The glossary's A to Z rail: one link per initial, filtering every page.
 * @module GlossaryLetters
 */
import Link from "next/link";

/** Every initial the rail offers, in order; `#` collects names that start with anything else. */
export const GLOSSARY_INITIALS = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ", "#"];

/** One rail cell, each on its own card; the active one is tinted, the empty ones are dimmed. */
const CELL =
  "flex h-8 min-w-8 items-center justify-center rounded-sm border px-2 font-pixel text-xs tracking-[0.06em] uppercase";

/**
 * Reads a `letter` query value as one of the rail's initials.
 *
 * @param value - The raw query value, if any.
 * @returns The initial in upper case, or null when it is missing or not one.
 */
export function parseInitial(value: string | undefined): string | null {
  const upper = (value ?? "").toUpperCase();
  return GLOSSARY_INITIALS.includes(upper) ? upper : null;
}

/**
 * Renders the rail. Initials with no terms stay visible but inert, so the
 * rail keeps its shape whatever the glossary holds.
 *
 * @param active - The initial being filtered by, or null for all of them.
 * @param present - Initials that have at least one term.
 * @param hrefFor - Builds the link for an initial, or for all terms when null.
 * @returns The rail.
 */
export default function GlossaryLetters({
  active,
  present,
  hrefFor,
}: {
  active: string | null;
  present: string[];
  hrefFor: (letter: string | null) => string;
}) {
  const available = new Set(present);
  return (
    <nav aria-label="Filter by letter" className="flex flex-wrap gap-1">
      <Link
        href={hrefFor(null)}
        aria-current={active === null ? "page" : undefined}
        className={`${CELL} ${
          active === null
            ? "border-(--accent) bg-[color-mix(in_srgb,var(--accent)_14%,var(--card))] text-(--accent)"
            : "border-(--border) bg-(--card) text-zinc-300 hover:border-white/25 hover:bg-(--secondary)"
        }`}
      >
        All
      </Link>
      {GLOSSARY_INITIALS.map((letter) =>
        available.has(letter) || letter === active ? (
          <Link
            key={letter}
            href={hrefFor(letter)}
            aria-current={letter === active ? "page" : undefined}
            aria-label={letter === "#" ? "Other" : letter}
            className={`${CELL} ${
              letter === active
                ? "border-(--accent) bg-[color-mix(in_srgb,var(--accent)_14%,var(--card))] text-(--accent)"
                : "border-(--border) bg-(--card) text-zinc-300 hover:border-white/25 hover:bg-(--secondary)"
            }`}
          >
            {letter}
          </Link>
        ) : (
          <span
            key={letter}
            aria-disabled="true"
            aria-label={
              letter === "#" ? "Other, no terms" : `${letter}, no terms`
            }
            className={`${CELL} border-(--border) bg-(--card) text-zinc-700`}
          >
            {letter}
          </span>
        ),
      )}
    </nav>
  );
}
