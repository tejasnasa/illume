/**
 * The "On this page" list beside a doc: one link per `h2`, with the section currently
 * being read highlighted as the reader scrolls.
 *
 * The current section is the last heading whose top has scrolled past a line just
 * below the fixed site header; above the first heading, the first entry is current.
 * Recomputed on scroll (once per frame) and on resize.
 * @module DocsOutline
 */
"use client";

import type { DocHeading } from "@/lib/docs";
import { useEffect, useState } from "react";

/** How far below the viewport top a heading counts as reached, in pixels. */
export const OUTLINE_OFFSET_PX = 120;

/**
 * Picks the section being read.
 *
 * @param tops - Each heading's distance from the viewport top, in page order.
 * @param offset - The line a heading must pass to become current.
 * @returns The index of the current heading, or 0 when none has passed it.
 */
export function currentSection(
  tops: readonly number[],
  offset: number,
): number {
  let current = 0;
  tops.forEach((top, i) => {
    if (top <= offset) current = i;
  });
  return current;
}

/**
 * Renders the outline.
 *
 * @param headings - The doc's `h2` headings, in page order.
 * @returns The list of section links.
 */
export function DocsOutline({ headings }: { headings: readonly DocHeading[] }) {
  const [activeId, setActiveId] = useState(headings[0]?.id ?? "");

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const elements = headings
        .map((h) => document.getElementById(h.id))
        .filter((el): el is HTMLElement => el !== null);
      if (elements.length === 0) return;
      const tops = elements.map((el) => el.getBoundingClientRect().top);
      const current = elements[currentSection(tops, OUTLINE_OFFSET_PX)];
      if (current) setActiveId(current.id);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [headings]);

  return (
    <ul className="m-0 flex list-none flex-col gap-0.5 border-l border-white/10 p-0 text-[13px]">
      {headings.map((heading) => {
        const active = heading.id === activeId;
        return (
          <li key={heading.id}>
            <a
              href={`#${heading.id}`}
              aria-current={active ? "location" : undefined}
              className={`-ml-px block border-l-2 py-1.5 pl-3 transition-colors ${
                active
                  ? "border-(--accent) text-(--foreground)"
                  : "border-transparent text-(--muted-foreground) hover:text-(--foreground)"
              }`}
            >
              {heading.text}
            </a>
          </li>
        );
      })}
    </ul>
  );
}
