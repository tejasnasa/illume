/**
 * One question and its answer: the question, the run steps, the answer and
 * the status notes.
 *
 * @module TurnView
 *
 * Port of ``client/src/components/chat/TurnView.tsx``.
 */

import { router } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { ActivityBlock } from "@/components/chat/ActivityBlock";
import { AnswerView, type RepoRef } from "@/components/chat/AnswerView";
import { StaleNotice } from "@/components/chat/StaleNotice";
import type { Turn } from "@/hooks/useConversation";
import type { RunState } from "@/lib/agent/reducer";
import { runCounts } from "@/lib/agent/tools";
import { RunGraph } from "@/components/chat/RunGraph";
import type Graph from "@/types/graph";

/** `1234` as `1.2k`, so token counts stay short. */
export function compactCount(value: number): string {
  if (value < 1000) return `${value}`;
  if (value < 10_000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  if (value < 1_000_000) return `${Math.round(value / 1000)}k`;
  return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** Seconds as `42 s` or `2 m 5 s`. */
export function formatSeconds(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return whole < 60 ? `${whole} s` : `${Math.floor(whole / 60)} m ${whole % 60} s`;
}

/**
 * The figures of a finished run: tool calls, sources, time and tokens.
 *
 * @param run - A finished run.
 * @returns The figures as labels; empty when none are known.
 */
export function runStatParts(run: RunState): string[] {
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

  const parts: string[] = [];
  if (toolCalls > 0) {
    parts.push(`${toolCalls} ${toolCalls === 1 ? "tool call" : "tool calls"}`);
  }
  if (sources > 0) parts.push(`${sources} ${sources === 1 ? "source" : "sources"}`);
  if (elapsed != null && elapsed > 0) parts.push(formatSeconds(elapsed));
  if (input + output > 0) {
    parts.push(`${compactCount(input)} in · ${compactCount(output)} out tokens`);
  }
  return parts;
}

/** What a finished run spent, as one quiet line. */
export function RunStats({ run }: { run: RunState }) {
  const parts = runStatParts(run);
  if (parts.length === 0) return null;
  return (
    <Text
      testID="run-stats"
      className="font-pixel text-[11px] uppercase tracking-[0.7px] text-faint-foreground"
    >
      {parts.join(" · ")}
    </Text>
  );
}

/**
 * Renders a conversation turn.
 *
 * @param props - The turn, link data for citations, and the turn actions.
 * @returns The turn.
 */
export function TurnView({
  turn,
  repo,
  repoId,
  graph,
  onReask,
  onDelete,
}: {
  turn: Turn;
  repo: RepoRef;
  repoId?: string;
  /** The file graph, when it has loaded; lights the files the run used. */
  graph?: Graph | null;
  onReask?: (question: string) => void;
  onDelete: (turnId: string) => void;
}) {
  const { run } = turn;
  const isQuota = run.error?.status === 402;

  return (
    <View testID="turn" className="gap-3.5">
      <View className="max-w-[88%] self-end">
        <Pressable
          onLongPress={() => onDelete(turn.id)}
          delayLongPress={400}
          accessibilityHint="Long press to delete this message"
          className="rounded-sm bg-[#1c1c21] px-4 py-3"
        >
          <Text className="text-[15px] leading-[21px] text-foreground">
            {turn.question}
          </Text>
        </Pressable>
      </View>

      <View className="gap-3.5">
        <ActivityBlock run={run} />
        {graph ? <RunGraph graph={graph} run={run} /> : null}
        <AnswerView run={run} repo={repo} />

        {run.status === "error" && run.error ? (
          <View
            accessibilityRole="alert"
            className="gap-2 rounded-sm border border-destructive/25 bg-destructive/5 p-3"
          >
            <Text className="text-sm text-red-300">{run.error.message}</Text>
            {isQuota ? (
              <Pressable
                accessibilityRole="link"
                onPress={() => router.push("/settings/ai")}
                className="min-h-[36px] justify-center"
              >
                <Text className="font-pixel text-xs uppercase text-accent">
                  Add your own API key
                </Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}

        {run.status === "cancelled" ? (
          <Text className="font-pixel text-xs uppercase tracking-[0.7px] text-subtle-foreground">
            Stopped before the answer finished.
          </Text>
        ) : null}

        {run.status === "connection_lost" ? (
          <View
            accessibilityRole="alert"
            className="rounded-sm border border-warning/25 bg-warning/5 p-3"
          >
            <Text className="text-xs text-yellow-300">
              Connection lost before the answer finished. Ask again to retry.
            </Text>
          </View>
        ) : null}

        {run.status === "done" && turn.stale && turn.chatMessageId && repoId ? (
          <StaleNotice
            repoId={repoId}
            messageId={turn.chatMessageId}
            stale={turn.stale}
            onReask={onReask ? () => onReask(turn.question) : undefined}
          />
        ) : null}

        {run.status === "done" && run.answer ? (
          <View className="border-t border-border pt-2.5">
            <RunStats run={run} />
          </View>
        ) : null}
      </View>
    </View>
  );
}
