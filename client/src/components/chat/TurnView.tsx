/**
 * One question and its answer: the user's message, the run's steps, the answer and status notes.
 * @module TurnView
 */
"use client";

import type { Turn } from "@/hooks/useConversation";
import type { RunState } from "@/lib/agent/reducer";
import { runCounts } from "@/lib/agent/tools";
import { TrashIcon, WarningIcon } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import ActivityBlock from "./ActivityBlock";
import AnswerView, { type RepoRef } from "./AnswerView";
import StaleNotice from "./StaleNotice";

/** `1234` as `1.2k`, so token counts stay short. */
export function compactCount(value: number): string {
  if (value < 1000) return `${value}`;
  if (value < 10_000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  if (value < 1_000_000) return `${Math.round(value / 1000)}k`;
  return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

function formatSeconds(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return whole < 60 ? `${whole} s` : `${Math.floor(whole / 60)} m ${whole % 60} s`;
}

/**
 * What a finished run spent: tool calls, sources, time and tokens.
 *
 * @param run - A finished run.
 * @returns A quiet line of figures, or null when none are known.
 */
export function RunStats({ run }: { run: RunState }) {
  const { tools, sources } = runCounts(run);
  const usage = run.usage;
  const toolCalls = usage?.tool_calls ?? tools;
  const elapsed =
    usage?.elapsed_seconds ??
    (run.startedAt != null && run.endedAt != null
      ? (run.endedAt - run.startedAt) / 1000
      : null);
  const input = usage?.input_tokens ?? 0;
  const output = usage?.output_tokens ?? 0;

  const parts: { label: string; title?: string }[] = [];
  if (toolCalls > 0) parts.push({ label: `${toolCalls} ${toolCalls === 1 ? "tool call" : "tool calls"}` });
  if (sources > 0) parts.push({ label: `${sources} ${sources === 1 ? "source" : "sources"}` });
  if (elapsed != null && elapsed > 0) parts.push({ label: formatSeconds(elapsed) });
  if (input + output > 0) {
    parts.push({
      label: `${compactCount(input)} in · ${compactCount(output)} out tokens`,
      title: `${input.toLocaleString()} input tokens, ${output.toLocaleString()} output tokens`,
    });
  }
  if (parts.length === 0) return null;

  return (
    <p
      className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-(--muted-foreground)"
      data-testid="run-stats"
    >
      {parts.map((part, i) => (
        <span key={part.label} title={part.title} className="inline-flex items-center gap-2">
          {i > 0 && <span aria-hidden="true">·</span>}
          {part.label}
        </span>
      ))}
    </p>
  );
}

/**
 * Renders a conversation turn.
 *
 * @param turn - The turn, with the run state to show.
 * @param repo - Link data for citations.
 * @param repoId - Repository id, for loading what changed under a stale answer.
 * @param onReask - Asks the turn's question again as a new turn.
 * @param onDelete - Removes the turn.
 * @param onPulse - Reports the file a hovered citation chip points at.
 * @returns The turn's markup.
 */
export default function TurnView({
  turn,
  repo,
  repoId,
  onReask,
  onDelete,
  onPulse,
}: {
  turn: Turn;
  repo: RepoRef;
  repoId?: string;
  onReask?: (question: string) => void;
  onDelete: (turnId: string) => void;
  onPulse: (path: string | null) => void;
}) {
  const reduced = useReducedMotion();
  const { run } = turn;
  const isQuota = run.error?.status === 402;

  return (
    <motion.article
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="group/turn relative flex flex-col gap-3"
      data-testid="turn"
    >
      <div className="flex max-w-[85%] items-center gap-1.5 self-end">
        <button
          type="button"
          onClick={() => onDelete(turn.id)}
          aria-label="Delete message"
          title="Delete message"
          className="shrink-0 rounded-lg p-1.5 text-(--muted-foreground) opacity-0 transition-opacity hover:bg-red-500/10 hover:text-red-400 focus-visible:opacity-100 group-hover/turn:opacity-100 cursor-pointer"
        >
          <TrashIcon size={14} />
        </button>
        <div className="min-w-0 rounded-2xl rounded-tr-sm border border-(--border) bg-(--card)/60 px-4 py-2.5 text-sm text-(--foreground) shadow-md backdrop-blur-md whitespace-pre-wrap wrap-break-word">
          {turn.question}
        </div>
      </div>

      <div className="relative w-full space-y-3 rounded-2xl rounded-tl-sm border border-(--border) bg-(--card)/60 p-4 shadow-sm backdrop-blur-md sm:p-5">
        <ActivityBlock run={run} />

        <AnswerView run={run} repo={repo} onPulse={onPulse} />

        {run.status === "error" && run.error && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-950/10 p-3 text-sm text-red-400"
          >
            <WarningIcon size={16} weight="fill" className="mt-0.5 shrink-0" />
            <p>
              {run.error.message}
              {isQuota && (
                <>
                  {" "}
                  <Link
                    href="/settings"
                    className="text-(--primary) underline-offset-2 hover:underline"
                  >
                    Add your own API key
                  </Link>{" "}
                  to keep chatting.
                </>
              )}
            </p>
          </div>
        )}

        {run.status === "cancelled" && (
          <p className="text-xs text-(--muted-foreground)" role="status">
            Stopped before the answer finished.
          </p>
        )}

        {run.status === "connection_lost" && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-lg border border-yellow-400/30 bg-yellow-400/5 p-3 text-xs text-yellow-300"
          >
            <WarningIcon size={14} weight="fill" />
            <span>Connection lost before the answer finished. Ask again to retry.</span>
          </div>
        )}

        {run.status === "done" && turn.stale && turn.chatMessageId && repoId && (
          <StaleNotice
            repoId={repoId}
            messageId={turn.chatMessageId}
            stale={turn.stale}
            onReask={onReask ? () => onReask(turn.question) : undefined}
          />
        )}

        {run.status === "done" && run.answer && (
          <div className="border-t border-(--border)/50 pt-2">
            <RunStats run={run} />
          </div>
        )}
      </div>
    </motion.article>
  );
}
