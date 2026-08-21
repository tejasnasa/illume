"use client";

import { getMyGitHubRepos } from "@/api/github";
import { GitHubRepo } from "@/types/github";
import {
  ArrowLeftIcon,
  GithubLogoIcon,
  GlobeIcon,
  MagnifyingGlassIcon,
  SpinnerIcon,
} from "@phosphor-icons/react/dist/ssr";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import GitGraph from "./GitGraph";
import Button from "./ui/Button";
import Input from "./ui/Input";

interface RepoPickerModalProps {
  onClose?: () => void;
}

type Mode = "picker" | "graph";
type Tab = "my-repos" | "external";

export default function RepoPickerModal({ onClose }: RepoPickerModalProps) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("picker");
  const [activeTab, setActiveTab] = useState<Tab>("my-repos");

  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
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

  useEffect(() => {
    const handle = setTimeout(() => {
      setDebouncedSearch(search);
    }, 400);

    return () => clearTimeout(handle);
  }, [search]);

  useEffect(() => {
    if (activeTab !== "my-repos") return;
    setPage(1);
    setRepos([]);
    setHasMoreRepos(true);
    setReposError(null);
    fetchRepos(1, debouncedSearch, true);
  }, [debouncedSearch, activeTab]);

  const fetchRepos = async (
    pageNumber: number,
    searchTerm: string,
    reset: boolean = false,
  ) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

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
      if (!controller.signal.aborted) {
        setLoadingRepos(false);
      }
    }
  };

  const observerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!hasMoreRepos || loadingRepos || activeTab !== "my-repos") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          const nextPage = page + 1;
          setPage(nextPage);
          fetchRepos(nextPage, debouncedSearch);
        }
      },
      { threshold: 0.1 },
    );

    const current = observerRef.current;
    if (current) {
      observer.observe(current);
    }

    return () => {
      if (current) {
        observer.unobserve(current);
      }
    };
  }, [hasMoreRepos, loadingRepos, page, debouncedSearch, activeTab]);

  const handleSelectMyRepo = (repo: GitHubRepo) => {
    const [owner, name] = repo.full_name.split("/");
    setSelectedRepoOwner(owner);
    setSelectedRepoName(name);
    setSelectedRepoUrl(repo.html_url);
    setMode("graph");
  };

  const handleExternalSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setExternalError("");

    const match = externalUrl.match(
      /^https:\/\/github\.com\/([\w.-]+)\/([\w.-]+)\/?$/,
    );
    if (!match) {
      setExternalError(
        "Please enter a valid GitHub repository URL (e.g. https://github.com/user/repo)",
      );
      return;
    }

    const [, owner, name] = match;
    setSelectedRepoOwner(owner);
    setSelectedRepoName(name.replace(/\.git$/, ""));
    setSelectedRepoUrl(externalUrl);
    setMode("graph");
  };

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
          const errorData = await res.json();
          throw new Error(errorData.message || "Failed to trigger ingestion");
        }

        const result = await res.json();
        if (onClose) onClose();
        router.push(`/repo/${result.repo_num}`);
      } catch (err: any) {
        setIngestError(err.message || "Failed to start ingestion process");
      }
    });
  };

  if (mode === "graph") {
    return (
      <div className="w-full flex flex-col gap-4 max-w-2xl mx-auto py-2">
        <button
          onClick={() => setMode("picker")}
          className="self-start flex items-center gap-1.5 text-xs text-(--muted-foreground) hover:text-(--foreground) transition-colors mb-2"
        >
          <ArrowLeftIcon size={14} />
          Back to repository list
        </button>

        <div className="mb-2">
          <h2 className="text-xl font-bold text-(--foreground)">
            Configure Version for {selectedRepoOwner}/{selectedRepoName}
          </h2>
          <p className="text-xs text-(--muted-foreground)">
            Select a branch or commit from the git history to ingest a targeted
            snapshot.
          </p>
        </div>

        {ingestError && (
          <div className="p-3 rounded bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
            {ingestError}
          </div>
        )}

        <GitGraph
          owner={selectedRepoOwner}
          repo={selectedRepoName}
          onSelect={handleVersionSelect}
          isSubmitting={isPending}
        />
      </div>
    );
  }

  return (
    <div className="w-full mx-auto flex flex-col min-h-[450px]">
      <div className="flex border-b border-(--border) mb-4">
        <button
          onClick={() => setActiveTab("my-repos")}
          className={`flex-1 py-3 text-center text-xs font-semibold uppercase tracking-wider border-b-2 transition-all flex items-center justify-center gap-2 ${
            activeTab === "my-repos"
              ? "border-(--primary) text-(--foreground)"
              : "border-transparent text-(--muted-foreground) hover:text-(--foreground)"
          }`}
        >
          <GithubLogoIcon size={16} />
          My Repositories
        </button>
        <button
          onClick={() => setActiveTab("external")}
          className={`flex-1 py-3 text-center text-xs font-semibold uppercase tracking-wider border-b-2 transition-all flex items-center justify-center gap-2 ${
            activeTab === "external"
              ? "border-(--primary) text-(--foreground)"
              : "border-transparent text-(--muted-foreground) hover:text-(--foreground)"
          }`}
        >
          <GlobeIcon size={16} />
          External URL
        </button>
      </div>

      <div className="flex-1 flex flex-col">
        {activeTab === "my-repos" ? (
          <div className="flex-1 flex flex-col">
            {/* Search filter input */}
            <div className="relative mb-4 pr-3">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-(--muted-foreground)">
                <MagnifyingGlassIcon size={16} />
              </span>
              <Input
                type="text"
                placeholder="Search your GitHub repositories..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-10 w-full bg-(--secondary)/10 text-sm py-2"
              />
            </div>

            <div className="flex-1 overflow-y-auto max-h-[320px] custom-scrollbar space-y-2 pr-0.5">
              {repos.map((repo) => (
                <div
                  key={repo.full_name}
                  onClick={() => handleSelectMyRepo(repo)}
                  className="p-3 rounded-sm border border-(--border) hover:border-(--primary)/50 bg-(--secondary)/5 hover:bg-(--secondary)/10 cursor-pointer transition-all duration-300 flex items-center justify-between"
                >
                  <div className="min-w-0 pr-4">
                    <h4 className="text-sm font-semibold truncate text-(--foreground)">
                      {repo.name}
                    </h4>
                    <p className="text-xs text-(--muted-foreground) truncate mt-0.5">
                      {repo.description || "No description provided."}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {repo.language && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-(--secondary) font-mono text-(--muted-foreground)">
                        {repo.language}
                      </span>
                    )}
                    {repo.private && (
                      <span className="text-[9px] font-bold text-yellow-500 bg-yellow-500/10 px-1.5 py-0.5 rounded-full uppercase tracking-wider">
                        Private
                      </span>
                    )}
                  </div>
                </div>
              ))}

              {loadingRepos && (
                <div className="py-8 flex justify-center text-(--muted-foreground) text-xs items-center gap-2">
                  <SpinnerIcon
                    className="animate-spin text-(--primary)"
                    size={16}
                  />
                  <span>Loading repositories...</span>
                </div>
              )}

              {hasMoreRepos && !loadingRepos && (
                <div ref={observerRef} className="h-4" />
              )}

              {!loadingRepos && repos.length === 0 && (
                <div className="py-12 text-center text-xs text-(--muted-foreground) italic">
                  {reposError || "No GitHub repositories found."}
                </div>
              )}
            </div>
          </div>
        ) : (
          <form
            onSubmit={handleExternalSubmit}
            className="flex-1 flex flex-col gap-4 py-4 justify-between"
          >
            <div className="space-y-2">
              <label
                htmlFor="url"
                className="text-xs font-semibold text-(--muted-foreground)"
              >
                GitHub Repository URL
              </label>
              <Input
                id="url"
                type="text"
                placeholder="https://github.com/owner/repository"
                value={externalUrl}
                onChange={(e) => setExternalUrl(e.target.value)}
                className="w-full bg-(--secondary)/10"
              />
              {externalError && (
                <p className="text-xs text-(--destructive)">{externalError}</p>
              )}
            </div>

            <Button type="submit" size="md" className="w-full">
              Continue
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
