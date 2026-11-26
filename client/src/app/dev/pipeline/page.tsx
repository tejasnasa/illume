/**
 * Preview harness for the ingestion progress view.
 *
 * Replays a scripted frame sequence through the real component so the
 * animation can be judged without ingesting anything, and without a worker,
 * database or repository row existing. Every frame it emits is the shape the
 * backend publishes, and it is folded by the same reducer the live view uses,
 * so what is on screen is the production path with a synthetic clock.
 *
 * @module DevPipelinePreview
 */

"use client";

import IngestFlow from "@/components/IngestFlow";
import type { IngestStream } from "@/hooks/useIngestStream";
import type { IngestFrame } from "@/types/ingest";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** A frame plus how long after the run starts it should be published. */
type Step = { at: number; frame: Omit<IngestFrame, "timestamp"> };

/**
 * Compressed timings. The real pipeline spends minutes here; the shapes and
 * the ordering are the ones the worker actually emits, which is the part
 * worth looking at.
 */
const TIMELINE: Step[] = [
  { at: 0, frame: { event: "status_update", message: "Status changed to cloning", status: "cloning", stage: "clone", phase: "started" } },
  { at: 500, frame: { event: "clone_complete", message: "Clone complete at branch=main, commit=a1b2c3d.", stage: "clone", phase: "done" } },
  { at: 700, frame: { event: "prs_fetch_started", message: "Fetching merged PRs for example/sample-project", stage: "pr_fetch", phase: "started" } },
  { at: 850, frame: { event: "parsing_started", message: "Starting file analysis...", stage: "parse", phase: "started" } },
  { at: 1100, frame: { event: "file_discovery", message: "Found 1024 source files.", stage: "parse", phase: "progress", total: 1024 } },
  { at: 1500, frame: { event: "file_processed", message: "128/1024 files indexed", stage: "parse", phase: "progress", processed: 128, total: 1024 } },
  { at: 1900, frame: { event: "file_processed", message: "384/1024 files indexed", stage: "parse", phase: "progress", processed: 384, total: 1024 } },
  { at: 2300, frame: { event: "file_processed", message: "640/1024 files indexed", stage: "parse", phase: "progress", processed: 640, total: 1024 } },
  { at: 2700, frame: { event: "file_processed", message: "896/1024 files indexed", stage: "parse", phase: "progress", processed: 896, total: 1024 } },
  { at: 3100, frame: { event: "db_storage_complete", message: "Stored 1024 files in DB.", stage: "parse", phase: "done", processed: 1024, total: 1024 } },
  { at: 3300, frame: { event: "deps_resolved_started", message: "Resolving imports...", stage: "resolve_dependencies", phase: "started" } },
  { at: 3900, frame: { event: "deps_resolved", message: "Resolved 2871 dependencies.", stage: "resolve_dependencies", phase: "done", count: 2871 } },
  { at: 4050, frame: { event: "metrics_started", message: "Computing fan-in/fan-out metrics...", stage: "compute_fan_metrics", phase: "started" } },
  { at: 4450, frame: { event: "metrics_complete", message: "Fan-in/fan-out metrics computed.", stage: "compute_fan_metrics", phase: "done" } },
  { at: 4600, frame: { event: "stack_detected", message: "Stack detected: ['Python', 'TypeScript']", stage: "detect_stack", phase: "done" } },
  { at: 4900, frame: { event: "git_analysis_started", message: "Starting git history analysis", stage: "git_history", phase: "started" } },
  { at: 5500, frame: { event: "commits_parsed", message: "Parsed 500 commits from git log", stage: "git_history", phase: "progress", count: 500 } },
  { at: 6000, frame: { event: "file_stats_aggregated", message: "Aggregated ownership stats for 1024 files", stage: "git_history", phase: "progress", count: 1024 } },
  { at: 6400, frame: { event: "ownership_written", message: "Code ownership records written for 1024 files", stage: "git_history", phase: "done", count: 1024 } },
  { at: 6700, frame: { event: "criticality_started", message: "Scoring file criticality...", stage: "criticality", phase: "started" } },
  { at: 7400, frame: { event: "criticality_complete", message: "File criticality scored.", stage: "criticality", phase: "done" } },
  { at: 7600, frame: { event: "glossary_started", message: "Building project glossary...", stage: "glossary", phase: "started" } },
  { at: 7700, frame: { event: "reading_order_started", message: "Generating recommended reading order...", stage: "reading_order", phase: "started" } },
  { at: 9600, frame: { event: "glossary_complete", message: "Project glossary ready.", stage: "glossary", phase: "done" } },
  { at: 10300, frame: { event: "reading_order_complete", message: "Reading order ready.", stage: "reading_order", phase: "done" } },
  { at: 10600, frame: { event: "embedding_started", message: "Generating embeddings...", stage: "generate_embeddings", phase: "started" } },
  { at: 10700, frame: { event: "brief_started", message: "Synthesizing AI architecture brief...", stage: "brief", phase: "started" } },
  { at: 11500, frame: { event: "embedding_progress", message: "Embedding 6 symbol chunks batches in parallel...", stage: "generate_embeddings", phase: "progress" } },
  { at: 13000, frame: { event: "embedding_progress", message: "README embedded (4 sections).", stage: "generate_embeddings", phase: "progress" } },
  { at: 14400, frame: { event: "embedding_complete", message: "Embedding complete — 3120 vectors stored.", stage: "generate_embeddings", phase: "done", count: 3120 } },
  { at: 15300, frame: { event: "brief_complete", message: "Architecture brief ready.", stage: "brief", phase: "done" } },
  { at: 15800, frame: { event: "prs_fetch_complete", message: "Stored 42 merged pull requests", stage: "pr_fetch", phase: "done", count: 42 } },
  { at: 16400, frame: { event: "status_update", message: "Ingestion complete!", status: "ready", stage: "ready", phase: "done" } },
  { at: 16600, frame: { event: "done", message: "DONE", stage: "ready", phase: "done" } },
];

