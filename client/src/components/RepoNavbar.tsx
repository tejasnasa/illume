/**
 * Repository header: a breadcrumb back to the dashboard, the repository's
 * section links on the right, and the settings gear.
 * @module RepoNavbar
 */
"use client";

import Repository from "@/types/repository";
import { splitRepoName } from "@/utils/repoName";
import Link from "next/link";
import { usePathname } from "next/navigation";
import Logo from "./ui/Logo";
import PixelGear from "./ui/PixelGear";

/** The repository sections, in the order the bar shows them. */
const SECTIONS = [
  { slug: "", label: "Overview" },
  { slug: "chat", label: "Chat" },
  { slug: "graph", label: "Graph" },
  { slug: "explorer", label: "Explorer" },
  { slug: "glossary", label: "Glossary" },
] as const;

/**
 * Shows the repository's identity and navigation to its sections.
 *
 * Until the repository is ready the section links are inert placeholders --
 * every section needs a finished analysis -- and the breadcrumb says the
 * repository is still being read.
 *
 * @param repo - The repository the page belongs to.
 * @returns Sticky header with the active section underlined.
 */
export default function RepoNavbar({ repo }: { repo: Repository }) {
  const path = usePathname();
  const { status, repo_number, sync_status } = repo;
  const base = `/repo/${repo_number}`;
  const ready = status === "ready";
  const { owner, name } = splitRepoName(repo.github_url, repo.name);
  const onSettings = path === `${base}/settings`;
  const isSyncing =
    sync_status === "queued" ||
    sync_status === "checking" ||
    sync_status === "updating";

  const crumb = !ready ? "Ingesting" : onSettings ? "Settings" : null;
  const linkClass = "shrink-0 pt-5.25 pb-4.75 transition-colors duration-200";

  return (
    <nav
      aria-label="Repository"
      className="sticky top-0 z-40 border-b border-(--border) bg-(--background)/85 backdrop-blur-md print:hidden"
    >
      <div className="flex h-16 items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-3.5">
          <Link
            href="/dashboard"
            aria-label="Back to dashboard"
            className="shrink-0"
          >
            <Logo />
          </Link>
          <span aria-hidden="true" className="text-zinc-700">
            /
          </span>
          <Link
            href={base}
            className="truncate font-pixel text-base text-zinc-300 hover:text-(--foreground)"
          >
            {owner && (
              <span className="text-(--subtle-foreground)">{owner}/</span>
            )}
            {name}
          </Link>
          {isSyncing && (
            <span
              title="Updating in the background"
              className="flex shrink-0 items-center gap-1.5 font-pixel text-[11px] tracking-[0.08em] text-(--chart-1) uppercase"
            >
              <span
                aria-hidden="true"
                className="blink h-1.5 w-1.5 bg-(--chart-1)"
              />
              <span className="hidden sm:inline">Syncing</span>
            </span>
          )}
          {crumb && (
            <>
              <span aria-hidden="true" className="text-zinc-700">
                /
              </span>
              <span className="shrink-0 font-pixel text-base">{crumb}</span>
            </>
          )}
        </div>

        <div className="flex min-w-0 items-center gap-3.5">
          <div className="hidden min-w-0 items-center gap-6 overflow-x-auto font-pixel text-[13px] tracking-[0.06em] uppercase [scrollbar-width:none] md:flex">
            {SECTIONS.map(({ slug, label }) => {
              const href = slug ? `${base}/${slug}` : base;
              if (!ready) {
                return (
                  <span
                    key={label}
                    aria-disabled="true"
                    className={`${linkClass} text-(--faint-foreground)`}
                  >
                    {label}
                  </span>
                );
              }
              const current = path === href;
              return (
                <Link
                  key={label}
                  href={href}
                  aria-current={current ? "page" : undefined}
                  className={`${linkClass} ${
                    current
                      ? "text-(--foreground) shadow-[inset_0_-2px_0_var(--accent)]"
                      : "text-(--muted-foreground) hover:text-(--foreground)"
                  }`}
                >
                  {label}
                </Link>
              );
            })}
          </div>
          <Link
            href={`${base}/settings`}
            aria-label="Repository settings"
            aria-current={onSettings ? "page" : undefined}
            className={`ghost flex shrink-0 rounded-sm border p-2 ${
              onSettings
                ? "border-(--accent) text-(--foreground)"
                : "border-(--border) text-(--muted-foreground)"
            }`}
          >
            <PixelGear />
          </Link>
        </div>
      </div>
      {ready && (
        <div className="flex h-10 gap-5 overflow-x-auto border-t border-(--border) px-4 font-pixel text-xs tracking-[0.06em] uppercase [scrollbar-width:none] md:hidden">
          {SECTIONS.map(({ slug, label }) => {
            const href = slug ? `${base}/${slug}` : base;
            const current = path === href;
            return (
              <Link
                key={label}
                href={href}
                aria-current={current ? "page" : undefined}
                className={`flex shrink-0 items-center ${
                  current
                    ? "text-(--foreground) shadow-[inset_0_-2px_0_var(--accent)]"
                    : "text-(--muted-foreground)"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </div>
      )}
    </nav>
  );
}
