/**
 * Floating inspector card for a selected dependency-graph node.
 * @module GraphCard
 */
"use client";

import { resolveGithubRef } from "@/lib/github";
import Link from "next/link";
import { useState } from "react";

/** How many importers the card lists before folding the rest away. */
export const IMPORTERS_PREVIEW = 2;

/** How many imports the card lists before summarising the remainder. */
const IMPORTS_LIMIT = 8;

/** A neighbouring node in the inspector's lists: its id and the text shown. */
export type Neighbour = { id: string; text: string };

/** A node as the inspector reads it; symbol nodes omit the file-only fields. */
export type InspectedNode = {
  id: string;
  label: string;
  path: string;
  kind?: string;
  loc?: number;
  language?: string;
  criticality?: string;
  fan_in?: number;
  fan_out?: number;
  complexity?: number;
};

const RISK_STYLE: Record<string, string> = {
  critical: "border-red-500/50 text-red-400",
  caution: "border-yellow-400/50 text-yellow-300",
  safe: "border-green-500/50 text-green-400",
};

/**
 * Splits a path into its directory (with trailing slash) and base name.
 *
 * @param path A repo-relative path.
 * @returns The directory prefix and the final segment.
 */
function splitPath(path: string): { dir: string; base: string } {
  const cut = path.lastIndexOf("/");
  return cut === -1
    ? { dir: "", base: path }
    : { dir: path.slice(0, cut + 1), base: path.slice(cut + 1) };
}

/**
 * Renders metadata, neighbours and onward links for the selected graph node.
 *
 * The importer list shows the first {@link IMPORTERS_PREVIEW} entries and folds
 * the rest behind a toggle, because a hub file can be imported by hundreds of
 * others and the list would otherwise push the actions off the card. The
 * fold resets whenever a different node is selected, because the parent keys
 * the card by node id.
 *
 * @param selectedNode The selected node.
 * @param onClose Clears the selection.
 * @param onSelectNode Selects another node by id, for the neighbour rows.
 * @param importers Nodes that depend on the selected one.
 * @param imports Nodes the selected one depends on.
 * @param currentLevel The active graph level ("file" or "symbol").
 * @param repoNumber The repository's number, for the chat and explorer links.
 * @param github_url The repository base URL for the GitHub link.
 * @param commitSha The ingested commit, which the link pins to when set.
 * @param branch Repository's ingested branch, used when the SHA is missing.
 * @param annotation Reading-order note for the file, if it has one.
 * @param tourPosition One-based reading-order position, if the file has one.
 * @returns The rendered graph inspector element.
 */
