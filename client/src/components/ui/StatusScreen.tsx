/**
 * Full-height message screen used by the not-found and error pages.
 * @module StatusScreen
 */
import type { ReactNode } from "react";

/**
 * Renders a centred status message.
 *
 * @param command - The pixel command line shown above the code, e.g. `cd /repo/42`.
 * @param code - The large figure, e.g. `404`.
 * @param title - The heading.
 * @param children - Explanation under the heading.
 * @param actions - Buttons and links.
 * @param footnote - Small print under the actions, such as an error reference.
 * @param className - Height and spacing from the caller, which knows what
 *   chrome sits around it.
 * @returns The screen.
 */
export default function StatusScreen({
  command,
  code,
  title,
  children,
  actions,
  footnote,
  className = "min-h-dvh",
}: {
  command: string;
  code: string;
  title: string;
  children: ReactNode;
  actions: ReactNode;
  footnote?: ReactNode;
  className?: string;
}) {
  return (
    <main
      className={`flex items-center justify-center bg-[radial-gradient(ellipse_at_50%_40%,#f6339a12,transparent_60%)] px-4 py-16 ${className}`}
    >
      <div className="rise flex w-full max-w-130 flex-col gap-5">
        <p
          aria-hidden="true"
          className="m-0 font-pixel text-[13px] tracking-[0.12em] break-all text-(--muted-foreground)"
        >
          &gt; {command}
          <span className="caret text-(--accent)">_</span>
        </p>
        <p
          aria-hidden="true"
          className="gradient-text m-0 font-pixel text-[clamp(4.5rem,14vw,8rem)] leading-[0.9]"
        >
          {code}
        </p>
        <h1 className="m-0 font-pixel text-[clamp(1.6rem,3.4vw,2.2rem)] leading-tight font-normal">
          {title}
        </h1>
        <div className="flex flex-col gap-3 text-[15px] leading-relaxed text-zinc-400">
          {children}
        </div>
        <div className="flex flex-wrap gap-2.5 pt-2">{actions}</div>
        {footnote && (
          <p className="m-0 font-pixel text-[11px] tracking-[0.06em] break-all text-zinc-600 uppercase">
            {footnote}
          </p>
        )}
      </div>
    </main>
  );
}

/** Class strings for the screen's two action styles. */
export const STATUS_PRIMARY =
  "cta inline-flex items-center gap-2 rounded-sm bg-(--primary) px-4.5 py-2.75 font-pixel text-[13px] tracking-[0.06em] text-pink-50 uppercase hover:cursor-pointer";
export const STATUS_GHOST =
  "ghost inline-flex items-center gap-2 rounded-sm border border-white/15 px-4.5 py-2.75 font-pixel text-[13px] tracking-[0.06em] text-zinc-300 uppercase hover:cursor-pointer";