/** Where the failure script interrupts the timeline. */
const FAIL_AT = 4900;
/** Where the retry script starts a second attempt. */
const RETRY_AT = 9000;

type Mode = "success" | "failure" | "retry" | "stall";

/** A short burst that replays the whole pipeline once a retry begins. */
const RETRY_TAIL: Step[] = [
  { at: 0, frame: { event: "clone_started", message: "Cloning repository (branch=main, commit=HEAD)...", stage: "clone", phase: "started" } },
  { at: 900, frame: { event: "clone_complete", message: "Clone complete at branch=main, commit=a1b2c3d.", stage: "clone", phase: "done" } },
  { at: 1100, frame: { event: "parsing_started", message: "Starting file analysis...", stage: "parse", phase: "started" } },
  { at: 1800, frame: { event: "db_storage_complete", message: "Stored 1024 files in DB.", stage: "parse", phase: "done", processed: 1024, total: 1024 } },
  { at: 2400, frame: { event: "deps_resolved", message: "Resolved 2871 dependencies.", stage: "resolve_dependencies", phase: "done" } },
  { at: 2900, frame: { event: "metrics_complete", message: "Fan-in/fan-out metrics computed.", stage: "compute_fan_metrics", phase: "done" } },
  { at: 3300, frame: { event: "stack_detected", message: "Stack detected: ['Python']", stage: "detect_stack", phase: "done" } },
  { at: 3700, frame: { event: "ownership_written", message: "Code ownership records written for 1024 files", stage: "git_history", phase: "done" } },
  { at: 4200, frame: { event: "criticality_complete", message: "File criticality scored.", stage: "criticality", phase: "done" } },
  { at: 4700, frame: { event: "glossary_complete", message: "Project glossary ready.", stage: "glossary", phase: "done" } },
  { at: 5000, frame: { event: "reading_order_complete", message: "Reading order ready.", stage: "reading_order", phase: "done" } },
  { at: 5400, frame: { event: "embedding_complete", message: "Embedding complete — 3120 vectors stored.", stage: "generate_embeddings", phase: "done" } },
  { at: 5800, frame: { event: "brief_complete", message: "Architecture brief ready.", stage: "brief", phase: "done" } },
  { at: 6200, frame: { event: "prs_fetch_complete", message: "Stored 42 merged pull requests", stage: "pr_fetch", phase: "done" } },
  { at: 6600, frame: { event: "status_update", message: "Ingestion complete!", status: "ready", stage: "ready", phase: "done" } },
  { at: 6800, frame: { event: "done", message: "DONE", stage: "ready", phase: "done" } },
];

