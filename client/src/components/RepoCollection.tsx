/**
 * The dashboard's filterable repository collection, as a grid or a list.
 * @module RepoCollection
 */
"use client";

import Repository from "@/types/repository";
import { useEffect, useMemo, useState } from "react";
import { statusView } from "@/utils/repoStatus";
import RepoCard, { RepoRow } from "./ui/RepoCard";

type Filter = "all" | "ready" | "ingesting" | "failed";
type View = "grid" | "list";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "ready", label: "Ready" },
  { id: "ingesting", label: "Ingesting" },
  { id: "failed", label: "Failed" },
];

const VIEW_KEY = "illume:dashboard-view";

/**
 * Renders the search box, status filters, view toggle and the repositories.
 *
 * Filtering is local: the dashboard already has every repository the user
 * owns. The chosen view is remembered per browser.
 *
 * @param repositories All of the user's repositories.
 * @returns The collection.
 */
export default function RepoCollection({
  repositories,
}: {
  repositories: Repository[];
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<View>("grid");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(VIEW_KEY);
      if (saved === "grid" || saved === "list") setView(saved);
    } catch {
      // Storage unavailable: the grid default stands.
    }
  }, []);

  /**
   * Switches the view and remembers it.
   *
   * @param next The view to show.
   */
  const chooseView = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      // Not remembered; the switch itself still applies.
    }
  };

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, ready: 0, ingesting: 0, failed: 0 };
    for (const repo of repositories) {
      c.all++;
      c[statusView(repo.status).kind]++;
    }
    return c;
  }, [repositories]);

  const q = query.trim().toLowerCase();
  const shown = repositories.filter((repo) => {
    if (filter !== "all" && statusView(repo.status).kind !== filter) return false;
    if (!q) return true;
    return (
      repo.name.toLowerCase().includes(q) ||
      repo.github_url?.toLowerCase().includes(q) ||
      (repo.architecture_summary ?? "").toLowerCase().includes(q)
    );
  });

  const toggleClass = (on: boolean) =>
    `px-2.75 py-2.25 hover:cursor-pointer ${on ? "bg-(--muted) text-(--foreground)" : "text-(--subtle-foreground) hover:text-(--foreground)"}`;

  return (
    <div className="flex flex-col gap-7">
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative max-w-90 flex-[1_1_260px]">
          <span
            aria-hidden="true"
            className="absolute top-1/2 left-3.5 -translate-y-1/2 font-pixel text-sm text-(--faint-foreground)"
          >
            ⌕
          </span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter repositories"
            aria-label="Filter repositories"
            className="h-10 w-full rounded-sm border border-(--border) bg-(--card) pr-3 pl-9 text-sm outline-none focus:border-(--accent)"
          />
        </label>
        <div role="group" aria-label="Status" className="flex flex-wrap gap-1.5">
          {FILTERS.map(({ id, label }) => {
            const on = filter === id;
            return (
              <button
                key={id}
                type="button"
                aria-pressed={on}
                onClick={() => setFilter(id)}
                className={`rounded-sm border px-3 py-2 font-pixel text-xs tracking-[0.08em] uppercase hover:cursor-pointer ${on ? "border-(--accent) bg-(--accent)/8 text-(--foreground)" : "border-(--border) text-(--muted-foreground) hover:text-(--foreground)"}`}
              >
                {label}{" "}
                <span className={on ? "text-(--accent)" : "text-(--faint-foreground)"}>
                  {counts[id]}
                </span>
              </button>
            );
          })}
        </div>
        <div className="grow" />
        <div
          role="group"
          aria-label="View"
          className="flex divide-x divide-(--border) overflow-hidden rounded-sm border border-(--border)"
        >
          <button
            type="button"
            aria-pressed={view === "grid"}
            aria-label="Grid view"
            onClick={() => chooseView("grid")}
            className={toggleClass(view === "grid")}
          >
            <svg width="14" height="14" viewBox="0 0 7 7" shapeRendering="crispEdges" fill="currentColor" aria-hidden="true">
              <path d="M0 0h3v3H0zM4 0h3v3H4zM0 4h3v3H0zM4 4h3v3H4z" />
            </svg>
          </button>
          <button
            type="button"
            aria-pressed={view === "list"}
            aria-label="List view"
            onClick={() => chooseView("list")}
            className={toggleClass(view === "list")}
          >
            <svg width="14" height="14" viewBox="0 0 7 7" shapeRendering="crispEdges" fill="currentColor" aria-hidden="true">
              <path d="M0 0h7v1H0zM0 3h7v1H0zM0 6h7v1H0z" />
            </svg>
          </button>
        </div>
      </div>

      {shown.length === 0 ? (
        <p className="m-0 rounded-md border border-dashed border-white/12 p-12 text-center font-pixel text-sm text-(--muted-foreground)">
          {repositories.length === 0
            ? "No repositories yet. Add your first one to get started."
            : "No repositories match that filter."}
        </p>
      ) : view === "grid" ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {shown.map((repo) => (
            <RepoCard key={repo.id} repo={repo} />
          ))}
        </div>
      ) : (
        <div className="panel overflow-hidden">
          <div
            aria-hidden="true"
            className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] gap-4 border-b border-(--border) px-4.5 py-3 font-pixel text-[11px] tracking-[0.12em] text-(--subtle-foreground) uppercase md:grid-cols-[minmax(0,2fr)_minmax(0,1.2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_20px]"
          >
            <span>Repository</span>
            <span className="hidden md:block">Snapshot</span>
            <span>Status</span>
            <span className="hidden md:block">Updated</span>
            <span className="hidden md:block" />
          </div>
          <ul className="m-0 list-none p-0">
            {shown.map((repo) => (
              <RepoRow key={repo.id} repo={repo} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
