/**
 * Repository overview: the architecture brief, the repository at a glance,
 * where to start reading, what is risky to change, and who to ask.
 * @module RepositoryPage
 */
import { GetGuide, GetGuideStats, GetRecentActivity } from "@/api/guide";
import { GetRepository } from "@/api/repository";
import IngestFlow from "@/components/IngestFlow";
import { GraphTile, RiskSpread } from "@/components/OverviewGraphTiles";
import type Guide from "@/types/guide";
import type { ActivityItem, Stats } from "@/types/guide";
import { splitRepoName } from "@/utils/repoName";
import { statusView, syncView } from "@/utils/repoStatus";
import { stripLeadingTitle } from "@/utils/stripLeadingTitle";
import { timeAgo } from "@/utils/timeAgo";
import { cookies } from "next/headers";
import Link from "next/link";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Language colours, assigned in this fixed order by share of lines. The
 * legend names every segment, so colour is never the only cue.
 */
const LANGUAGE_COLORS = ["#53eafd", "#f6339a", "#facc15", "#a855f7", "#22c55e"];
const OTHER_COLOR = "#52525b";
const START_STEPS = 6;
const RISK_ROWS = 5;
const PEOPLE_ROWS = 4;
const PEOPLE_COLORS = ["#a3004c", "#0092b8", "#7e22ce", "#15803d"];

const RISK_COLOR: Record<string, string> = {
  critical: "#ef4444",
  caution: "#facc15",
};

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

/** A share as a whole percentage, with tiny shares shown as "<1%". */
function percent(share: number): string {
  return share < 0.01 ? "<1%" : `${Math.round(share * 100)}%`;
}

