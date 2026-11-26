/**
 * Repository card and list row for the dashboard, in every ingestion state.
 * @module RepoCard
 */
"use client";

import regenerateRepoAction from "@/actions/regenerateRepo";
import Repository from "@/types/repository";
import { splitRepoName } from "@/utils/repoName";
import { statusView, syncView } from "@/utils/repoStatus";
import { timeAgo } from "@/utils/timeAgo";
import Link from "next/link";
import { useState, useTransition } from "react";
import RepoThumb from "./RepoThumb";

/** The coarse statuses an ingest moves through, in order. */
const INGEST_STEPS = ["pending", "cloning", "parsing", "embedding"] as const;

const STEP_LABEL: Record<string, string> = {
  pending: "Queued",
  cloning: "Fetching the repository",
  parsing: "Parsing and mapping files",
  embedding: "Writing the guide",
};

/**
 * The languages and frameworks the stack detector found, deduplicated.
 *
 * @param repo The repository.
 * @returns Up to `limit` stack labels.
 */
function stackOf(repo: Repository, limit = 4): string[] {
  const all = [
    ...(repo.detected_stack?.languages ?? []),
    ...(repo.detected_stack?.frameworks ?? []),
  ];
  return [...new Set(all)].slice(0, limit);
}

/**
 * The branch and short commit the repository was read at.
 *
 * @param repo The repository.
 * @returns The snapshot line, or null when neither is recorded.
 */
function Snapshot({ repo }: { repo: Repository }) {
  if (!repo.ingested_branch && !repo.ingested_commit_sha) return null;
  return (
    <span className="truncate font-pixel text-xs text-(--muted-foreground)">
      ⎇ {repo.ingested_branch ?? "detached"}
      {repo.ingested_commit_sha && (
        <>
          {" "}
          <span className="text-(--faint-foreground)">@</span>{" "}
          <span className="text-(--accent)">
            {repo.ingested_commit_sha.slice(0, 7)}
          </span>
        </>
      )}
    </span>
  );
}

/**
 * The retry control for a failed ingest.
 *
 * Re-ingesting rebuilds the repository under the same id and returns to the
 * dashboard, which then shows it ingesting again.
 *
 * @param repoId The repository's UUID.
 * @returns The retry button and any error.
 */
function RetryButton({ repoId }: { repoId: string }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        disabled={pending}
        onClick={() => {
          setError(null);
          startTransition(async () => {
            try {
              // On success the action redirects back to the dashboard.
              await regenerateRepoAction(repoId);
            } catch {
              setError("Could not restart the ingest. Try again.");
            }
          });
        }}
        className="ghost relative z-10 self-start rounded-sm border border-(--border-strong) px-3 py-1.75 font-pixel text-xs tracking-[0.06em] text-zinc-300 uppercase hover:cursor-pointer disabled:opacity-60"
      >
        {pending ? "Restarting…" : "↻ Retry"}
      </button>
      {error && (
        <span role="alert" className="text-xs text-red-300">
          {error}
        </span>
      )}
    </div>
  );
}

/**
 * Renders one repository as a dashboard card.
 *
 * The whole card is a link to the repository, done with a stretched overlay
 * rather than wrapping the card in `<a>`, so the GitHub link and the retry
 * button inside it remain valid, separately focusable controls.
 *
 * @param repo The repository record.
 * @returns The rendered card.
 */
