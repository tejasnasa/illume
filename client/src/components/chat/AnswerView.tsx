/**
 * The streamed answer with inline citation chips and its sources.
 * @module AnswerView
 */
"use client";

import {
  decorateAnswer,
  findCitation,
  keysFromHref,
  keyOfCitation,
  partitionSources,
  pathOfKey,
  shortKeyLabel,
  toSource,
  trimPartialMarkup,
} from "@/lib/agent/answer";
import type { RunState } from "@/lib/agent/reducer";
import type { Citation } from "@/lib/agent/types";
import { BookBookmarkIcon, CaretDownIcon, XIcon } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CitationCard from "../ui/CitationCard";

/** The typography an answer is set in; streamed text in the activity uses it too. */
export const PROSE =
  "prose prose-sm prose-invert max-w-none text-(--foreground) prose-headings:text-(--foreground) prose-headings:font-semibold prose-strong:text-(--foreground) prose-code:rounded prose-code:bg-(--secondary)/70 prose-code:px-1 prose-code:py-0.5 prose-code:font-mono prose-code:text-[0.85em] prose-code:font-normal prose-code:text-(--foreground) prose-code:before:content-none prose-code:after:content-none prose-pre:border prose-pre:border-(--border) prose-pre:bg-(--background)/70 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-[0.95em] prose-li:marker:text-(--muted-foreground)";

/** A blinking caret after the last character of text that is still being written. */
export const CARET =
  "after:ml-0.5 after:inline-block after:h-4 after:w-0.5 after:translate-y-0.5 after:bg-(--chart-1) after:content-[''] after:animate-pulse";

/** Where cards link to on GitHub. */
export interface RepoRef {
  url: string;
  commitSha?: string | null;
  branch?: string | null;
}

/** The headline of a source's hover preview. */
function previewTitle(citation: Partial<Citation> | null, key: string): string {
  if (!citation) return shortKeyLabel(key);
  if (citation.symbol_name && citation.symbol_name !== "<anonymous>") {
    return citation.symbol_name;
  }
  if (citation.source_type === "pull_request" && citation.pr_number != null) {
    return `PR #${citation.pr_number}${citation.pr_title ? ` · ${citation.pr_title}` : ""}`;
  }
  if (citation.source_type === "commit") {
    return citation.commit_hash
      ? `commit ${citation.commit_hash.slice(0, 7)}`
      : "Commit";
  }
  return citation.file_path?.split("/").pop() ?? shortKeyLabel(key);
}

/** The line under the headline: where the source lives. */
function previewSubtitle(citation: Partial<Citation> | null, key: string): string {
  if (!citation) return "Not among the sources returned with the answer.";
  if (citation.file_path) {
    const range =
      citation.start_line != null && citation.end_line != null
        ? `:${citation.start_line}-${citation.end_line}`
        : "";
    return `${citation.file_path}${range}`;
  }
  if (citation.author_name) return `by ${citation.author_name}`;
  return key;
}

const PREVIEW_WIDTH = 360;
const PREVIEW_GAP = 6;
const PREVIEW_LINES = 14;

/** Where the preview sits: below the chip, or above it when there is no room. */
interface PreviewPlacement {
  left: number;
  top: number;
  above: boolean;
}

function placePreview(rect: DOMRect): PreviewPlacement {
  const margin = 12;
  const left = Math.min(
    Math.max(margin, rect.left),
    window.innerWidth - PREVIEW_WIDTH - margin,
  );
  const above = window.innerHeight - rect.bottom < 260 && rect.top > 260;
  return {
    left,
    top: above ? rect.top - PREVIEW_GAP : rect.bottom + PREVIEW_GAP,
    above,
  };
}

/**
 * The hover preview of a source: what it is, where it lives, and the first
 * lines of the text the answer was built from.
 *
 * Rendered into the document body with fixed positioning, so neither the
 * message card nor the scrolling column can clip it.
 */
