/**
 * Docs sidebar: a title filter, the overview, then every doc under its group
 * heading. A vertical list from the `lg` breakpoint up; below it, a collapsible
 * "Documentation" menu above the article. The active page is read from the
 * pathname, which is why this is a client component.
 *
 * The mobile menu is keyed on the pathname so it remounts closed after every
 * navigation, rather than tracking open state by hand.
 * @module DocsNav
 */
"use client";

import type { DocSection } from "@/lib/docs";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

/**
 * Renders the sidebar.
 *
 * @param sections - Every doc except the overview, grouped in sidebar order.
 * @returns The sidebar navigation.
 */
export function DocsNav({ sections }: { sections: DocSection[] }) {
  const pathname = usePathname();
  const [query, setQuery] = useState("");

  const needle = query.trim().toLowerCase();
  const matches = (title: string) =>
    !needle || title.toLowerCase().includes(needle);

  const visible = sections
    .map((section) => ({
      ...section,
      docs: section.docs.filter((doc) => matches(doc.title)),
    }))
    .filter((section) => section.docs.length > 0);
  const showOverview = matches("Overview");

  const link = (href: string, title: string) => {
    const active = pathname === href;
    return (
      <li key={href}>
        <Link
          href={href}
          aria-current={active ? "page" : undefined}
          className={`block rounded-r-sm px-2.5 py-1.75 text-sm transition-colors duration-150 ${
            active
              ? "bg-(--accent)/8 text-(--foreground) shadow-[inset_2px_0_0_var(--accent)]"
              : "text-(--muted-foreground) hover:bg-zinc-900 hover:text-(--foreground)"
          }`}
        >
          {title}
        </Link>
      </li>
    );
  };

  const links = (
    <div className="flex flex-col gap-5.5">
      <label className="relative block">
        <span className="sr-only">Filter the docs</span>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 font-pixel text-[13px] text-zinc-600"
        >
          /
        </span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search the docs"
          className="w-full rounded-sm border border-white/10 bg-(--card) py-2.25 pr-3 pl-7 font-pixel text-[13px] text-(--foreground) outline-none placeholder:text-zinc-600 focus:border-(--accent)"
        />
      </label>
      {showOverview && (
        <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
          {link("/docs", "Overview")}
        </ul>
      )}
      {visible.map((section) => (
        <div key={section.title} className="flex flex-col gap-0.5">
          <p className="m-0 px-2.5 pb-1.5 font-pixel text-[10px] tracking-[0.14em] text-zinc-600 uppercase">
            {section.title}
          </p>
          <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
            {section.docs.map((doc) => link(`/docs/${doc.slug}`, doc.title))}
          </ul>
        </div>
      ))}
      {!showOverview && visible.length === 0 && (
        <p className="m-0 px-2.5 font-pixel text-xs tracking-[0.06em] text-zinc-600 uppercase">
          Nothing matches
        </p>
      )}
    </div>
  );

  return (
    <nav aria-label="Documentation">
      <details key={pathname} className="docs-menu lg:hidden">
        <summary className="cursor-pointer rounded-sm border border-white/10 bg-(--card) px-3 py-2.5 font-pixel text-[13px] tracking-[0.06em]">
          Documentation <span aria-hidden="true">▾</span>
        </summary>
        <div className="mt-2 rounded-sm border border-white/10 bg-(--card) p-3">
          {links}
        </div>
      </details>
      <div className="hidden lg:block">{links}</div>
    </nav>
  );
}
