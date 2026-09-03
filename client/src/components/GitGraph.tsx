/**
 * Unified commit timeline with branch rails and ingest targeting.
 * @module GitGraph
 */
"use client";

import { useGitGraph } from "@/hooks/useGitGraph";
import { GitHubMultiBranchCommit } from "@/types/github";
import { timeAgo } from "@/utils/timeAgo";
import {
  GitBranchIcon,
  GitCommitIcon,
  SpinnerIcon,
} from "@phosphor-icons/react/dist/ssr";

/** Props for the repository timeline selector. */
interface GitGraphProps {
  owner: string;
  repo: string;
  onSelect: (branch: string, commitSha: string | null) => void;
  isSubmitting?: boolean;
}

const colors = [
  "#a78bfa",
  "#34d399",
  "#22d3ee",
  "#fbbf24",
  "#f43f5e",
  "#60a5fa",
];

/**
 * Maps a rail index to a stable color, cycling the palette.
 *
 * @param trackIndex - Zero-based rail column.
 * @returns Hex color for the rail.
 */
const getRailColor = (trackIndex: number) => colors[trackIndex % colors.length];

/**
 * Renders multi-branch history and reports the ingest target.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @param onSelect - Called with the chosen branch and optional commit SHA.
 * @param isSubmitting - Disables ingest while the parent submits.
 * @returns Timeline panel with rail graph, commit list, and ingest footer.
 */
