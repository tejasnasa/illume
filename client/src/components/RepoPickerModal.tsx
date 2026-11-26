/**
 * Two-step picker for a repository and the version of it to ingest.
 * @module RepoPickerModal
 */
"use client";

import { getMyGitHubRepos } from "@/api/github";
import apiError from "@/lib/apiError";
import { repoSlug } from "@/lib/github";
import { GitHubRepo } from "@/types/github";
import { timeAgo } from "@/utils/timeAgo";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
} from "react";
import GitGraph from "./GitGraph";
import Input from "./ui/Input";

/** Props for the repository picker. */
interface RepoPickerModalProps {
  /** Closes the surrounding dialog; also called once an ingest has started. */
  onClose?: () => void;
  /** A line shown beside the ingest action, such as what the ingest costs. */
  note?: string;
  /** URLs of the repositories already added; those rows are marked and disabled. */
  added?: string[];
}

type Mode = "picker" | "graph";
type Tab = "my-repos" | "external";

const TABS: { id: Tab; label: string }[] = [
  { id: "my-repos", label: "My Repositories" },
  { id: "external", label: "External URL" },
];

const STEPS = ["Repository", "Version", "Read"] as const;

/**
 * The step indicator across the top of the picker.
 *
 * @param current Zero-based index of the step on screen.
 * @returns The ordered step list.
 */