function SourcePreview({
  citation,
  citationKey,
  placement,
}: {
  citation: Partial<Citation> | null;
  citationKey: string;
  placement: PreviewPlacement;
}) {
  const reduced = useReducedMotion();
  const text = (citation?.chunk_text ?? "")
    .trim()
    .split("\n")
    .slice(0, PREVIEW_LINES)
    .join("\n");
  return createPortal(
    <motion.div
      role="tooltip"
      initial={{ opacity: 0, y: reduced ? 0 : placement.above ? 4 : -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.14 }}
      style={{
        left: placement.left,
        top: placement.top,
        width: PREVIEW_WIDTH,
        transform: placement.above ? "translateY(-100%)" : undefined,
      }}
      className="pointer-events-none fixed z-50 overflow-hidden rounded-xl border border-(--border) bg-(--popover)/95 text-left shadow-2xl backdrop-blur-md"
      data-testid="source-preview"
    >
      <div className="border-b border-(--border) px-3 py-2">
        <p className="truncate text-xs font-semibold text-(--foreground)">
          {previewTitle(citation, citationKey)}
        </p>
        <p className="mt-0.5 truncate font-mono text-[10px] text-(--muted-foreground)">
          {previewSubtitle(citation, citationKey)}
        </p>
      </div>
      {text && (
        <pre className="m-0 max-h-56 overflow-hidden whitespace-pre-wrap break-words bg-transparent px-3 py-2 font-mono text-[10.5px] leading-relaxed text-(--muted-foreground)">
          {text}
        </pre>
      )}
    </motion.div>,
    document.body,
  );
}

/**
 * One inline citation key.
 *
 * Interactive only once the answer has settled; while it streams the key shows
 * as quiet text so chips do not pop in and out as the sentence is written.
 */
export function CitationChip({
  citationKey,
  citation,
  settled,
  onOpen,
  onPulse,
}: {
  citationKey: string;
  citation: Partial<Citation> | null;
  settled: boolean;
  onOpen: (citation: Partial<Citation>) => void;
  onPulse: (path: string | null) => void;
}) {
  const reduced = useReducedMotion();
  const [placement, setPlacement] = useState<PreviewPlacement | null>(null);
  const label = shortKeyLabel(citationKey);
  const path = pathOfKey(citationKey);

  if (!settled) {
    return <span className="text-(--muted-foreground) text-[0.8em]">[{label}]</span>;
  }

  const show = (target: HTMLElement) => {
    setPlacement(placePreview(target.getBoundingClientRect()));
    onPulse(path);
  };
  const hide = () => {
    setPlacement(null);
    onPulse(null);
  };

  return (
    <motion.span
      className="mx-0.5 inline-block align-baseline"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduced ? 0.15 : 0.35 }}
      data-chip={citationKey}
    >
      <button
        type="button"
        disabled={!citation}
        onClick={() => citation && onOpen(citation)}
        onMouseEnter={(event) => show(event.currentTarget)}
        onMouseLeave={hide}
        onFocus={(event) => show(event.currentTarget)}
        onBlur={hide}
        aria-label={`Source ${citationKey}`}
        className={`rounded-md border px-1.5 py-px font-mono text-[0.72em] no-underline transition-colors ${
          citation
            ? "border-(--chart-2)/40 bg-(--chart-2)/10 text-(--chart-1) hover:bg-(--chart-2)/20 cursor-pointer"
            : "border-dashed border-(--border) text-(--muted-foreground) cursor-default"
        }`}
      >
        {label}
      </button>
      {placement && (
        <SourcePreview
          citation={citation}
          citationKey={citationKey}
          placement={placement}
        />
      )}
    </motion.span>
  );
}

/**
 * Renders a run's answer and its sources.
 *
 * @param run - The run whose answer to show.
 * @param repo - Repository link data for GitHub deep links.
 * @param onPulse - Called with a file path while a chip is hovered, `null` after.
 * @returns The answer block, or null before any text has arrived.
 */
