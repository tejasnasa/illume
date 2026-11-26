/**
 * Numbered glossary entry card with a source link and a way into the chat.
 * @module GlossaryEntry
 */
import { resolveGithubRef } from "@/lib/github";
import type Glossary from "@/types/glossary";
import Link from "next/link";

/** One glossary entry. */
export type GlossaryItem = Glossary["entries"][number];

/**
 * Renders one glossary term with its definition and file reference.
 * @param entry The glossary entry.
 * @param start The base offset added to idx for the displayed entry number.
 * @param idx The zero-based index of this entry within the current page.
 * @param github_url The repository base URL for the source-file link.
 * @param repoNumber The repository's user-scoped number, for the chat link.
 * @param commitSha The ingested commit, which the link pins to when set.
 * @param branch Repository's ingested branch, used when the SHA is missing.
 * @returns The rendered glossary entry element.
 */
export default function GlossaryEntry({
  entry,
  start,
  idx,
  github_url,
  repoNumber,
  commitSha,
  branch,
}: {
  entry: GlossaryItem;
  start: number;
  idx: number;
  github_url: string;
  repoNumber?: number;
  commitSha?: string | null;
  branch?: string | null;
}) {
  const githubRef = resolveGithubRef(commitSha, branch);
  const line = entry.line_number ? `#L${entry.line_number}` : "";
  const question = `What is ${entry.name}${entry.file_path ? ` in ${entry.file_path}` : ""}, and where is it used?`;

  return (
    <article className="panel flex min-w-0 flex-col gap-3 p-5.5 transition-colors hover:border-(--accent)/40">
      <div className="flex min-w-0 items-baseline gap-3">
        <span className="shrink-0 font-pixel text-xs text-(--faint-foreground)">
          {String(start + idx).padStart(2, "0")}
        </span>
        <h3 className="m-0 min-w-0 truncate font-pixel text-[22px] font-normal" title={entry.name}>
          {entry.name}
        </h3>
      </div>
      <p className="m-0 text-[15px] leading-[1.65] whitespace-pre-wrap text-zinc-400">
        {entry.definition}
      </p>
      <div className="mt-auto flex flex-wrap justify-between gap-2.5 border-t border-white/8 pt-2.5 font-pixel text-xs">
        {entry.file_path ? (
          <a
            href={`${github_url}/blob/${githubRef}/${entry.file_path}${line}`}
            target="_blank"
            rel="noopener noreferrer"
            title={entry.file_path}
            className="min-w-0 truncate text-(--muted-foreground) hover:text-(--foreground)"
          >
            {entry.file_path}
            {entry.line_number && <span className="text-(--accent)">:{entry.line_number}</span>}{" "}
            <span aria-hidden="true">↗</span>
          </a>
        ) : (
          <span className="text-(--faint-foreground) uppercase">No source recorded</span>
        )}
        {repoNumber !== undefined && (
          <Link
            href={`/repo/${repoNumber}/chat?q=${encodeURIComponent(question)}`}
            className="shrink-0 tracking-[0.06em] text-(--muted-foreground) uppercase hover:text-(--accent)"
          >
            Ask about it →
          </Link>
        )}
      </div>
    </article>
  );
}