export default function GitGraph({
  owner,
  repo,
  onSelect,
  isSubmitting = false,
}: GitGraphProps) {
  const {
    branches,
    commits,
    defaultBranch,
    selectedCommit,
    setSelectedCommit,
    loadingBranches,
    loadingCommits,
    error,
  } = useGitGraph({ owner, repo });

  const commitMap = new Map<string, number>();
  commits.forEach((c, idx) => commitMap.set(c.sha, idx));

  const tracks: number[] = [];
  const activeTracks: (string | null)[] = [];

  // Assign each commit a rail column, threading parent SHAs down the rails.
  for (let r = 0; r < commits.length; r++) {
    const commit = commits[r];
    const sha = commit.sha;

    let col = activeTracks.indexOf(sha);
    if (col === -1) {
      col = activeTracks.indexOf(null);
      if (col === -1) {
        col = activeTracks.length;
        activeTracks.push(sha);
      } else {
        activeTracks[col] = sha;
      }
    }
    tracks[r] = col;

    for (let i = 0; i < activeTracks.length; i++) {
      if (i !== col && activeTracks[i] === sha) {
        activeTracks[i] = null;
      }
    }

    activeTracks[col] = null;

    if (commit.parents.length > 0) {
      activeTracks[col] = commit.parents[0];
      for (let p = 1; p < commit.parents.length; p++) {
        const parentSha = commit.parents[p];
        let pCol = activeTracks.indexOf(parentSha);
        if (pCol === -1) {
          pCol = activeTracks.indexOf(null);
          if (pCol === -1) {
            activeTracks.push(parentSha);
          } else {
            activeTracks[pCol] = parentSha;
          }
        }
      }
    }
  }

  const activeTracksCount = Math.max(activeTracks.length, 1);
  const columnWidth = 20;
  const rowHeight = 56;
  const nodeRadius = 5;
  const paddingX = 16;
  const paddingY = 28;

  /** Converts a rail column to an SVG x-coordinate. */
  const getX = (col: number) => col * columnWidth + paddingX;
  /** Converts a commit row to an SVG y-coordinate. */
  const getY = (row: number) => row * rowHeight + paddingY;

  // Bezier links from each commit to its parents; stubs when parent is absent.
  const links: { path: string; stroke: string }[] = [];
  commits.forEach((commit, r) => {
    const col = tracks[r];
    const x1 = getX(col);
    const y1 = getY(r);
    const strokeColor = getRailColor(col);

    commit.parents.forEach((parentSha) => {
      const parentRow = commitMap.get(parentSha);
      if (parentRow !== undefined) {
        const parentCol = tracks[parentRow];
        const x2 = getX(parentCol);
        const y2 = getY(parentRow);

        const dy = y2 - y1;
        const cpY1 = y1 + dy * 0.45;
        const cpY2 = y2 - dy * 0.45;
        const path = `M ${x1} ${y1} C ${x1} ${cpY1}, ${x2} ${cpY2}, ${x2} ${y2}`;
        links.push({ path, stroke: strokeColor });
      } else {
        const path = `M ${x1} ${y1} L ${x1} ${y1 + rowHeight}`;
        links.push({ path, stroke: strokeColor });
      }
    });
  });

  /**
   * Toggles selection of a commit row.
   *
   * @param commit - Commit that was clicked.
   */
  const handleCommitClick = (commit: GitHubMultiBranchCommit) => {
    if (selectedCommit?.sha === commit.sha) {
      setSelectedCommit(null);
    } else {
      setSelectedCommit(commit);
    }
  };

  /** Reports the selected commit (or default branch) to the parent. */
  const handleIngest = () => {
    const targetBranch = selectedCommit?.branches[0] || defaultBranch;
    const targetSha = selectedCommit?.sha || null;
    onSelect(targetBranch, targetSha);
  };

  const selectedTarget = selectedCommit
    ? `commit ${selectedCommit.short_sha}`
    : `branch ${defaultBranch}`;

  return (
    <div className="w-full flex flex-col h-[550px] bg-(--background) rounded-sm border border-(--border) overflow-hidden relative">
      <div className="flex items-center justify-between p-4 border-b border-(--border) bg-(--secondary)/10">
        <div className="flex items-center gap-2">
          <GitBranchIcon size={20} className="text-(--primary)" />
          <span className="font-semibold text-sm">
            Unified Repository Timeline
          </span>
        </div>
        <div className="text-[10px] text-(--muted-foreground) flex gap-3">
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-violet-400" /> default
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" /> feature
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar relative">
        {error && (
          <div className="p-4 m-4 rounded bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
            {error}
          </div>
        )}

        {commits.length > 0 ? (
          <div
            className="relative"
            style={{ height: `${commits.length * rowHeight + 48}px` }}
          >
            <svg
              className="absolute top-0 left-0 h-full pointer-events-none"
              style={{
                width: `${activeTracksCount * columnWidth + paddingX * 2}px`,
              }}
            >
              {links.map((link, i) => (
                <path
                  key={i}
                  d={link.path}
                  fill="none"
                  stroke={link.stroke}
                  strokeWidth={2}
                  opacity={0.6}
                />
              ))}

              {commits.map((commit, r) => {
                const col = tracks[r];
                const isSelected = selectedCommit?.sha === commit.sha;
                const strokeColor = getRailColor(col);

                return (
                  <circle
                    key={commit.sha}
                    cx={getX(col)}
                    cy={getY(r)}
                    r={isSelected ? nodeRadius + 2.5 : nodeRadius}
                    fill={isSelected ? "var(--primary)" : "var(--background)"}
                    stroke={isSelected ? "#ffffff" : strokeColor}
                    strokeWidth={isSelected ? 2.5 : 2}
                    className="transition-all duration-300"
                  />
                );
              })}
            </svg>

            <div
              className="absolute top-0 right-0 left-0 flex flex-col"
              style={{
                paddingLeft: `${activeTracksCount * columnWidth + paddingX * 2}px`,
                paddingRight: "16px",
                paddingTop: `${paddingY - 28}px`,
              }}
            >
              {commits.map((commit, r) => {
                const isSelected = selectedCommit?.sha === commit.sha;

                return (
                  <div
                    key={commit.sha}
                    className="flex items-center h-[56px] cursor-pointer"
                    onClick={() => handleCommitClick(commit)}
                  >
                    <div
                      className={`flex-1 glass-card px-3 py-1.5 rounded-sm border transition-all duration-300 flex items-center justify-between gap-4 ${
                        isSelected
                          ? "border-(--primary)/50 bg-(--primary)/5 shadow-md shadow-(--primary)/5"
                          : "border-(--border) hover:border-(--primary)/30 hover:bg-(--secondary)/5"
                      }`}
                    >
                      <div className="min-w-0 flex-1 flex flex-col justify-center">
                        <div className="flex items-center gap-2">
                          <p className="text-xs font-semibold text-(--foreground) truncate max-w-[320px]">
                            {commit.message}
                          </p>
                          {commit.branches.map((b) => (
                            <span
                              key={b}
                              className="text-[8px] font-bold px-1 py-0.5 rounded bg-(--primary)/10 text-(--primary) border border-(--primary)/20 whitespace-nowrap"
                            >
                              {b}
                            </span>
                          ))}
                        </div>

                        <div className="flex items-center gap-1.5 mt-0.5">
                          {commit.author_avatar ? (
                            <img
                              src={commit.author_avatar}
                              alt={commit.author_name}
                              className="w-3.5 h-3.5 rounded-full object-cover"
                            />
                          ) : (
                            <div className="w-3.5 h-3.5 rounded-full bg-(--secondary) flex items-center justify-center text-[7px] font-bold">
                              {commit.author_name.charAt(0)}
                            </div>
                          )}
                          <span className="text-[10px] text-(--muted-foreground) truncate max-w-[100px]">
                            {commit.author_name}
                          </span>
                          <span className="text-[10px] text-(--muted-foreground)/50">
                            •
                          </span>
                          <span className="text-[10px] text-(--muted-foreground)/50">
                            {timeAgo(new Date(commit.authored_at))}
                          </span>
                        </div>
                      </div>

                      <span className="text-[9px] font-mono px-2 py-0.5 rounded bg-(--secondary) text-(--muted-foreground) shrink-0">
                        {commit.short_sha}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          !loadingCommits && (
            <div className="py-12 flex flex-col items-center justify-center text-(--muted-foreground)/60 h-full">
              <GitCommitIcon size={32} className="mb-2 opacity-40" />
              <p className="text-sm italic">No commits found.</p>
            </div>
          )
        )}

        {loadingCommits && (
          <div className="py-12 flex flex-col items-center justify-center gap-2 text-xs text-(--muted-foreground) absolute inset-0 bg-(--background)/60 backdrop-blur-xs z-20">
            <SpinnerIcon className="animate-spin text-(--primary)" size={24} />
            <span>Loading Git Graph...</span>
          </div>
        )}
      </div>

      <div className="p-4 border-t border-(--border) bg-(--secondary)/10 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="text-xs">
          <span className="text-(--muted-foreground)">Target Selection: </span>
          <span className="font-mono font-bold text-(--primary)">
            {selectedCommit
              ? `commit ${selectedCommit.short_sha} (${selectedCommit.branches[0]})`
              : `branch ${defaultBranch} (default)`}
          </span>
        </div>

        <button
          onClick={handleIngest}
          disabled={isSubmitting || commits.length === 0}
          className="w-full sm:w-auto bg-(--primary) hover:bg-(--primary)/90 text-white font-semibold text-xs px-5 py-2.5 rounded-sm transition-all shadow-lg shadow-(--primary)/20 hover:shadow-xl hover:shadow-(--primary)/30 disabled:opacity-50 disabled:pointer-events-none flex items-center justify-center gap-2"
        >
          {isSubmitting ? (
            <>
              <SpinnerIcon className="animate-spin" size={14} />
              <span>Ingesting...</span>
            </>
          ) : (
            <span>Ingest {selectedTarget}</span>
          )}
        </button>
      </div>
    </div>
  );
}