export default function RepoCard({ repo }: { repo: Repository }) {
  const view = statusView(repo.status);
  const { owner, name } = splitRepoName(repo.github_url, repo.name);
  const stack = stackOf(repo);
  const sync = syncView(repo);
  const stepIndex = Math.max(0, INGEST_STEPS.indexOf(repo.status as never));
  const href = `/repo/${repo.repo_number}`;

  return (
    <article className="group panel relative flex min-w-0 flex-col overflow-hidden transition-colors hover:border-(--border-strong)">
      <div className="relative h-32 border-b border-white/8 bg-[#060608]">
        <RepoThumb
          repoId={repo.id}
          tone={view.kind === "ready" ? "ready" : "muted"}
        />
        <span
          className="absolute top-2.5 left-3 flex items-center gap-1.5 border bg-(--background)/80 px-2 py-1 font-pixel text-[11px] tracking-[0.1em] uppercase"
          style={{ borderColor: `${view.color}66`, color: view.color }}
        >
          <span
            className={`h-1.5 w-1.5 ${view.kind === "ingesting" ? "blink" : ""}`}
            style={{ background: view.color }}
          />
          {view.label}
        </span>
        {repo.primary_language && (
          <span className="absolute top-2.5 right-3 font-pixel text-[11px] tracking-[0.08em] text-(--subtle-foreground) uppercase">
            {repo.primary_language}
          </span>
        )}
      </div>

      <div className="flex grow flex-col gap-3 p-4.5">
        <div className="flex items-start justify-between gap-2.5">
          <div className="flex min-w-0 flex-col gap-1.5">
            <h3 className="m-0 truncate font-pixel text-xl leading-tight">
              <Link
                href={href}
                className="after:absolute after:inset-0 after:content-[''] focus-visible:outline-none"
              >
                {owner && (
                  <span className="text-(--subtle-foreground)">{owner}/</span>
                )}
                {name}
              </Link>
            </h3>
            <Snapshot repo={repo} />
          </div>
          <span
            aria-hidden="true"
            className="font-pixel text-lg text-(--faint-foreground) transition-transform group-hover:translate-x-0.5 group-hover:text-(--accent)"
          >
            →
          </span>
        </div>

        {view.kind === "ingesting" && (
          <div className="flex flex-col gap-2 rounded-sm border border-dashed border-white/12 p-3">
            <div className="flex justify-between font-pixel text-xs text-zinc-300">
              <span>{STEP_LABEL[repo.status] ?? "Working"}</span>
              <span className="text-(--accent)">
                {stepIndex + 1}/{INGEST_STEPS.length}
              </span>
            </div>
            <span aria-hidden="true" className="flex gap-0.5">
              {INGEST_STEPS.map((step, i) => (
                <span
                  key={step}
                  className={`h-1.5 flex-1 ${i < stepIndex ? "bg-(--chart-2)" : i === stepIndex ? "blink bg-(--accent)" : "bg-(--muted)"}`}
                />
              ))}
            </span>
            <span className="font-pixel text-[11px] tracking-[0.06em] text-(--subtle-foreground) uppercase">
              Step {stepIndex + 1} of {INGEST_STEPS.length} · You can leave this
              page
            </span>
          </div>
        )}

        {view.kind === "failed" && (
          <div className="flex flex-col gap-2.5 rounded-sm border border-red-500/25 bg-red-500/5 p-3">
            <span className="text-[13px] leading-normal text-red-300">
              This ingest did not finish. Open it to see where it stopped, or
              start it again.
            </span>
            <RetryButton repoId={repo.id} />
          </div>
        )}

        {view.kind === "ready" &&
          (repo.architecture_summary ? (
            <p className="m-0 line-clamp-3 text-sm leading-relaxed text-zinc-400">
              {repo.architecture_summary}
            </p>
          ) : (
            <p className="m-0 font-pixel text-xs text-(--faint-foreground) uppercase">
              No summary yet
            </p>
          ))}

        {stack.length > 0 && (
          <div className="mt-auto flex flex-wrap gap-1.5">
            {stack.map((t) => (
              <span
                key={t}
                className="rounded-[3px] border border-(--border) px-2 py-1 font-pixel text-[11px] text-zinc-300"
              >
                {t}
              </span>
            ))}
          </div>
        )}

        <div
          className={`flex justify-between gap-2.5 border-t border-white/8 pt-3 font-pixel text-[11px] tracking-[0.06em] text-(--subtle-foreground) uppercase ${stack.length ? "" : "mt-auto"}`}
        >
          <span className="flex items-center gap-1.5">
            <span
              className={`h-1.5 w-1.5 ${sync.live ? "blink" : ""}`}
              style={{ background: sync.color }}
            />
            {sync.label}
          </span>
          <span>{timeAgo(repo.updated_at)}</span>
        </div>
      </div>
    </article>
  );
}

/**
 * Renders one repository as a row of the dashboard's list view.
 *
 * @param repo The repository record.
 * @returns The rendered row.
 */
export function RepoRow({ repo }: { repo: Repository }) {
  const view = statusView(repo.status);
  const { owner, name } = splitRepoName(repo.github_url, repo.name);
  const stack = stackOf(repo, 6);

  return (
    <li className="relative grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] items-center gap-4 border-b border-white/6 px-4.5 py-4 last:border-b-0 hover:bg-(--secondary)/60 md:grid-cols-[minmax(0,2fr)_minmax(0,1.2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_20px]">
      <span className="flex min-w-0 flex-col gap-1">
        <Link
          href={`/repo/${repo.repo_number}`}
          className="truncate font-pixel text-base after:absolute after:inset-0 after:content-['']"
        >
          {owner && (
            <span className="text-(--subtle-foreground)">{owner}/</span>
          )}
          {name}
        </Link>
        <span className="truncate text-[13px] text-(--muted-foreground)">
          {stack.join(" · ") || "—"}
        </span>
      </span>
      <span className="hidden min-w-0 md:block">
        <Snapshot repo={repo} />
      </span>
      <span
        className="flex items-center gap-2 font-pixel text-xs tracking-[0.08em] uppercase"
        style={{ color: view.color }}
      >
        <span
          className={`h-1.5 w-1.5 ${view.kind === "ingesting" ? "blink" : ""}`}
          style={{ background: view.color }}
        />
        {view.kind === "ingesting"
          ? (STEP_LABEL[repo.status] ?? view.label)
          : view.label}
      </span>
      <span className="hidden font-pixel text-xs text-(--subtle-foreground) uppercase md:block">
        {timeAgo(repo.updated_at)}
      </span>
      <span
        aria-hidden="true"
        className="hidden text-right font-pixel text-base text-(--faint-foreground) md:block"
      >
        →
      </span>
    </li>
  );
}
