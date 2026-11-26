/**
 * Unified commit timeline with branch lanes and ingest targeting.
 * @module GitGraph
 */
"use client";

import { useGitGraph } from "@/hooks/useGitGraph";
import { GitHubMultiBranchCommit } from "@/types/github";
import { timeAgo } from "@/utils/timeAgo";

/** Props for the repository timeline selector. */
interface GitGraphProps {
  owner: string;
  repo: string;
  onSelect: (branch: string, commitSha: string | null) => void;
  isSubmitting?: boolean;
  onBack?: () => void;
  note?: string;
}

/** Lane colours, in the order lanes are allocated: the first lane is the mainline. */
const colors = ["#f6339a", "#53eafd", "#facc15", "#a855f7", "#22c55e", "#0078ff"];

/**
 * Maps a lane index to a stable color, cycling the palette.
 *
 * @param trackIndex - Zero-based lane column.
 * @returns Hex color for the lane.
 */
const getRailColor = (trackIndex: number) => colors[trackIndex % colors.length];

const COLUMN_WIDTH = 20;
const ROW_HEIGHT = 48;
const PADDING_X = 16;
const PADDING_Y = 24;

/**
 * Assigns each commit a lane, threading parent SHAs down the lanes so every
 * branch in view shares one timeline.
 *
 * @param commits - Commits newest first.
 * @returns The lane per row and the total lane count.
 */
function assignLanes(commits: GitHubMultiBranchCommit[]): {
  tracks: number[];
  lanes: number;
} {
  const tracks: number[] = [];
  const active: (string | null)[] = [];

  for (let r = 0; r < commits.length; r++) {
    const commit = commits[r];
    const sha = commit.sha;

    let col = active.indexOf(sha);
    if (col === -1) {
      col = active.indexOf(null);
      if (col === -1) {
        col = active.length;
        active.push(sha);
      } else {
        active[col] = sha;
      }
    }
    tracks[r] = col;

    for (let i = 0; i < active.length; i++) {
      if (i !== col && active[i] === sha) active[i] = null;
    }
    active[col] = null;

    if (commit.parents.length > 0) {
      active[col] = commit.parents[0];
      for (let p = 1; p < commit.parents.length; p++) {
        const parentSha = commit.parents[p];
        if (active.indexOf(parentSha) !== -1) continue;
        const free = active.indexOf(null);
        if (free === -1) active.push(parentSha);
        else active[free] = parentSha;
      }
    }
  }

  return { tracks, lanes: Math.max(active.length, ...tracks.map((t) => t + 1), 1) };
}

/**
 * Renders multi-branch history and reports the ingest target.
 *
 * Nothing is selected at first, which means "the default branch at its tip";
 * clicking a commit pins that exact commit instead, and clicking it again
 * goes back to the tip.
 *
 * @param owner - GitHub repository owner.
 * @param repo - GitHub repository name.
 * @param onSelect - Called with the chosen branch and optional commit SHA.
 * @param isSubmitting - Disables ingest while the parent submits.
 * @param onBack - When given, a Back button in the footer returns to the repository list.
 * @param note - Optional line shown beside the action, such as the free-tier cost.
 * @returns Timeline panel with lane graph, commit list, and ingest footer.
 */