/** Where an activity item lives on GitHub. */
function activityHref(githubUrl: string, item: ActivityItem): string | null {
  if (item.kind === "pull_request" && item.number != null) {
    return `${githubUrl}/pull/${item.number}`;
  }
  if (item.kind === "commit" && item.hash)
    return `${githubUrl}/commit/${item.hash}`;
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

/**
 * Up to two initials for a contributor's tile.
 *
 * @param name The contributor's name as git records it.
 * @returns The initials, upper-cased.
 */
function initialsOf(name: string): string {
  const parts = name
    .trim()
    .split(/[\s._-]+/)
    .filter(Boolean);
  const letters =
    parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return letters.toUpperCase();
}

/**
 * One bento card with a pixel title row.
 *
 * @param title The card's heading.
 * @param action Shown at the right end of the title row.
 * @param className Grid placement.
 * @param children The card's body.
 * @returns The card.
 */
function Card({
  title,
  action,
  className = "",
  children,
}: {
  title: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`panel flex min-w-0 flex-col gap-4 p-5.5 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="m-0 font-pixel text-xs font-normal tracking-[0.12em] text-(--muted-foreground) uppercase">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A small pixel link in a card's title row. */
function CardLink({
  href,
  external = false,
  children,
}: {
  href: string;
  external?: boolean;
  children: ReactNode;
}) {
  const className =
    "font-pixel text-xs tracking-[0.06em] text-(--muted-foreground) uppercase hover:text-(--accent)";
  return external ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
    >
      {children}
    </a>
  ) : (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}

/** A pixel stat: big number over a small label. */
function Stat({
  label,
  value,
  hint,
  color,
}: {
  label: string;
  value: string;
  hint?: string;
  color?: string;
}) {
  return (
    <div title={hint} className="flex flex-col gap-0.5">
      <span className="font-pixel text-3xl leading-none" style={{ color }}>
        {value}
      </span>
      <span className="font-pixel text-[11px] tracking-[0.1em] text-(--subtle-foreground) uppercase">
        {label}
      </span>
    </div>
  );
}

/** One labelled row of the tech stack card. */
function StackRow({
  label,
  items,
  tone = "neutral",
}: {
  label: string;
  items: string[] | undefined | null;
  tone?: "neutral" | "accent" | "cyan";
}) {
  if (!items || items.length === 0) return null;
  const chip =
    tone === "accent"
      ? "border-(--accent)/40 text-(--accent)"
      : tone === "cyan"
        ? "border-(--chart-1)/35 text-(--chart-1)"
        : "border-(--border) text-zinc-300";
  return (
    <div className="flex items-start gap-3.5">
      <h3 className="m-0 w-26 shrink-0 pt-1.25 font-pixel text-[11px] font-normal tracking-[0.1em] text-(--subtle-foreground) uppercase">
        {label}
      </h3>
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
        {items.map((tool) => (
          <li
            key={tool}
            className={`rounded-[3px] border px-2.25 py-1.25 font-pixel text-xs ${chip}`}
          >
            {tool}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The riskiest files, as bars scaled to the busiest one's fan-in.
 *
 * @param files The guide's critical files.
 * @returns The list.
 */
function RiskList({ files }: { files: Guide["critical_files"] }) {
  const max = Math.max(1, ...files.map((f) => f.fan_in));
  return (
    <ul className="m-0 flex list-none flex-col gap-3 p-0">
      {files.map((f) => {
        const level = (f.criticality ?? "").toLowerCase();
        const color = RISK_COLOR[level] ?? "#22c55e";
        return (
          <li key={f.file_path} className="flex flex-col gap-1.5">
            <span className="flex justify-between gap-2 font-pixel text-[13px]">
              <span className="truncate" title={f.file_path}>
                {f.file_path}
              </span>
              <span
                className="shrink-0 text-[11px] tracking-[0.08em] uppercase"
                style={{ color }}
              >
                {level || "safe"}
              </span>
            </span>
            <span aria-hidden="true" className="block h-1.5 bg-(--secondary)">
              <span
                className="bar-fill block h-1.5"
                style={{
                  width: `${Math.max(4, (f.fan_in / max) * 100)}%`,
                  background: color,
                }}
              />
            </span>
            <span className="font-pixel text-[11px] tracking-[0.06em] text-(--faint-foreground) uppercase">
              Fan-in {f.fan_in}
              {f.change_frequency > 0 && ` · ${f.change_frequency} changes`}
              {!f.has_tests && " · no tests"}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Server-rendered overview when ready; the live ingest view otherwise.
 *
 * Each panel is left out when its data is missing, so a repository whose
 * guide or stats failed to load shows what it has rather than empty cards.
 *
 * @param params - Route params promise resolving to the repository number.
 * @returns Repository overview, or the live ingest view.
 */
export default async function Repository({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));

  // While indexing there is nothing to summarise yet, so the whole page
  // becomes the live progress view.
  if (repo.status !== "ready") {
    const cookieStore = await cookies();
    const token = cookieStore.get("access_token")?.value || "";
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
  const [guide, stats, activity] = await Promise.all([
    GetGuide(repo.id).catch(() => null),
    GetGuideStats(repo.id).catch(() => null),
    GetRecentActivity(repo.id).catch(() => null),
  ]);

  const { owner, name } = splitRepoName(repo.github_url, repo.name);
  const status = statusView(repo.status);
  const sync = syncView(repo);
  const explorerHref = (path: string) =>
    `/repo/${repo.repo_number}/explorer?file=${encodeURIComponent(path)}`;
  const shares = stats ? languageShares(stats) : [];
  const steps = guide?.reading_order?.slice(0, START_STEPS) ?? [];
  const risky = guide?.critical_files?.slice(0, RISK_ROWS) ?? [];
  const people = stats?.top_contributors?.slice(0, PEOPLE_ROWS) ?? [];
  const recent = activity ?? [];
  const stack = repo.detected_stack;
  const external = (guide?.architecture_brief?.external_integrations ?? []).map(
    (tool: string) => tool.charAt(0).toUpperCase() + tool.slice(1),
  );
  const hasStack = [
    stack?.languages,
    stack?.frameworks,
    stack?.databases,
    stack?.infrastructure,
    stack?.ci_cd,
    external,
  ].some((g) => g && g.length > 0);

  // Split the name so the last segment can carry the gradient.
  const cut = Math.max(
    name.lastIndexOf("-"),
    name.lastIndexOf("_"),
    name.lastIndexOf("."),
  );
  const head = cut > 0 ? name.slice(0, cut + 1) : "";
  const tail = cut > 0 ? name.slice(cut + 1) : name;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-7 px-4 pt-11 pb-16 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div className="flex min-w-0 flex-col gap-3.5">
          <div className="flex flex-wrap items-center gap-2.5 font-pixel text-xs tracking-[0.08em] uppercase">
            <span
              className="flex items-center gap-1.5 border px-2.25 py-1.25"
              style={{ borderColor: `${status.color}55`, color: status.color }}
            >
              <span
                className="h-1.5 w-1.5"
                style={{ background: status.color }}
              />
              {status.label}
            </span>
            {(repo.ingested_branch || repo.ingested_commit_sha) && (
              <span className="border border-(--border) px-2.25 py-1.25 text-(--muted-foreground) normal-case">
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
            )}
            <span className="flex items-center gap-1.5 border border-(--border) px-2.25 py-1.25 text-(--muted-foreground)">
              <span
                className={`h-1.5 w-1.5 ${sync.live ? "blink" : ""}`}
                style={{ background: sync.color }}
              />
              {sync.label}
            </span>
          </div>
          <h1 className="m-0 font-pixel text-[clamp(2.4rem,5vw,4.2rem)] leading-none font-normal tracking-[-0.02em] break-all">
            {head}
            <span className="gradient-text">{tail}</span>
          </h1>
          <a
            href={repo.github_url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-pixel text-[13px] text-(--muted-foreground) hover:text-(--accent)"
          >
            github.com/{owner ? `${owner}/` : ""}
            {name} <span aria-hidden="true">↗</span>
          </a>
        </div>
        <RiskSpread repoNumber={repo.repo_number} />
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Card
          title="Architecture brief"
          action={
            <CardLink href={`/repo/${repo.repo_number}/glossary`}>
              Glossary →
            </CardLink>
          }
          className="lg:col-span-8 lg:row-span-2 lg:min-h-112"
        >
          {repo.architecture_summary ? (
            // On wide screens the brief is taken out of flow and scrolls in its
            // card, so the rows are as tall as the graph and the glance cards
            // need and a long brief never stretches them.
            <div className="lg:relative lg:min-h-0 lg:flex-1">
              <div
                role="region"
                tabIndex={0}
                aria-label="Architecture brief"
                className="brief custom-scrollbar lg:absolute lg:inset-0 lg:overflow-y-auto lg:pr-3"
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {stripLeadingTitle(repo.architecture_summary)}
                </ReactMarkdown>
              </div>
            </div>
          ) : (
            <p className="m-0 font-pixel text-xs text-(--faint-foreground) uppercase">
              No architecture summary generated.
            </p>
          )}
        </Card>

        <GraphTile repoNumber={repo.repo_number} className="lg:col-span-4" />

        {stats && (
          <Card title="At a glance" className="lg:col-span-4">
            <div className="grid grid-cols-2 gap-x-3 gap-y-4">
              <Stat label="Files" value={compact.format(stats.total_files)} />
              <Stat
                label="Lines"
                value={compact.format(stats.total_loc)}
                hint={`${stats.total_loc.toLocaleString()} lines of code`}
              />
              <Stat
                label="Contributors"
                value={compact.format(stats.total_contributors)}
              />
              <Stat
                label="Silos"
                value={compact.format(stats.knowledge_silo_count)}
                hint="Files that only one person has worked on"
                color={stats.knowledge_silo_count > 0 ? "#facc15" : undefined}
              />
            </div>

            {shares.length > 0 && (
              <div className="flex flex-col gap-2.5">
                <div
                  className="flex h-2.5 gap-0.5"
                  role="img"
                  aria-label={`Lines by language: ${shares
                    .map((s) => `${s.name} ${percent(s.share)}`)
                    .join(", ")}`}
                >
                  {shares.map((s) => (
                    <span
                      key={s.name}
                      className="min-w-1"
                      style={{ flex: `${s.loc} 1 0`, background: s.color }}
                      title={`${s.name}: ${s.loc.toLocaleString()} lines in ${s.files} ${s.files === 1 ? "file" : "files"} (${percent(s.share)})`}
                    />
                  ))}
                </div>
                <ul className="m-0 flex list-none flex-wrap gap-x-3.5 gap-y-1.5 p-0">
                  {shares.map((s) => (
                    <li
                      key={s.name}
                      className="flex items-center gap-1.5 font-pixel text-[11px] text-(--muted-foreground)"
                    >
                      <span
                        aria-hidden="true"
                        className="h-1.5 w-1.5"
                        style={{ background: s.color }}
                      />
                      <span className="text-(--foreground)">{s.name}</span>
                      <span>{percent(s.share)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        )}

        {steps.length > 0 && (
          <Card
            title="Start here"
            action={
              <CardLink href={`/repo/${repo.repo_number}/graph`}>
                Full reading tour →
              </CardLink>
            }
            className="lg:col-span-4"
          >
            <ol className="m-0 flex list-none flex-col gap-0.5 p-0">
              {steps.map((step) => (
                <li key={step.file_path}>
                  <Link
                    href={explorerHref(step.file_path)}
                    className="flex items-start gap-3 rounded-sm px-2 py-2.25 hover:bg-(--secondary)"
                  >
                    <span
                      className={`w-5.5 shrink-0 font-pixel text-[13px] ${step.position === 1 ? "text-(--accent)" : "text-(--faint-foreground)"}`}
                    >
                      {String(step.position).padStart(2, "0")}
                    </span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="truncate font-pixel text-[13px]">
                        {step.file_path}
                      </span>
                      {step.annotation && (
                        <span className="line-clamp-2 text-xs text-(--subtle-foreground)">
                          {step.annotation}
                        </span>
                      )}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </Card>
        )}

        {risky.length > 0 && (
          <Card
            title="Riskiest to change"
            action={
              <CardLink href={`/repo/${repo.repo_number}/explorer`}>
                Explorer →
              </CardLink>
            }
            className="lg:col-span-4"
          >
            <RiskList files={risky} />
          </Card>
        )}

        {recent.length > 0 && (
          <Card
            title="Recent activity"
            action={
              <CardLink href={repo.github_url} external>
                GitHub ↗
              </CardLink>
            }
            className="lg:col-span-4"
          >
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
              {recent.map((item) => {
                const href = activityHref(repo.github_url, item);
                const isPr = item.kind === "pull_request";
                const tag = isPr
                  ? `#${item.number}`
                  : (item.hash ?? "").slice(0, 7);
                const meta = [item.author, when(item.at)]
                  .filter(Boolean)
                  .join(" · ");
                const body = (
                  <>
                    <span
                      className={`w-14.5 shrink-0 font-pixel text-xs ${isPr ? "text-(--accent)" : "text-(--chart-1)"}`}
                    >
                      {tag}
                    </span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span
                        className="truncate text-[13px] leading-snug"
                        title={item.title}
                      >
                        {item.title}
                      </span>
                      <span className="font-pixel text-[11px] tracking-[0.04em] text-(--subtle-foreground)">
                        {meta}
                      </span>
                    </span>
                  </>
                );
                return (
                  <li key={`${item.kind}-${item.number ?? item.hash}`}>
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={item.title}
                        className="flex items-start gap-3 rounded-sm px-2 py-2.25 hover:bg-(--secondary)"
                      >
                        {body}
                      </a>
                    ) : (
                      <div className="flex items-start gap-3 px-2 py-2.25">
                        {body}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </Card>
        )}

        {hasStack && (
          <Card title="Tech stack" className="lg:col-span-6">
            <div className="flex flex-col gap-3.5">
              <StackRow
                label="Languages"
                items={stack?.languages}
                tone="accent"
              />
              <StackRow
                label="Frameworks"
                items={stack?.frameworks}
                tone="cyan"
              />
              <StackRow label="Databases" items={stack?.databases} />
              <StackRow label="Infra" items={stack?.infrastructure} />
              <StackRow label="CI / CD" items={stack?.ci_cd} />
              <StackRow label="External" items={external} />
            </div>
          </Card>
        )}

        {people.length > 0 && (
          <Card
            title="Who to ask"
            action={
              <span className="font-pixel text-xs tracking-[0.06em] text-(--faint-foreground) uppercase">
                From git history
              </span>
            }
            className="lg:col-span-6"
          >
            <ul className="m-0 flex list-none flex-col gap-3 p-0">
              {people.map((p, i) => (
                <li key={p.name} className="flex items-center gap-3.5">
                  <span
                    aria-hidden="true"
                    className="flex h-8.5 w-8.5 shrink-0 items-center justify-center font-pixel text-[13px]"
                    style={{
                      background: PEOPLE_COLORS[i % PEOPLE_COLORS.length],
                    }}
                  >
                    {initialsOf(p.name)}
                  </span>
                  <span className="min-w-0 grow truncate text-sm">
                    {p.name}
                  </span>
                  <span className="shrink-0 font-pixel text-xs text-(--muted-foreground)">
                    {p.files_owned} files
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}