function StepHeader({ current }: { current: number }) {
  return (
    <ol className="m-0 flex list-none items-center gap-2.5 p-0 font-pixel text-[11px] tracking-[0.1em] uppercase">
      {STEPS.map((step, i) => {
        const state = i < current ? "done" : i === current ? "on" : "todo";
        return (
          <li
            key={step}
            aria-current={state === "on" ? "step" : undefined}
            className="flex items-center gap-2.5"
          >
            {i > 0 && (
              <span
                aria-hidden="true"
                className="h-px w-5 bg-(--border-strong)"
              />
            )}
            <span
              className={
                state === "on"
                  ? "text-(--accent)"
                  : state === "done"
                    ? "text-zinc-300"
                    : "text-(--faint-foreground)"
              }
            >
              {i + 1} {step}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Lets users choose a GitHub repository, then a branch or commit to ingest.
 *
 * @param onClose - Closes the dialog; called after ingestion starts too.
 * @param note - Optional cost line shown on the version step.
 * @returns Picker UI or version graph depending on the current mode.
 */
export default function RepoPickerModal({
  onClose,
  note,
  added,
}: RepoPickerModalProps) {
  const router = useRouter();
  const addedSlugs = useMemo(
    () =>
      new Set(
        (added ?? [])
          .map(repoSlug)
          .filter((slug): slug is string => slug !== null),
      ),
    [added],
  );
  const [mode, setMode] = useState<Mode>("picker");
  const [activeTab, setActiveTab] = useState<Tab>("my-repos");

  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [hasMoreRepos, setHasMoreRepos] = useState(true);
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [reposError, setReposError] = useState<string | null>(null);

  const [selectedRepoOwner, setSelectedRepoOwner] = useState("");
  const [selectedRepoName, setSelectedRepoName] = useState("");
  const [selectedRepoUrl, setSelectedRepoUrl] = useState("");

  const [externalUrl, setExternalUrl] = useState("");
  const [externalError, setExternalError] = useState("");

  const [isPending, startTransition] = useTransition();
  const [ingestError, setIngestError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  /**
   * The highest page actually loaded.
   *
   * Kept in a ref rather than in state because the scroll observer reads it from inside
   * a callback. State read there is the value captured when the observer was built,
   * which is a commit behind by the time the callback runs.
   */
  const loadedPageRef = useRef(1);
  /** Whether a page request is in flight, so a callback cannot start a second one. */
  const loadingRef = useRef(false);

  /** Debounces the search box to avoid a request per keystroke. */
  useEffect(() => {
    const handle = setTimeout(() => {
      setDebouncedSearch(search);
    }, 400);

    return () => clearTimeout(handle);
  }, [search]);

  /** Reloads page one whenever the debounced query or tab changes. */
  useEffect(() => {
    if (activeTab !== "my-repos") return;
    setRepos([]);
    setHasMoreRepos(true);
    setReposError(null);
    fetchRepos(1, debouncedSearch, true);
  }, [debouncedSearch, activeTab]);

  /**
   * Loads one page of the user's repos, aborting any in-flight request.
   *
   * @param pageNumber - 1-indexed page to fetch.
   * @param searchTerm - Name filter sent to the backend.
   * @param reset - Replaces the list instead of appending.
   */
  const fetchRepos = async (
    pageNumber: number,
    searchTerm: string,
    reset: boolean = false,
  ) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    loadingRef.current = true;
    setLoadingRepos(true);
    try {
      const data = await getMyGitHubRepos(
        pageNumber,
        searchTerm,
        controller.signal,
      );
      if (controller.signal.aborted) return;

      if (reset) {
        setRepos(data);
      } else {
        setRepos((prev) => [...prev, ...data]);
      }
      loadedPageRef.current = pageNumber;
      if (data.length < 30) {
        setHasMoreRepos(false);
      }
    } catch (err: any) {
      if (err.name === "AbortError") return;
      if (err.message?.includes("GitHub account not linked")) {
        setReposError("GitHub account not linked. Please re-authenticate.");
      } else {
        setReposError(err.message || "Failed to load repositories");
      }
    } finally {
      // Only the request that is still the current one may clear the flag: a superseded
      // request finishing later would otherwise unlock the observer while its
      // replacement is still in flight.
      if (abortRef.current === controller) {
        loadingRef.current = false;
        setLoadingRepos(false);
      }
    }
  };

  /** Fetches the page after the last one loaded, unless a request is in flight. */
  const loadMoreRef = useRef<() => void>(() => {});
  useLayoutEffect(() => {
    loadMoreRef.current = () => {
      if (loadingRef.current) return;
      fetchRepos(loadedPageRef.current + 1, debouncedSearch);
    };
  });
  const observerRef = useRef<IntersectionObserver | null>(null);

  /**
   * Watches the scroll sentinel, appending the next page when it comes into view.
   *
   * A callback ref rather than an effect, so the observer follows the element itself.
   * The list unmounts while a version is being picked and mounts a fresh sentinel on
   * the way back; an effect keyed on the list's state would not re-run for that and
   * would keep watching the detached node, leaving the list stuck on what it had.
   *
   * The sentinel only exists once a page is on screen and no request is in flight.
   * That matters on first paint: the modal mounts with no results, and an observer
   * attached then would ask for page two while page one was still outstanding, and
   * `fetchRepos` would abort page one to make room for it.
   */
  const sentinelRef = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadMoreRef.current();
      },
      { threshold: 0.1 },
    );
    observer.observe(node);
    observerRef.current = observer;
  }, []);

  /**
   * Records the clicked repo and advances to version selection.
   *
   * @param repo - Repository chosen from the list.
   */
  const handleSelectMyRepo = (repo: GitHubRepo) => {
    const [owner, name] = repo.full_name.split("/");
    setSelectedRepoOwner(owner);
    setSelectedRepoName(name);
    setSelectedRepoUrl(repo.html_url);
    setMode("graph");
  };

  /**
   * Validates an external GitHub URL and advances to version selection.
   *
   * @param e - Form submit event.
   */
  const handleExternalSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setExternalError("");

    const match = externalUrl
      .trim()
      .match(/^https:\/\/github\.com\/([\w.-]+)\/([\w.-]+)\/?$/);
    if (!match) {
      setExternalError(
        "Please enter a valid GitHub repository URL (e.g. https://github.com/user/repo)",
      );
      return;
    }

    const [, owner, name] = match;
    setSelectedRepoOwner(owner);
    setSelectedRepoName(name.replace(/\.git$/, ""));
    setSelectedRepoUrl(externalUrl.trim());
    setMode("graph");
  };

  /**
   * Posts the chosen branch/commit to start ingestion, then navigates.
   *
   * @param branch - Branch to ingest.
   * @param commitSha - Optional pinned commit; null ingests the branch tip.
   */
  const handleVersionSelect = (branch: string, commitSha: string | null) => {
    setIngestError(null);
    startTransition(async () => {
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/v1/repository`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({
              github_url: selectedRepoUrl,
              branch,
              commit_sha: commitSha,
            }),
          },
        );

        if (!res.ok) {
          throw await apiError(res, "Failed to trigger ingestion");
        }

        const result = await res.json();
        if (onClose) onClose();
        router.push(`/repo/${result.repo_num}`);
      } catch (err: any) {
        setIngestError(err.message || "Failed to start ingestion process");
      }
    });
  };

  const header = (
    <div className="flex items-center justify-between gap-4 border-b border-white/8 px-5 py-4">
      <StepHeader current={mode === "picker" ? 0 : 1} />
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="font-pixel text-base text-(--subtle-foreground) hover:cursor-pointer hover:text-(--foreground)"
        >
          ✕
        </button>
      )}
    </div>
  );

  if (mode === "graph") {
    return (
      <div className="flex h-full min-h-0 flex-col">
        {header}
        <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-width:thin]">
          <div className="flex flex-col gap-1.5 px-5 pt-5 pb-4">
            <h2 className="m-0 font-pixel text-2xl font-normal tracking-[-0.01em] break-words">
              Choose a version of{" "}
              <span className="gradient-text">
                {selectedRepoOwner}/{selectedRepoName}
              </span>
            </h2>
            <p className="m-0 text-sm text-(--muted-foreground)">
              Read the tip of a branch, or pin any older commit as a snapshot.
              The default branch is picked for you.
            </p>
          </div>

          {ingestError && (
            <div
              role="alert"
              className="mx-5 mb-4 rounded-sm border border-red-500/25 bg-red-500/5 p-3 text-xs text-red-300"
            >
              {ingestError}
            </div>
          )}

          <GitGraph
            owner={selectedRepoOwner}
            repo={selectedRepoName}
            onSelect={handleVersionSelect}
            isSubmitting={isPending}
            onBack={() => setMode("picker")}
            note={note}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {header}
      <div className="flex flex-col gap-1.5 px-5 pt-5">
        <h2 className="m-0 font-pixel text-2xl font-normal tracking-[-0.01em]">
          Add a <span className="gradient-text">repository</span>
        </h2>
        <p className="m-0 text-sm text-(--muted-foreground)">
          Pick one of yours, or paste any public GitHub URL.
        </p>
      </div>

      <div
        role="tablist"
        aria-label="Repository source"
        className="mt-4 flex gap-6 border-b border-white/8 px-5"
      >
        {TABS.map(({ id, label }) => {
          const on = activeTab === id;
          return (
            <button
              key={id}
              id={`picker-tab-${id}`}
              type="button"
              role="tab"
              aria-selected={on}
              aria-controls={`picker-panel-${id}`}
              onClick={() => setActiveTab(id)}
              className={`-mb-px border-b-2 py-3 font-pixel text-xs tracking-[0.1em] uppercase hover:cursor-pointer ${
                on
                  ? "border-(--accent) text-(--foreground)"
                  : "border-transparent text-(--subtle-foreground) hover:text-(--foreground)"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {activeTab === "my-repos" ? (
        <div
          id="picker-panel-my-repos"
          role="tabpanel"
          aria-labelledby="picker-tab-my-repos"
          className="flex min-h-0 flex-1 flex-col gap-3 p-5"
        >
          <label className="relative">
            <span
              aria-hidden="true"
              className="absolute top-1/2 left-3.5 -translate-y-1/2 font-pixel text-sm text-(--faint-foreground)"
            >
              ⌕
            </span>
            <Input
              type="text"
              placeholder="Search your GitHub repositories..."
              aria-label="Search your GitHub repositories"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9"
            />
          </label>

          <ul className="m-0 flex min-h-0 flex-1 list-none flex-col gap-1.5 overflow-y-auto p-0 [scrollbar-width:thin]">
            {repos.map((repo) => {
              const [owner] = repo.full_name.split("/");
              // Still selectable: another branch or commit of it is a separate snapshot.
              const isAdded = addedSlugs.has(repo.full_name.toLowerCase());
              return (
                <li key={repo.full_name}>
                  <button
                    type="button"
                    onClick={() => handleSelectMyRepo(repo)}
                    className="ghost group flex w-full items-center justify-between gap-4 rounded-sm border border-(--border) bg-(--background) px-3.5 py-3 text-left hover:cursor-pointer hover:bg-(--secondary)"
                  >
                    <span className="flex min-w-0 flex-col gap-1">
                      <span className="truncate font-pixel text-sm">
                        <span className="text-(--subtle-foreground)">
                          {owner}/
                        </span>
                        <span>{repo.name}</span>
                      </span>
                      <span className="truncate text-[13px] text-(--muted-foreground)">
                        {repo.description || "No description provided."}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2 font-pixel text-[10px] tracking-[0.08em] uppercase">
                      {repo.private && (
                        <span className="border border-(--warning)/40 px-1.5 py-0.5 text-(--warning)">
                          Private
                        </span>
                      )}
                      {repo.language && (
                        <span className="border border-(--border) px-1.5 py-0.5 text-zinc-300">
                          {repo.language}
                        </span>
                      )}
                      {isAdded ? (
                        <span className="text-(--success)">Added ✓</span>
                      ) : (
                        repo.updated_at && (
                          <span className="hidden text-(--faint-foreground) sm:inline">
                            Pushed {timeAgo(new Date(repo.updated_at))}
                          </span>
                        )
                      )}
                      <span
                        aria-hidden="true"
                        className="text-sm text-(--faint-foreground) group-hover:text-(--accent)"
                      >
                        →
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}

            {loadingRepos && (
              <li className="blink py-8 text-center font-pixel text-xs tracking-[0.12em] text-(--muted-foreground) uppercase">
                Loading repositories...
              </li>
            )}

            {hasMoreRepos && !loadingRepos && repos.length > 0 && (
              <li aria-hidden="true">
                <div ref={sentinelRef} className="h-4" />
              </li>
            )}

            {!loadingRepos && repos.length === 0 && (
              <li
                role={reposError ? "alert" : undefined}
                className={`py-12 text-center text-sm ${reposError ? "text-red-300" : "text-(--muted-foreground)"}`}
              >
                {reposError || "No GitHub repositories found."}
              </li>
            )}
          </ul>
        </div>
      ) : (
        <form
          id="picker-panel-external"
          role="tabpanel"
          aria-labelledby="picker-tab-external"
          onSubmit={handleExternalSubmit}
          className="flex flex-1 flex-col justify-between gap-6 p-5"
        >
          <div className="flex flex-col gap-2">
            <label
              htmlFor="url"
              className="font-pixel text-[11px] tracking-[0.1em] text-(--muted-foreground) uppercase"
            >
              GitHub Repository URL
            </label>
            <Input
              id="url"
              type="text"
              inputMode="url"
              autoComplete="off"
              placeholder="https://github.com/owner/repository"
              value={externalUrl}
              onChange={(e) => setExternalUrl(e.target.value)}
              aria-invalid={externalError ? true : undefined}
              aria-describedby={externalError ? "url-error" : "url-note"}
              className="w-full"
            />
            {externalError ? (
              <p id="url-error" className="m-0 text-xs text-(--destructive)">
                {externalError}
              </p>
            ) : (
              <p
                id="url-note"
                className="m-0 font-pixel text-[11px] tracking-[0.06em] text-(--subtle-foreground) uppercase"
              >
                Public repositories only. For a private one, use the My
                Repositories tab.
              </p>
            )}
          </div>

          <button
            type="submit"
            className="cta self-end rounded-sm bg-(--primary) px-5 py-2.75 font-pixel text-[13px] tracking-[0.06em] text-(--primary-foreground) uppercase hover:cursor-pointer"
          >
            Continue <span aria-hidden="true">→</span>
          </button>
        </form>
      )}
    </div>
  );
}
