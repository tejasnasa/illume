/**
 * Docs sidebar: the overview, then every doc under its group heading. A fixed vertical
 * list from the `lg` breakpoint up; below it, a collapsible "Documentation" menu above
 * the article. The active page is read from the pathname, which is why this is a
 * client component.
 *
 * The mobile menu is keyed on the pathname so it remounts closed after every
 * navigation, rather than tracking open state by hand.
 * @module DocsNav
 */
"use client";

import type { DocSection } from "@/lib/docs";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Renders the sidebar.
 *
 * @param sections - Every doc except the overview, grouped in sidebar order.
 * @returns The sidebar navigation.
 */
export function DocsNav({ sections }: { sections: DocSection[] }) {
  const pathname = usePathname();

  const link = (href: string, title: string) => {
    const active = pathname === href;
    return (
      <li key={href}>
        <Link
          href={href}
          aria-current={active ? "page" : undefined}
          className={`block rounded-lg px-3 py-1.5 text-sm transition-colors ${
            active
              ? "bg-(--secondary) text-(--foreground)"
              : "text-(--muted-foreground) hover:bg-(--secondary)/60 hover:text-(--foreground)"
          }`}
        >
          {title}
        </Link>
      </li>
    );
  };

  const links = (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-0.5">{link("/docs", "Overview")}</ul>
      {sections.map((section) => (
        <div key={section.title}>
          <p className="mb-1 px-3 text-xs uppercase tracking-wider text-(--muted-foreground)">
            {section.title}
          </p>
          <ul className="flex flex-col gap-0.5">
            {section.docs.map((doc) => link(`/docs/${doc.slug}`, doc.title))}
          </ul>
        </div>
      ))}
    </div>
  );

  return (
    <nav aria-label="Documentation">
      <details key={pathname} className="docs-menu lg:hidden">
        <summary className="cursor-pointer rounded-lg border border-(--border) bg-(--card)/40 px-3 py-2 text-sm">
          Documentation
        </summary>
        <div className="mt-2 rounded-lg border border-(--border) bg-(--card) p-2">
          {links}
        </div>
      </details>
      <div className="hidden max-h-[calc(100dvh-7rem)] overflow-y-auto pb-4 lg:block">
        {links}
      </div>
    </nav>
  );
}