export default function AnswerView({
  run,
  repo,
  onPulse,
}: {
  run: RunState;
  repo: RepoRef;
  onPulse: (path: string | null) => void;
}) {
  const [opened, setOpened] = useState<Partial<Citation> | null>(null);
  const [showCited, setShowCited] = useState(false);
  const [showRetrieved, setShowRetrieved] = useState(false);
  const settled = run.status === "done";
  const streaming = run.status === "live" || run.status === "connecting";

  const markdown = useMemo(
    () => decorateAnswer(streaming ? trimPartialMarkup(run.answer) : run.answer),
    [run.answer, streaming],
  );
  const parts = useMemo(
    () => partitionSources(run.answer, run.citations, run.evidenceKeys),
    [run.answer, run.citations, run.evidenceKeys],
  );

  const components = useMemo(
    () => ({
      a({ href, children }: { href?: string; children?: React.ReactNode }) {
        const keys = keysFromHref(href);
        if (keys) {
          return (
            <>
              {keys.map((key) => (
                <CitationChip
                  key={key}
                  citationKey={key}
                  citation={findCitation(key, run.citations)}
                  settled={settled}
                  onOpen={setOpened}
                  onPulse={onPulse}
                />
              ))}
            </>
          );
        }
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        );
      },
    }),
    [run.citations, settled, onPulse],
  );

  if (!run.answer) return null;

  return (
    <div className="space-y-4">
      <div
        className={`${PROSE} ${streaming ? CARET : ""}`}
        data-testid="answer"
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {markdown}
        </ReactMarkdown>
      </div>

      {opened && (
        <div className="relative" data-testid="opened-citation">
          <CitationCard
            key={keyOfCitation(opened) ?? "opened"}
            src={toSource(opened)}
            url={repo.url}
            commitSha={repo.commitSha}
            branch={repo.branch}
            defaultExpanded
          />
          <button
            type="button"
            onClick={() => setOpened(null)}
            aria-label="Close source"
            className="absolute -right-2 -top-2 rounded-full border border-(--border) bg-(--card) p-1 text-(--muted-foreground) hover:text-(--foreground) cursor-pointer"
          >
            <XIcon size={10} weight="bold" />
          </button>
        </div>
      )}

      {settled && parts.cited.length > 0 && (
        <section aria-label="Sources cited">
          <button
            type="button"
            onClick={() => setShowCited((v) => !v)}
            aria-expanded={showCited}
            className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-(--muted-foreground) hover:text-(--foreground) cursor-pointer"
          >
            <BookBookmarkIcon size={14} />
            Sources cited ({parts.cited.length})
            <CaretDownIcon
              size={12}
              className={`transition-transform ${showCited ? "rotate-180" : ""}`}
            />
          </button>
          {showCited && (
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {parts.cited.map((citation, i) => (
                <CitationCard
                  key={`${keyOfCitation(citation) ?? "c"}-${i}`}
                  src={toSource(citation)}
                  url={repo.url}
                  commitSha={repo.commitSha}
                  branch={repo.branch}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {settled && (parts.retrieved.length > 0 || parts.retrievedKeys.length > 0) && (
        <section aria-label="Also retrieved">
          <button
            type="button"
            onClick={() => setShowRetrieved((v) => !v)}
            aria-expanded={showRetrieved}
            className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-(--muted-foreground) hover:text-(--foreground) cursor-pointer"
          >
            Also retrieved ({parts.retrieved.length + parts.retrievedKeys.length})
            <CaretDownIcon
              size={12}
              className={`transition-transform ${showRetrieved ? "rotate-180" : ""}`}
            />
          </button>
          {showRetrieved && (
            <div className="mt-2 space-y-2">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {parts.retrieved.map((citation, i) => (
                  <CitationCard
                    key={`${keyOfCitation(citation) ?? "r"}-${i}`}
                    src={toSource(citation)}
                    url={repo.url}
                    commitSha={repo.commitSha}
                    branch={repo.branch}
                  />
                ))}
              </div>
              {parts.retrievedKeys.length > 0 && (
                <ul className="flex flex-wrap gap-1.5">
                  {parts.retrievedKeys.slice(0, 40).map((key) => (
                    <li
                      key={key}
                      className="rounded-md border border-(--border) px-1.5 py-0.5 font-mono text-[10px] text-(--muted-foreground)"
                    >
                      {shortKeyLabel(key)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
