/**
 * Expandable citation card for a single RAG source.
 * @module CitationCard
 */
import ChatMessage from "@/types/chat";
import {
  CaretDownIcon,
  CodeIcon,
  FileDocIcon,
  FileCodeIcon,
  GitCommitIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import { GithubLogoIcon } from "@phosphor-icons/react/dist/ssr";
import { useState } from "react";

/** Known source kinds; anything else falls back to "document". */
type SourceType = "symbol" | "commit" | "pull_request" | "file" | "document";
/** A single citation entry from a chat message. */
type Source = ChatMessage["sources"][number];

const TYPE_CONFIG: Record<
  SourceType,
  {
    icon: React.ElementType;
    color: string;
    bg: string;
    label: string;
  }
> = {
  symbol: {
    icon: CodeIcon,
    color: "text-yellow-500",
    bg: "bg-yellow-500/10",
    label: "Symbol",
  },
  commit: {
    icon: GitCommitIcon,
    color: "text-purple-500",
    bg: "bg-purple-500/10",
    label: "Commit",
  },
  pull_request: {
    icon: GitPullRequestIcon,
    color: "text-[var(--chart-2)]",
    bg: "bg-[var(--chart-2)]/10",
    label: "Pull Request",
  },
  file: {
    icon: FileCodeIcon,
    color: "text-pink-500",
    bg: "bg-pink-500/10",
    label: "File",
  },
  document: {
    icon: FileDocIcon,
    color: "text-pink-500",
    bg: "bg-green-500/10",
    label: "File",
  },
};

/**
 * Normalizes a raw source_type string to a known SourceType.
 * @param src The citation source to classify.
 * @returns The matching SourceType, or "document" for unknown values.
 */
function resolveType(src: Source): SourceType {
  return (
    ["symbol", "commit", "pull_request", "file"] as SourceType[]
  ).includes(src.source_type as SourceType)
    ? (src.source_type as SourceType)
    : "document";
}

/**
 * Resolves the primary display label for a citation.
 * @param type The normalized source type.
 * @param src The citation source.
 * @returns The headline label shown on the card.
 */
function resolvePrimaryLabel(type: SourceType, src: Source): string {
  switch (type) {
    case "symbol":
      return src.symbol_name !== "<anonymous>" ? src.symbol_name : "";
    case "commit":
      return src.commit_hash
        ? src.commit_hash.slice(0, 7)
        : (src.author_name ?? "");
    case "pull_request":
      return `PR #${src.pr_number}`;
    case "file":
      return src.file_path ? src.file_path.split("/").pop()! : "File";
    case "document":
      return src.file_path ? src.file_path.split("/").pop()! : "Source";
  }
}

/**
 * Resolves the secondary display label for a citation.
 * @param type The normalized source type.
 * @param src The citation source.
 * @returns The sub-label shown beneath the primary label.
 */
function resolveSubLabel(type: SourceType, src: Source): string {
  switch (type) {
    case "symbol":
      return src.file_path ?? "";
    case "commit":
      return src.author_name ? `by ${src.author_name}` : "";
    case "pull_request":
      return src.pr_title ?? "";
    case "file":
      return src.file_path ?? "";
    case "document":
      return src.file_path ?? "";
  }
}

/**
 * Builds a GitHub deep link for a citation when one applies.
 * @param src The citation source.
 * @param url The repository base URL.
 * @returns The GitHub URL, or null when the type has no link target.
 */
function resolveGithubHref(src: Source, url: string): string | null {
  if (src.source_type === "symbol")
    return `${url}/blob/master/${src.file_path}#L${src.start_line}-L${src.end_line}`;
  if (src.source_type === "file")
    return `${url}/blob/master/${src.file_path}`;
  if (src.source_type === "commit") return `${url}/commit/${src.commit_hash}`;
  if (src.source_type === "pull_request") return `${url}/pull/${src.pr_number}`;
  return null;
}

/**
 * Renders the GitHub icon link for a citation.
 * @param href The GitHub URL to open in a new tab.
 * @returns The rendered external link element.
 */
function GithubLink({ href }: { href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="mr-2 text-(--muted-foreground) hover:text-(--foreground) transition-colors"
    >
      <GithubLogoIcon size={16} weight="bold" />
    </a>
  );
}

/**
 * Renders an expandable card summarizing one cited source.
 * @param src The citation source to display.
 * @param url The repository base URL for GitHub links.
 * @returns The rendered citation card element.
 */
export default function CitationCard({
  src,
  url,
}: {
  src: Source;
  url: string;
}) {
  const [expanded, setExpanded] = useState(false);

  const type = resolveType(src);
  const config = TYPE_CONFIG[type];
  const Icon = config.icon;
  const githubHref = resolveGithubHref(src, url);

  return (
    <div
      className={`overflow-hidden rounded-lg border transition-all duration-200 h-min ${
        expanded
          ? "bg-(--card) border-(--primary)/40 shadow-sm"
          : "bg-(--secondary)/30 border-(--border) hover:border-(--primary)/20"
      }`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-2.5 text-left focus:outline-none h-13"
      >
        <div className="flex items-center gap-3 overflow-hidden">
          <div
            className={`flex items-center justify-center w-6 h-6 rounded-md ${config.bg} shrink-0`}
          >
            <Icon size={14} className={config.color} weight="bold" />
          </div>

          <div className="truncate">
            <p className="text-xs font-bold text-(--foreground) truncate">
              {resolvePrimaryLabel(type, src)}
            </p>
            <p className="text-[10px] text-(--muted-foreground) truncate mt-0.5">
              {resolveSubLabel(type, src)}
            </p>
          </div>
        </div>

        <div className="flex items-center">
          {githubHref && <GithubLink href={githubHref} />}
          <CaretDownIcon
            size={16}
            className={`text-(--muted-foreground) transition-transform duration-200 shrink-0 ${
              expanded ? "rotate-180" : ""
            }`}
          />
        </div>
      </button>

      {expanded && src.chunk_text && (
        <div className="p-2 pt-0 border-t border-(--border) bg-(--background)/50">
          <div className="mt-2 p-2 rounded bg-(--secondary)/50 border border-(--border) h-35 overflow-y-auto custom-scrollbar">
            <pre className="text-[10px] font-mono text-(--muted-foreground) whitespace-pre-wrap leading-relaxed break-all">
              {src.chunk_text}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