export default function GitGraph({
  owner,
  repo,
  onSelect,
  isSubmitting = false,
  onBack,
  note,
}: GitGraphProps) {
  const {
    commits,
    defaultBranch,
    selectedCommit,
    setSelectedCommit,
    loadingBranches,
    loadingCommits,
    error,
  } = useGitGraph({ owner, repo });

  const rowOf = new Map<string, number>();
  commits.forEach((c, idx) => rowOf.set(c.sha, idx));
  const { tracks, lanes } = assignLanes(commits);
  const graphWidth = lanes * COLUMN_WIDTH + PADDING_X * 2;
  const graphHeight = commits.length * ROW_HEIGHT;

  /** Converts a lane to an SVG x-coordinate. */
  const getX = (col: number) => col * COLUMN_WIDTH + PADDING_X;
  /** Converts a commit row to an SVG y-coordinate. */
  const getY = (row: number) => row * ROW_HEIGHT + PADDING_Y;

  // Curves from each commit to its parents; a stub when the parent is off the list.
  const links: { path: string; stroke: string }[] = [];
  commits.forEach((commit, r) => {
    const x1 = getX(tracks[r]);
    const y1 = getY(r);
    const stroke = getRailColor(tracks[r]);
    commit.parents.forEach((parentSha) => {
      const parentRow = rowOf.get(parentSha);
      if (parentRow === undefined) {
        links.push({ path: `M ${x1} ${y1} L ${x1} ${y1 + ROW_HEIGHT}`, stroke });
        return;
      }
      const x2 = getX(tracks[parentRow]);
      const y2 = getY(parentRow);
      const dy = y2 - y1;
      links.push({
        path: `M ${x1} ${y1} C ${x1} ${y1 + dy * 0.45}, ${x2} ${y2 - dy * 0.45}, ${x2} ${y2}`,
        stroke,
      });
    });
  });

  /** Each branch the timeline shows, coloured by the lane its tip sits on. */
  const legend: { name: string; color: string }[] = [];
  const seen = new Set<string>();
  commits.forEach((commit, r) => {
    for (const b of commit.branches) {
      if (seen.has(b)) continue;
      seen.add(b);
      legend.push({ name: b, color: getRailColor(tracks[r]) });
    }
  });

  /**
   * Toggles selection of a commit row.
   *
   * @param commit - Commit that was clicked.
   */
  const handleCommitClick = (commit: GitHubMultiBranchCommit) => {
    setSelectedCommit(selectedCommit?.sha === commit.sha ? null : commit);
  };

  /** Reports the selected commit (or default branch) to the parent. */
  const handleIngest = () => {
    const targetBranch = selectedCommit?.branches[0] || defaultBranch;
    const targetSha = selectedCommit?.sha || null;
    onSelect(targetBranch, targetSha);
  };

  const onBranch = selectedCommit?.branches[0];
  const targetLabel = selectedCommit
    ? `Ingest commit ${selectedCommit.short_sha}${onBranch ? ` on ${onBranch}` : ""} →`
    : `Ingest branch ${defaultBranch} @ tip →`;

  return (
    <div className="flex flex-col">
      <div className="mx-5 overflow-hidden rounded-sm border border-white/8 bg-(--background)">
        <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-white/8 px-3.5 py-2.5 font-pixel text-[11px] tracking-[0.1em] text-(--muted-foreground)">
          <span className="uppercase">All branches · one timeline</span>
          <ul aria-label="Branches" className="m-0 flex list-none flex-wrap gap-3 p-0">
            {legend.map(({ name, color }) => (
              <li key={name} className="flex items-center gap-1.5">
                <span aria-hidden="true" className="h-2 w-2" style={{ background: color }} />
                {name}
              </li>
            ))}
          </ul>
        </div>

        <div className="relative max-h-90 min-h-40 overflow-y-auto [scrollbar-width:thin]">
          {error && (
            <div
              role="alert"
              className="m-4 rounded-sm border border-red-500/25 bg-red-500/5 p-3 text-xs text-red-300"
            >
              {error}
            </div>
          )}

          {commits.length > 0 && (
            <div className="relative flex" style={{ minHeight: graphHeight }}>
              <svg
                width={graphWidth}
                height={graphHeight}
                viewBox={`0 0 ${graphWidth} ${graphHeight}`}
                aria-hidden="true"
                className="block shrink-0"
              >
                {links.map((link, i) => (
                  <path
                    key={i}
                    d={link.path}
                    stroke={link.stroke}
                    strokeWidth={2}
                    fill="none"
                  />
                ))}
                {commits.map((commit, r) => {
                  const on = selectedCommit?.sha === commit.sha;
                  const color = getRailColor(tracks[r]);
                  const size = on ? 12 : 10;
                  return (
                    <rect
                      key={commit.sha}
                      x={getX(tracks[r]) - size / 2}
                      y={getY(r) - size / 2}
                      width={size}
                      height={size}
                      fill={on ? color : "#09090b"}
                      stroke={on ? "#fafafa" : color}
                      strokeWidth={2}
                    />
                  );
                })}
              </svg>
              <div className="flex min-w-0 grow flex-col">
                {commits.map((commit, r) => {
                  const on = selectedCommit?.sha === commit.sha;
                  const color = getRailColor(tracks[r]);
                  return (
                    <button
                      key={commit.sha}
                      type="button"
                      aria-pressed={on}
                      onClick={() => handleCommitClick(commit)}
                      className={`flex h-12 w-full items-center gap-3 pr-3.5 pl-1 text-left hover:cursor-pointer hover:bg-(--secondary) ${on ? "bg-(--secondary)" : ""}`}
                    >
                      <span
                        className={`w-15.5 shrink-0 font-pixel text-xs ${on ? "text-(--foreground)" : "text-(--muted-foreground)"}`}
                      >
                        {commit.short_sha}
                      </span>
                      <span className="flex min-w-0 grow items-center gap-2 overflow-hidden">
                        {commit.branches.map((b) => (
                          <span
                            key={b}
                            className="shrink-0 border px-1.5 py-0.5 font-pixel text-[10px] tracking-[0.04em]"
                            style={{ borderColor: color, color }}
                          >
                            <span aria-hidden="true">⎇ </span>
                            <span>{b}</span>
                          </span>
                        ))}
                        <span className="min-w-0 truncate text-sm text-zinc-300">
                          {commit.message}
                        </span>
                      </span>
                      <span className="hidden shrink-0 font-pixel text-[11px] whitespace-nowrap text-(--subtle-foreground) sm:inline">
                        {commit.author_name} · {timeAgo(new Date(commit.authored_at))}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {commits.length === 0 &&
            !error &&
            (loadingCommits || loadingBranches ? (
              <p className="blink m-0 py-12 text-center font-pixel text-xs tracking-[0.12em] text-(--muted-foreground) uppercase">
                Loading history
              </p>
            ) : (
              <p className="m-0 py-12 text-center font-pixel text-xs text-(--faint-foreground) uppercase">
                No commits found
              </p>
            ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            aria-label="Back to repository list"
            className="ghost rounded-sm border border-(--input) px-3.5 py-2.5 font-pixel text-xs text-zinc-300 uppercase hover:cursor-pointer"
          >
            ← Back
          </button>
        )}
        <span className="grow text-right font-pixel text-[11px] tracking-[0.06em] text-(--subtle-foreground) uppercase">
          {note}
        </span>
        <button
          type="button"
          onClick={handleIngest}
          disabled={isSubmitting || commits.length === 0}
          className="cta rounded-sm bg-(--primary) px-5 py-2.75 font-pixel text-[13px] tracking-[0.06em] text-(--primary-foreground) hover:cursor-pointer disabled:cursor-default disabled:opacity-50"
        >
          {isSubmitting ? "Ingesting..." : targetLabel}
        </button>
      </div>
    </div>
  );
}
