/**
 * Repository overview: architecture summary, tech stack, where to start
 * reading, and what has changed lately.
 * @module RepositoryPage
 */
import { GetGuide, GetGuideStats, GetRecentActivity } from "@/api/guide";
import { GetRepository } from "@/api/repository";
import IngestFlow from "@/components/IngestFlow";
import DashboardCard from "@/components/ui/DashboardCard";
import { resolveGithubRef } from "@/lib/github";
import type { ActivityItem, Stats } from "@/types/guide";
import { stripLeadingTitle } from "@/utils/stripLeadingTitle";
import { timeAgo } from "@/utils/timeAgo";
import {
  ArrowRightIcon,
  ArrowSquareOutIcon,
  AtomIcon,
  BookOpenIcon,
  ChartBarIcon,
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  CodeIcon,
  DatabaseIcon,
  GitBranchIcon,
  GitCommitIcon,
  GithubLogoIcon,
  GitPullRequestIcon,
  LinkIcon,
  TreeStructureIcon,
  WrenchIcon,
} from "@phosphor-icons/react/dist/ssr";
import { cookies } from "next/headers";
import Link from "next/link";
import type { ElementType } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Language colours, assigned in this fixed order by share of lines. Checked
 * for contrast and colour-blind separation against the dark surface; the
 * legend names every segment, so colour is never the only cue.
 */
const LANGUAGE_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"];
const OTHER_COLOR = "#52514e";
const START_STEPS = 8;

const compact = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** The share of lines per language: the top five, then everything else together. */
function languageShares(stats: Stats) {
  const rows = [...(stats.language_breakdown ?? [])]
    .filter((row) => row.loc_count > 0)
    .sort((a, b) => b.loc_count - a.loc_count);
  const total = rows.reduce((sum, row) => sum + row.loc_count, 0);
  if (total === 0) return [];
  const top = rows.slice(0, LANGUAGE_COLORS.length).map((row, i) => ({
    name: row.language,
    loc: row.loc_count,
    files: row.file_count,
    share: row.loc_count / total,
    color: LANGUAGE_COLORS[i],
  }));
  const rest = rows.slice(LANGUAGE_COLORS.length);
  if (rest.length > 0) {
    const loc = rest.reduce((sum, row) => sum + row.loc_count, 0);
    top.push({
      name: "Other",
      loc,
      files: rest.reduce((sum, row) => sum + row.file_count, 0),
      share: loc / total,
      color: OTHER_COLOR,
    });
  }
  return top;
}

function percent(share: number): string {
  return share < 0.01 ? "<1%" : `${Math.round(share * 100)}%`;
}

/** Where an activity item lives on GitHub. */
function activityHref(githubUrl: string, item: ActivityItem): string | null {
  if (item.kind === "pull_request" && item.number != null) {
    return `${githubUrl}/pull/${item.number}`;
  }
  if (item.kind === "commit" && item.hash) return `${githubUrl}/commit/${item.hash}`;
  return null;
}

/** A relative time that never throws on a malformed timestamp. */
function when(at: string): string {
  try {
    return timeAgo(at);
  } catch {
    return "";
  }
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div title={hint}>
      <p className="text-xl font-bold tabular-nums text-(--foreground)">{value}</p>
      <p className="text-[10px] font-semibold uppercase tracking-widest text-(--muted-foreground)">
        {label}
      </p>
    </div>
  );
}

/** One group of detected tools in the tech stack panel. */
function StackGroup({
  icon: Icon,
  label,
  items,
  tone = "chart",
}: {
  icon: ElementType;
  label: string;
  items: string[] | undefined | null;
  tone?: "chart" | "accent";
}) {
  const chip =
    tone === "accent"
      ? "bg-(--destructive)/10 text-(--destructive) border-(--destructive)/20"
      : "bg-(--chart-1)/10 text-(--chart-1) border-(--chart-1)/20";
  return (
    <div>
      <h3 className="text-[10px] font-bold uppercase tracking-widest text-(--muted-foreground) mb-1.5 flex items-center gap-1.5">
        <Icon size={12} /> {label}
      </h3>
      {items && items.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {items.map((tool, i) => (
            <span key={i} className={`px-2 py-0.5 border text-[10px] font-mono ${chip}`}>
              {tool}
            </span>
          ))}
        </div>
      ) : (
        <span className="text-xs text-(--muted-foreground)/50 italic">None detected</span>
      )}
    </div>
  );
}

/**
 * Server-rendered overview: summary, stack and onboarding panels when ready,
 * live logs while indexing.
 *
 * Each onboarding panel is left out when its data is missing, so a repository
 * whose guide or stats failed to load shows what it has rather than empty
 * cards.
 *
 * @param params - Route params promise resolving to the repository id.
 * @returns Repository overview, or the live logs.
 */
