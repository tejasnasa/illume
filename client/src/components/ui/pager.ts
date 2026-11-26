/**
 * Class names shared by the Previous and Next controls of paged lists.
 *
 * Kept in a plain module so both server pages and client components can
 * import the strings themselves.
 * @module pager
 */

/** An enabled pager button or link. */
export const PAGER_BUTTON =
  "ghost rounded-sm border border-(--input) px-3.5 py-2 font-pixel text-xs tracking-[0.06em] text-zinc-300 uppercase hover:cursor-pointer";

/** A pager control with nowhere to go. */
export const PAGER_DISABLED =
  "rounded-sm border border-(--border) px-3.5 py-2 font-pixel text-xs tracking-[0.06em] text-(--faint-foreground) uppercase";
