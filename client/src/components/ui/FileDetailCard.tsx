/**
 * The explorer's detail section for the selected file: its risk, where it
 * sits in the reading order, who knows it, what it defines, where it has
 * been changing, and what it is connected to.
 * @module FileDetailCard
 */
import { resolveGithubRef } from "@/lib/github";
import { FileDetail, FileNode } from "@/types/explorer";
import type Ownership from "@/types/ownership";
import { timeAgo } from "@/utils/timeAgo";
import Link from "next/link";
import NeighbourhoodGraph from "./NeighbourhoodGraph";
import { RISK_DOT } from "./TreeNodeRenderer";

/** Rows the symbol list shows before it says how many more there are. */
const SYMBOL_ROWS = 8;

/** Rows each neighbour list shows before it says how many more there are. */
const NEIGHBOUR_ROWS = 10;

const OWNER_COLORS = ["#f6339a", "#53eafd", "#a855f7", "#facc15", "#22c55e"];

/** One file's ownership record. */
export type FileOwnership = Ownership["files"][number];

/**
 * Props for the FileDetailCard component.
 */
interface Props {
  file: FileNode;
  ownershipData: FileOwnership | null;
  isLoading: boolean;
  /** The file's symbols and recent commits, or null while unknown. */
  detail: FileDetail | null;
  isLoadingDetail: boolean;
  githubUrl: string;
  repoNumber: number;
  commitSha?: string | null;
  branch?: string | null;
  annotation: string | null;
  /** One-based reading-order position, when the file is on the order. */
  readingPosition: number | null;
  importers: FileNode[];
  imports: FileNode[];
  onSelectPath: (path: string) => void;
}

/**
 * A bordered pixel chip.
 *
 * @param color Text and border colour; neutral when absent.
 * @param children The chip's text.
 * @returns The chip.
 */
function Chip({
  color,
  children,
}: {
  color?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className="border px-2 py-1"
      style={
        color
          ? { borderColor: `${color}66`, color }
          : { borderColor: "var(--border)", color: "var(--muted-foreground)" }
      }
    >
      {children}
    </span>
  );
}

/**
 * A titled card of the detail grid.
 *
 * @param title The card's heading.
 * @param aside Shown at the right end of the title row.
 * @param children The body.
 * @returns The card.
 */