export default async function Repository({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));

  const isReady = repo.status === "ready";

  // Guide is only available after indexing; live logs need the auth token.
  const guide = isReady ? await GetGuide(repo.id) : null;

  const cookieStore = await cookies();
  const token = cookieStore.get("access_token")?.value || "";

  // While indexing there is nothing to summarise yet, so the whole page
  // becomes the live progress view.
  if (!isReady) {
    return (
      <IngestFlow
        repoId={repo.id}
        token={token}
        repoLabel={repo.github_url.split("github.com/")[1]}
        branch={repo.ingested_branch}
        commitSha={repo.ingested_commit_sha}
        status={repo.status}
      />
    );
  }

  // The panels are extras: a failed call leaves its panel out rather than
  // failing the page.
  const [stats, activity] = await Promise.all([
    GetGuideStats(repo.id).catch(() => null),
    GetRecentActivity(repo.id).catch(() => null),
  ]);

  const ref = resolveGithubRef(repo.ingested_commit_sha, repo.ingested_branch);
  const fileHref = (path: string) => `${repo.github_url}/blob/${ref}/${path}`;
  const shares = stats ? languageShares(stats) : [];
  const steps = guide?.reading_order?.slice(0, START_STEPS) ?? [];
  const recent = activity ?? [];
  const stack = repo.detected_stack;
  const external = (guide?.architecture_brief?.external_integrations ?? []).map(
    (tool: string) => tool.charAt(0).toUpperCase() + tool.slice(1),
  );

  return (
    <main className="p-4 flex flex-col gap-4 max-w-7xl mx-auto lg:h-[calc(100vh-64px)] lg:flex-row">
      <section className="w-full flex flex-col gap-4 lg:h-full lg:w-1/2">
        <div className="grid grid-cols-1 gap-4 shrink-0 sm:grid-cols-2 sm:h-30">
          <DashboardCard href={repo.github_url}>
            <div className="absolute inset-0 bg-linear-to-br from-(--primary)/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="absolute top-4 right-4 text-(--muted-foreground) group-hover:text-(--foreground) transition-colors">
              <LinkIcon size={20} />
            </div>
            <div className="flex flex-col justify-between h-full">
              <div className="flex justify-between items-start">
                <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
                  Repository
                </span>
                {repo.ingested_branch && (
                  <span className="mr-7 text-[10px] font-mono bg-(--primary)/10 text-(--primary) px-2 py-0.5 rounded border border-(--primary)/20 flex items-center gap-1 shrink-0">
                    <GitBranchIcon size={12} />
                    {repo.ingested_branch}
                    {repo.ingested_commit_sha && (
                      <span className="opacity-75">
                        @{repo.ingested_commit_sha.substring(0, 7)}
                      </span>
                    )}
                  </span>
                )}
              </div>
              <h2 className="text-2xl font-bold flex items-center gap-3 text-(--foreground) truncate">
                <GithubLogoIcon size={28} weight="fill" className="text-(--primary) shrink-0" />
                <span className="truncate">{repo.github_url.split("github.com/")[1]}</span>
              </h2>
            </div>
          </DashboardCard>

          <DashboardCard className="justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
              Processing Status
            </span>
            <div className="flex items-end justify-between">
              {/* Reaching this card means the repository is indexed, so the
                  status is always the terminal one here. */}
              <div className="flex items-center gap-2 font-bold text-xl uppercase text-(--success)">
                <CheckCircleIcon size={24} weight="fill" />
                {repo.status}
              </div>
              <div className="text-right text-xs text-(--muted-foreground)">
                <p>Updated: {timeAgo(repo.updated_at)}</p>
                <p className="opacity-60">Created: {timeAgo(repo.created_at)}</p>
              </div>
            </div>
          </DashboardCard>
        </div>

        <DashboardCard
          icon={TreeStructureIcon}
          title="AI Architecture Overview"
          className="flex-1 min-h-80 relative overflow-hidden lg:min-h-0"
        >
          {repo.architecture_summary ? (
            <div className="overflow-y-auto custom-scrollbar pr-2.5 text-sm text-(--muted-foreground) leading-relaxed text-justify prose prose-sm dark:prose-invert">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {stripLeadingTitle(repo.architecture_summary)}
              </ReactMarkdown>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-(--muted-foreground) text-sm italic">
              No architecture summary generated.
            </div>
          )}
        </DashboardCard>

        <DashboardCard icon={AtomIcon} title="Tech Stack Detected" className="shrink-0">
          <div className="flex-1 overflow-y-auto custom-scrollbar pr-2 grid grid-cols-2 gap-x-6 gap-y-3">
            <StackGroup icon={CodeIcon} label="Languages" items={stack?.languages} tone="accent" />
            <StackGroup icon={WrenchIcon} label="Frameworks" items={stack?.frameworks} />
            <StackGroup icon={DatabaseIcon} label="Databases" items={stack?.databases} />
            <StackGroup icon={DatabaseIcon} label="Infrastructure" items={stack?.infrastructure} />
            <StackGroup icon={GitBranchIcon} label="CI/CD And Infra" items={stack?.ci_cd} />
            <StackGroup icon={DatabaseIcon} label="External" items={external} />
          </div>
        </DashboardCard>
      </section>

      <section className="w-full flex flex-col gap-4 lg:h-full lg:w-1/2">
        {stats && (
          <DashboardCard icon={ChartBarIcon} title="At a Glance" className="shrink-0">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Files" value={compact.format(stats.total_files)} />
              <Stat
                label="Lines"
                value={compact.format(stats.total_loc)}
                hint={`${stats.total_loc.toLocaleString()} lines of code`}
              />
              <Stat label="Contributors" value={compact.format(stats.total_contributors)} />
              <Stat
                label="Silos"
                value={compact.format(stats.knowledge_silo_count)}
                hint="Files that only one person has worked on"
              />
            </div>

            {shares.length > 0 && (
              <div className="mt-4">
                <div
                  className="flex h-2.5 w-full gap-0.5 overflow-hidden rounded-full"
                  role="img"
                  aria-label={`Lines by language: ${shares
                    .map((s) => `${s.name} ${percent(s.share)}`)
                    .join(", ")}`}
                >
                  {shares.map((s) => (
                    <span
                      key={s.name}
                      className="h-full first:rounded-l-full last:rounded-r-full"
                      style={{
                        width: `${Math.max(s.share * 100, 1)}%`,
                        backgroundColor: s.color,
                      }}
                      title={`${s.name}: ${s.loc.toLocaleString()} lines in ${s.files} ${s.files === 1 ? "file" : "files"} (${percent(s.share)})`}
                    />
                  ))}
                </div>
                <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                  {shares.map((s) => (
                    <li
                      key={s.name}
                      className="flex items-center gap-1.5 text-xs text-(--muted-foreground)"
                    >
                      <span
                        aria-hidden="true"
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: s.color }}
                      />
                      <span className="text-(--foreground)">{s.name}</span>
                      <span className="tabular-nums">{percent(s.share)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </DashboardCard>
        )}

        {steps.length > 0 && (
          <DashboardCard
            icon={BookOpenIcon}
            title="Start Here"
            className="flex-[9] min-h-0"
            action={
              <Link
                href={`/repo/${repo.repo_number}/graph`}
                className="flex shrink-0 items-center gap-1 text-xs text-(--muted-foreground) hover:text-(--foreground)"
              >
                Full reading tour
                <ArrowRightIcon size={12} />
              </Link>
            }
          >
            <ol className="min-h-0 space-y-3 overflow-y-auto custom-scrollbar pr-2">
              {steps.map((step) => (
                <li key={step.file_path} className="flex gap-3">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-(--primary)/30 bg-(--primary)/10 text-[10px] font-bold text-(--primary)">
                    {step.position}
                  </span>
                  <div className="min-w-0">
                    <a
                      href={fileHref(step.file_path)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex items-center gap-1 font-mono text-xs text-(--foreground) hover:text-(--primary)"
                    >
                      <span className="truncate">{step.file_path}</span>
                      <ArrowSquareOutIcon
                        size={11}
                        className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                      />
                    </a>
                    {step.annotation && (
                      <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-(--muted-foreground)">
                        {step.annotation}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </DashboardCard>
        )}

        {recent.length > 0 && (
          <DashboardCard
            icon={ClockCounterClockwiseIcon}
            title="Recent Activity"
            className="flex-[5] min-h-0"
          >
            <ul className="min-h-0 space-y-2.5 overflow-y-auto custom-scrollbar pr-2">
              {recent.map((item) => {
                const href = activityHref(repo.github_url, item);
                const Icon = item.kind === "pull_request" ? GitPullRequestIcon : GitCommitIcon;
                const tag =
                  item.kind === "pull_request" ? `#${item.number}` : (item.hash ?? "").slice(0, 7);
                return (
                  <li
                    key={`${item.kind}-${item.number ?? item.hash}`}
                    className="flex items-start gap-2.5"
                  >
                    <Icon
                      size={14}
                      className={`mt-0.5 shrink-0 ${item.kind === "pull_request" ? "text-(--primary)" : "text-(--muted-foreground)"}`}
                    />
                    <div className="min-w-0 flex-1">
                      {href ? (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block truncate text-xs text-(--foreground) hover:text-(--primary)"
                          title={item.title}
                        >
                          {item.title}
                        </a>
                      ) : (
                        <p className="truncate text-xs text-(--foreground)" title={item.title}>
                          {item.title}
                        </p>
                      )}
                      <p className="mt-0.5 truncate text-[11px] text-(--muted-foreground)">
                        <span className="font-mono">{tag}</span> · {item.author}
                        {when(item.at) && ` · ${when(item.at)}`}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          </DashboardCard>
        )}
      </section>
    </main>
  );
}
