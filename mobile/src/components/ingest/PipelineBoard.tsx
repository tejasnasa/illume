/**
 * The ingestion pipeline as a board of stage cards.
 *
 * @module PipelineBoard
 *
 * Port of ``client/src/components/ingest/PipelineBoard.tsx``. The web board
 * is seven columns side by side; on a phone the columns stack, each with its
 * heading and its stages in a wrapping row. State is a pure function of the
 * frames received -- no timer advances a card -- so the board cannot claim
 * progress the backend never reported. Cards are drawn from the state map
 * alone; a screen reader gets one summary line per stage.
 */

import { useEffect } from "react";
import { Text, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";

import { useReducedMotion } from "@/hooks/useReducedMotion";
import { NODES, NODES_BY_ID } from "@/lib/ingestFlow";
import {
  CARD_LOOK,
  PIPELINE_COLUMNS,
  countLabel,
  doneCount,
  fillOf,
  metaLine,
} from "@/lib/pipelineBoard";
import { Eyebrow, Panel } from "@/ui/Panel";
import type { StageState, StageStateMap } from "@/types/ingest";

/** A bar that sweeps while a stage runs without a counter. */
function IndeterminateBar({ color }: { color: string }) {
  const reduced = useReducedMotion();
  const progress = useSharedValue(0);

  useEffect(() => {
    if (reduced) return;
    progress.value = withRepeat(withTiming(1, { duration: 1400 }), -1, false);
  }, [reduced, progress]);

  const style = useAnimatedStyle(() => ({
    width: "35%",
    left: `${progress.value * 65}%`,
  }));

  return (
    <Animated.View
      style={[{ position: "absolute", top: 0, bottom: 0, backgroundColor: color }, reduced ? { width: "35%", left: "30%" } : style]}
    />
  );
}

/** One stage card. */
function StageCard({ id, stage }: { id: string; stage: StageState }) {
  const look = CARD_LOOK[stage.state];
  const fill = fillOf(stage);
  const waiting = stage.state === "pending";

  return (
    <View
      testID={`stage-${id}`}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      className="min-w-[46%] flex-1 gap-1.5 rounded-sm border px-3 py-2.5"
      style={{ borderColor: look.border, backgroundColor: look.background }}
    >
      <View className="flex-row items-center justify-between gap-2">
        <Text
          numberOfLines={1}
          className={`flex-1 text-sm ${waiting ? "text-zinc-500" : "text-foreground"}`}
        >
          {NODES_BY_ID[id]?.label ?? id}
        </Text>
        <Text testID={`stage-mark-${id}`} className="font-pixel text-xs" style={{ color: look.markColor }}>
          {look.mark}
        </Text>
      </View>
      <Text
        testID={`stage-meta-${id}`}
        numberOfLines={1}
        className="font-pixel text-[11px] uppercase tracking-[0.5px] text-zinc-500"
      >
        {metaLine(id, stage)}
      </Text>
      <View className="h-0.5 overflow-hidden bg-white/5">
        {fill === null ? (
          <IndeterminateBar color={look.markColor} />
        ) : (
          <View
            testID={`stage-bar-${id}`}
            style={{ height: 2, width: `${Math.round(fill * 100)}%`, backgroundColor: look.markColor }}
          />
        )}
      </View>
    </View>
  );
}

/**
 * Renders the board.
 *
 * @param props - Every stage state.
 * @returns The board and its screen-reader summary.
 */
export function PipelineBoard({ states }: { states: StageStateMap }) {
  const stageOf = (id: string): StageState => states[id] ?? { state: "pending" };

  return (
    <Panel testID="pipeline-board" className="gap-4 p-4" accessibilityLabel="Pipeline">
      <View className="flex-row flex-wrap items-center justify-between gap-2">
        <Eyebrow>Pipeline</Eyebrow>
        <Text className="font-pixel text-[11px] uppercase text-zinc-500">
          <Text className="text-chart-2">✓</Text> Done{"  "}
          <Text className="text-accent">●</Text> Running{"  "}
          <Text className="text-zinc-600">·</Text> Waiting
        </Text>
      </View>

      {PIPELINE_COLUMNS.map((column) => (
        <View key={column.label} className="gap-2">
          <Text className="font-pixel text-[10px] uppercase tracking-[1.4px] text-zinc-600">
            {column.label}
          </Text>
          <View className="flex-row flex-wrap gap-2">
            {column.stages.map((id) => (
              <StageCard key={id} id={id} stage={stageOf(id)} />
            ))}
          </View>
        </View>
      ))}

      {/* Progress counters are left out of the summary: a ten-thousand-file
          parse would otherwise announce itself hundreds of times. */}
      <View accessibilityLiveRegion="polite" testID="pipeline-summary">
        {NODES.map((node) => {
          const stage = stageOf(node.id);
          const total =
            stage.count === undefined ? null : countLabel(node, stage.count);
          return (
            <Text key={node.id} className="h-0 overflow-hidden opacity-0">
              {node.label}: {stage.state}
              {total ? ` (${total})` : ""}
            </Text>
          );
        })}
      </View>
    </Panel>
  );
}