function DetailCard({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="panel flex min-w-0 flex-col gap-3.5 p-5">
      <div className="flex items-center justify-between gap-2">
        <h3 className="m-0 font-pixel text-xs font-normal tracking-[0.12em] text-(--muted-foreground) uppercase">
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/**
 * A blinking loading line for a card body.
 *
 * @param children What is loading.
 * @returns The line.
 */
function LoadingLine({ children }: { children: React.ReactNode }) {
  return (
    <p className="blink m-0 font-pixel text-xs tracking-[0.1em] text-(--muted-foreground) uppercase">
      {children}
    </p>
  );
}

/**
 * A quiet line for a card with nothing to list.
 *
 * @param children The message.
 * @returns The line.
 */
function EmptyLine({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 px-2 py-2 font-pixel text-xs text-(--faint-foreground) uppercase">
      {children}
    </p>
  );
}

/**
 * A list of connected files; each row selects that file.
 *
 * @param files The neighbours.
 * @param empty Shown when there are none.
 * @param onSelectPath Selects a file by path.
 * @returns The list.
 */
function NeighbourList({
  files,
  empty,
  onSelectPath,
}: {
  files: FileNode[];
  empty: string;
  onSelectPath: (path: string) => void;
}) {
  if (files.length === 0) {
    return (
      <p className="m-0 px-2 py-2 font-pixel text-xs text-(--faint-foreground) uppercase">
        {empty}
      </p>
    );
  }
  const shown = files.slice(0, NEIGHBOUR_ROWS);
  return (
    <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
      {shown.map((f) => (
        <li key={f.path}>
          <button
            type="button"
            onClick={() => onSelectPath(f.path)}
            title={f.path}
            className="flex w-full items-center gap-2.5 rounded-sm px-2 py-2 text-left font-pixel text-[13px] text-zinc-300 hover:cursor-pointer hover:bg-(--secondary)"
          >
            <span
              aria-hidden="true"
              className="h-1.5 w-1.5 shrink-0"
              style={{
                background:
                  RISK_DOT[(f.criticality ?? "").toLowerCase()] ?? "#22c55e",
              }}
            />
            <span className="truncate">{f.path}</span>
          </button>
        </li>
      ))}
      {files.length > shown.length && (
        <li className="px-2 py-1.5 font-pixel text-[11px] tracking-[0.06em] text-(--faint-foreground) uppercase">
          and {files.length - shown.length} more
        </li>
      )}
    </ul>
  );
}

/**
 * Renders the selected file's header, actions and detail cards.
 * @param file The selected file node.
 * @param ownershipData Ownership record for the file, or null when none.
 * @param isLoading When true, the ownership card shows its loading state.
 * @param detail The file's symbols and recent commits, if loaded.
 * @param isLoadingDetail When true, the symbol and history cards show their loading state.
 * @param githubUrl Repository URL used for the GitHub link.
 * @param repoNumber The repository's user-scoped number, for internal links.
 * @param commitSha The ingested commit, which the GitHub link pins to when set.
 * @param branch Repository's ingested branch, used when the SHA is missing.
 * @param annotation The reading-order note for the file, if any.
 * @param readingPosition The file's place on the reading order, if any.
 * @param importers Files that import this one.
 * @param imports Files this one imports.
 * @param onSelectPath Selects another file by path.
 * @returns The detail section.
 */
export default function FileDetailCard({
  file,
  ownershipData,
  isLoading,
  detail,
  isLoadingDetail,
  githubUrl,
  repoNumber,
  commitSha,
  branch,
  annotation,
  readingPosition,
  importers,
  imports,
  onSelectPath,
}: Props) {
  const githubRef = resolveGithubRef(commitSha, branch);
  const slash = file.path.lastIndexOf("/");
  const dir = slash > 0 ? file.path.slice(0, slash + 1) : "";
  const name = slash >= 0 ? file.path.slice(slash + 1) : file.path;
  const risk = (file.criticality ?? "").toLowerCase() || "safe";
  const riskColor = RISK_DOT[risk] ?? "#22c55e";
  const question = `What does ${file.path} do, and what depends on it?`;
  const contributors = ownershipData?.contributors ?? [];

  return (
    <section aria-label="File details" className="flex min-w-0 flex-col gap-4">
      <div className="panel flex min-w-0 flex-col gap-4 p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-2.5">
            {dir && (
              <span className="font-pixel text-[13px] text-(--subtle-foreground)">
                {dir}
              </span>
            )}
            <h2 className="m-0 font-pixel text-[clamp(2rem,4vw,3.2rem)] leading-none font-normal tracking-[-0.02em] break-all">
              {name}
            </h2>
            <div className="flex flex-wrap gap-1.5 font-pixel text-[11px] tracking-[0.08em] uppercase">
              <Chip color={riskColor}>{risk}</Chip>
              <Chip>{file.language || "Unknown"}</Chip>
              <Chip>{(file.loc || 0).toLocaleString()} LOC</Chip>
              <Chip>
                In {file.fan_in} · Out {file.fan_out}
              </Chip>
              {ownershipData?.is_knowledge_silo && (
                <Chip color="#facc15">Knowledge silo</Chip>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2 font-pixel text-[13px]">
            <Link
              href={`/repo/${repoNumber}/chat?q=${encodeURIComponent(question)}`}
              className="cta rounded-sm bg-(--primary) px-4 py-2.75 tracking-[0.04em] text-(--primary-foreground)"
            >
              Ask about this file →
            </Link>
            <Link
              href={`/repo/${repoNumber}/graph`}
              className="ghost rounded-sm border border-(--input) px-3.5 py-2.75 text-zinc-300 uppercase"
            >
              Graph
            </Link>
            <a
              href={`${githubUrl}/blob/${githubRef}/${file.path}`}
              target="_blank"
              rel="noopener noreferrer"
              className="ghost rounded-sm border border-(--input) px-3.5 py-2.75 text-zinc-300 uppercase"
            >
              GitHub <span aria-hidden="true">↗</span>
            </a>
          </div>
        </div>

        {annotation && (
          <p className="m-0 rounded-r-sm border-l-2 border-(--accent) bg-(--accent)/5 px-4 py-3.5 text-[15px] leading-relaxed text-zinc-300">
            {readingPosition !== null && (
              <span className="font-pixel text-(--accent)">
                Read {readingPosition} ·{" "}
              </span>
            )}
            {annotation}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="panel flex min-w-0 flex-col overflow-hidden">
          <div className="flex items-center justify-between gap-2 px-5 pt-5">
            <h3 className="m-0 font-pixel text-xs font-normal tracking-[0.12em] text-(--muted-foreground) uppercase">
              Neighbourhood
            </h3>
            <Link
              href={`/repo/${repoNumber}/graph`}
              className="font-pixel text-xs tracking-[0.06em] text-(--accent) uppercase hover:underline"
            >
              Open 3D <span aria-hidden="true">→</span>
            </Link>
          </div>
          <div aria-hidden="true" className="relative h-57.5">
            <NeighbourhoodGraph
              file={file}
              importers={importers}
              imports={imports}
            />
          </div>
        </section>

        <DetailCard
          title="Who to ask"
          aside={
            <span className="font-pixel text-xs tracking-[0.06em] text-(--faint-foreground) uppercase">
              Share of lines
            </span>
          }
        >
          {isLoading ? (
            <p className="blink m-0 font-pixel text-xs tracking-[0.1em] text-(--muted-foreground) uppercase">
              Loading ownership
            </p>
          ) : contributors.length > 0 ? (
            <ul className="m-0 flex list-none flex-col gap-3.5 p-0">
              {contributors.slice(0, 5).map((c, i) => (
                <li key={`${c.name}-${i}`} className="flex flex-col gap-1.5">
                  <span className="flex justify-between gap-3 text-sm">
                    <span className="truncate" title={c.name}>
                      {c.name}
                      {c.name === ownershipData?.primary_owner && (
                        <span className="ml-2 font-pixel text-[11px] tracking-[0.06em] text-(--accent) uppercase">
                          Owner
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 font-pixel text-xs text-(--muted-foreground)">
                      {c.percentage == null
                        ? "—"
                        : `${c.percentage.toFixed(1)}%`}
                    </span>
                  </span>
                  <span
                    aria-hidden="true"
                    className="block h-1.5 bg-(--secondary)"
                  >
                    <span
                      className="block h-1.5"
                      style={{
                        width: `${c.percentage || 0}%`,
                        background: OWNER_COLORS[i % OWNER_COLORS.length],
                      }}
                    />
                  </span>
                </li>
              ))}
              {ownershipData && (
                <li className="font-pixel text-[11px] tracking-[0.06em] text-(--faint-foreground) uppercase">
                  Bus factor {ownershipData.bus_factor} · {contributors.length}{" "}
                  {contributors.length === 1 ? "contributor" : "contributors"}
                </li>
              )}
            </ul>
          ) : (
            <p className="m-0 text-sm text-(--muted-foreground)">
              No ownership data. This file might not have enough history.
            </p>
          )}
        </DetailCard>

        <DetailCard
          title={`Symbols${detail ? ` · ${detail.symbols.length}` : ""}`}
        >
          {isLoadingDetail ? (
            <LoadingLine>Loading symbols</LoadingLine>
          ) : detail && detail.symbols.length > 0 ? (
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
              {detail.symbols.slice(0, SYMBOL_ROWS).map((symbol, i) => (
                <li key={`${symbol.name}-${symbol.start_line}-${i}`}>
                  <a
                    href={`${githubUrl}/blob/${githubRef}/${file.path}${symbol.start_line ? `#L${symbol.start_line}` : ""}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-3 rounded-sm px-2 py-2 font-pixel text-[13px] hover:bg-(--secondary)"
                  >
                    <span className="w-14 shrink-0 text-[11px] tracking-[0.06em] text-(--accent) uppercase">
                      {symbol.kind}
                    </span>
                    <span
                      className="min-w-0 flex-1 truncate text-zinc-300"
                      title={symbol.name}
                    >
                      {symbol.name}
                    </span>
                    {symbol.start_line != null && (
                      <span className="shrink-0 text-xs text-(--faint-foreground)">
                        L{symbol.start_line}
                      </span>
                    )}
                  </a>
                </li>
              ))}
              {detail.symbols.length > SYMBOL_ROWS && (
                <li className="px-2 py-1.5 font-pixel text-[11px] tracking-[0.06em] text-(--faint-foreground) uppercase">
                  and {detail.symbols.length - SYMBOL_ROWS} more
                </li>
              )}
            </ul>
          ) : (
            <EmptyLine>No functions or classes</EmptyLine>
          )}
        </DetailCard>

        <DetailCard title="Recent changes">
          {isLoadingDetail ? (
            <LoadingLine>Loading history</LoadingLine>
          ) : detail && detail.commits.length > 0 ? (
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
              {detail.commits.map((commit) => (
                <li key={commit.hash}>
                  <a
                    href={`${githubUrl}/commit/${commit.hash}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-3 rounded-sm px-2 py-2 hover:bg-(--secondary)"
                  >
                    <span className="shrink-0 pt-0.5 font-pixel text-xs text-(--accent)">
                      {commit.hash.slice(0, 7)}
                    </span>
                    <span className="flex min-w-0 flex-col gap-1">
                      <span
                        className="truncate text-sm text-zinc-300"
                        title={commit.title}
                      >
                        {commit.title || "No message"}
                      </span>
                      <span className="font-pixel text-[11px] tracking-[0.06em] text-(--faint-foreground) uppercase">
                        Commit · {commit.author} · {timeAgo(commit.at)}
                      </span>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyLine>No commits in the analysed history</EmptyLine>
          )}
        </DetailCard>

        <DetailCard title={`Imported by · ${importers.length}`}>
          <NeighbourList
            files={importers}
            empty="Nothing imports this file"
            onSelectPath={onSelectPath}
          />
        </DetailCard>

        <DetailCard title={`Imports · ${imports.length}`}>
          <NeighbourList
            files={imports}
            empty="No internal imports"
            onSelectPath={onSelectPath}
          />
        </DetailCard>
      </div>
    </section>
  );
}