/** Build the script for a mode. */
function scriptFor(mode: Mode): Step[] {
  const head = TIMELINE.filter((step) => step.at <= FAIL_AT);

  if (mode === "success") return TIMELINE;

  // "stall" stops emitting without failing, so the liveness gating shows.
  if (mode === "stall") return head.slice(0, -1);

  const failure: Step[] = [
    { at: FAIL_AT + 200, frame: { event: "status_update", message: "Error: git log failed with exit code 128", status: "failed", phase: "failed" } },
    { at: FAIL_AT + 400, frame: { event: "error", message: "ERROR", phase: "failed" } },
  ];

  if (mode === "failure") return [...head, ...failure];

  return [
    ...head,
    ...failure,
    ...RETRY_TAIL.map((step) => ({ ...step, at: RETRY_AT + step.at })),
  ];
}

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "success", label: "Success", hint: "the whole pipeline, start to finish" },
  { id: "failure", label: "Failure", hint: "breaks during git history" },
  { id: "retry", label: "Failure then retry", hint: "watch the board rewind and run again" },
  { id: "stall", label: "Stall", hint: "frames stop — the graph should settle" },
];

/**
 * The preview page.
 *
 * @returns Mode controls above the real progress view.
 */
export default function DevPipelinePreview() {
  const [mode, setMode] = useState<Mode>("success");
  const [frames, setFrames] = useState<IngestFrame[]>([]);
  const [runId, setRunId] = useState(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  /** Restart the current script from zero. */
  const replay = useCallback(
    (next: Mode = mode) => {
      setMode(next);
      setFrames([]);
      setRunId((value) => value + 1);
    },
    [mode],
  );

  useEffect(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];

    const script = scriptFor(mode);
    for (const step of script) {
      timers.current.push(
        setTimeout(() => {
          setFrames((current) => [
            ...current,
            { ...step.frame, timestamp: new Date().toISOString() },
          ]);
        }, step.at),
      );
    }

    return () => {
      timers.current.forEach(clearTimeout);
      timers.current = [];
    };
  }, [mode, runId]);

  const stream: IngestStream = useMemo(
    () => ({
      frames,
      connected: true,
      closed: frames.some((frame) => frame.message === "DONE"),
      reconnect: () => replay(),
    }),
    [frames, replay],
  );

  const finished = frames.some(
    (frame) => frame.message === "DONE" || frame.message === "ERROR",
  );

  return (
    <div className="min-h-screen bg-(--background)">
      <div className="flex flex-wrap items-center gap-2 border-b border-(--border) px-4 py-3 text-xs">
        <span className="mr-2 font-semibold uppercase tracking-wider text-(--muted-foreground)">
          Preview
        </span>
        {MODES.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => replay(entry.id)}
            title={entry.hint}
            className={`rounded border px-3 py-1 transition-colors ${
              entry.id === mode
                ? "border-(--primary) bg-(--primary)/15 text-(--foreground)"
                : "border-(--border) text-(--muted-foreground) hover:text-(--foreground)"
            }`}
          >
            {entry.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => replay()}
          className="rounded border border-(--border) px-3 py-1 text-(--muted-foreground) transition-colors hover:text-(--foreground)"
        >
          {finished ? "Replay" : "Restart"}
        </button>
        <span className="ml-auto font-mono text-(--muted-foreground)/70">
          {MODES.find((entry) => entry.id === mode)?.hint}
        </span>
      </div>

      <IngestFlow
        repoId="preview"
        token="preview"
        repoLabel="example/sample-project"
        branch="main"
        commitSha={"a1b2c3d4e5f6".padEnd(40, "0")}
        status="cloning"
        stream={stream}
        // Shortened so a stall is visible in seconds rather than minutes.
        idleMs={8000}
      />
    </div>
  );
}