export default function GraphCard({
  selectedNode,
  onClose,
  onSelectNode,
  importers,
  imports,
  currentLevel,
  repoNumber,
  github_url,
  commitSha,
  branch,
  annotation,
  tourPosition,
}: {
  selectedNode: InspectedNode;
  onClose: () => void;
  onSelectNode: (id: string) => void;
  importers: Neighbour[];
  imports: Neighbour[];
  currentLevel: string;
  repoNumber: string;
  github_url: string;
  commitSha?: string | null;
  branch?: string | null;
  annotation: string | null;
  tourPosition: number | null;
}) {
  const [showAllImporters, setShowAllImporters] = useState(false);
  const githubRef = resolveGithubRef(commitSha, branch);
  const isFile = currentLevel === "file";
  const { dir, base } = splitPath(selectedNode.path);
  const risk = selectedNode.criticality || "safe";
  const noun = isFile ? "file" : "symbol";

  const hiddenImporters = Math.max(0, importers.length - IMPORTERS_PREVIEW);
  const visibleImporters = showAllImporters
    ? importers
    : importers.slice(0, IMPORTERS_PREVIEW);
  const visibleImports = imports.slice(0, IMPORTS_LIMIT);

  const chatHref = `/repo/${repoNumber}/chat?q=${encodeURIComponent(
    `What does ${selectedNode.path} do, and what depends on it?`,
  )}`;
  const explorerHref = `/repo/${repoNumber}/explorer?file=${encodeURIComponent(
    selectedNode.path,
  )}`;

  const rowClass =
    "w-full truncate rounded-sm px-2 py-1.5 text-left font-pixel text-xs text-zinc-300 transition-colors hover:cursor-pointer hover:bg-(--secondary) hover:text-(--foreground)";
  const labelClass =
    "font-pixel text-[11px] tracking-[0.1em] text-(--subtle-foreground) uppercase";
  const chipClass =
    "border border-(--border) px-2 py-1 text-(--muted-foreground)";

  return (
    <aside
      aria-label={`Selected ${noun}`}
      className="panel rise absolute top-5 right-5 z-20 flex max-h-[calc(100%-80px)] w-[min(340px,calc(100%-40px))] flex-col gap-4 overflow-y-auto bg-(--card)/95 p-5 backdrop-blur-sm"
    >
      <div className="flex items-start justify-between gap-2.5">
        <div className="flex min-w-0 flex-col gap-1.5">
          {isFile && dir && (
            <span className="font-pixel text-[11px] tracking-[0.1em] break-all text-(--subtle-foreground)">
              {dir}
            </span>
          )}
          <h2 className="font-pixel text-[22px] leading-tight break-all">
            {isFile ? base : selectedNode.label}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="ghost rounded-sm border border-(--border) px-2 py-1 font-pixel text-(--muted-foreground) hover:cursor-pointer"
        >
          ×
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5 font-pixel text-[11px] tracking-[0.08em] uppercase">
        <span
          className={`border px-2 py-1 ${RISK_STYLE[risk] ?? RISK_STYLE.safe}`}
        >
          {risk}
        </span>
        {!isFile && selectedNode.kind && (
          <span className={chipClass}>{selectedNode.kind}</span>
        )}
        {selectedNode.language && (
          <span className={chipClass}>{selectedNode.language}</span>
        )}
        <span className={chipClass}>{selectedNode.loc ?? 0} LOC</span>
        {!isFile && typeof selectedNode.complexity === "number" && (
          <span className={chipClass}>
            Complexity {selectedNode.complexity}
          </span>
        )}
      </div>

      {!isFile && (
        <span className="font-pixel text-xs break-all text-(--muted-foreground)">
          {selectedNode.path}
        </span>
      )}

      <div className="grid grid-cols-2 gap-2.5">
        <div className="rounded-sm border border-white/8 p-2.5">
          <span className="block font-pixel text-2xl">{importers.length}</span>
          <span className="font-pixel text-[10px] tracking-[0.1em] text-(--subtle-foreground) uppercase">
            {isFile ? "Imported by" : "Used by"}
          </span>
        </div>
        <div className="rounded-sm border border-white/8 p-2.5">
          <span className="block font-pixel text-2xl">{imports.length}</span>
          <span className="font-pixel text-[10px] tracking-[0.1em] text-(--subtle-foreground) uppercase">
            {isFile ? "Imports" : "Uses"}
          </span>
        </div>
      </div>

      {annotation && (
        <p className="m-0 border-l-2 border-(--accent) bg-(--accent)/5 px-3 py-2.5 text-[13px] leading-relaxed text-zinc-300">
          {tourPosition !== null && (
            <span className="font-pixel text-(--accent)">
              {String(tourPosition).padStart(2, "0")}{" "}
            </span>
          )}
          {annotation}
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <span className={labelClass}>{isFile ? "Imported by" : "Used by"}</span>
        {importers.length === 0 ? (
          <span className="px-2 font-pixel text-[11px] text-(--faint-foreground) uppercase">
            Nothing depends on this {noun}
          </span>
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
            {visibleImporters.map(({ id, text }) => (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => onSelectNode(id)}
                  title={text}
                  className={rowClass}
                >
                  ← {text}
                </button>
              </li>
            ))}
          </ul>
        )}
        {hiddenImporters > 0 && (
          <button
            type="button"
            aria-expanded={showAllImporters}
            onClick={() => setShowAllImporters((v) => !v)}
            className="flex items-center gap-2 rounded-sm px-2 py-1 text-left font-pixel text-[11px] tracking-[0.08em] text-(--subtle-foreground) uppercase hover:cursor-pointer hover:bg-(--secondary) hover:text-(--foreground)"
          >
            <span aria-hidden="true" className="text-[10px]">
              {showAllImporters ? "▴" : "▾"}
            </span>
            {showAllImporters ? "Show fewer" : `Show ${hiddenImporters} more`}
          </button>
        )}

        <span className={`${labelClass} mt-1.5`}>
          {isFile ? "Imports" : "Uses"}
        </span>
        {imports.length === 0 ? (
          <span className="px-2 font-pixel text-[11px] text-(--faint-foreground) uppercase">
            No internal dependencies
          </span>
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
            {visibleImports.map(({ id, text }) => (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => onSelectNode(id)}
                  title={text}
                  className={rowClass}
                >
                  → {text}
                </button>
              </li>
            ))}
          </ul>
        )}
        {imports.length > IMPORTS_LIMIT && (
          <span className="px-2 font-pixel text-[11px] text-(--faint-foreground) uppercase">
            + {imports.length - IMPORTS_LIMIT} more
          </span>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Link
          href={chatHref}
          className="cta rounded-sm bg-(--primary) px-3.5 py-2.5 text-center font-pixel text-[13px] tracking-[0.04em] text-(--primary-foreground)"
        >
          Ask about this {noun} →
        </Link>
        <div className="flex gap-2">
          <Link
            href={explorerHref}
            className="ghost flex-1 rounded-sm border border-(--input) p-2.5 text-center font-pixel text-xs text-zinc-300 uppercase"
          >
            Explorer
          </Link>
          <a
            href={`${github_url}/blob/${githubRef}/${selectedNode.path}`}
            target="_blank"
            rel="noopener noreferrer"
            className="ghost flex-1 rounded-sm border border-(--input) p-2.5 text-center font-pixel text-xs text-zinc-300 uppercase"
          >
            GitHub ↗
          </a>
        </div>
      </div>
    </aside>
  );
}
