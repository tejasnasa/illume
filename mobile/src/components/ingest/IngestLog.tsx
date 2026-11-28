/**
 * The raw frames of an ingest, as a scrolling log.
 *
 * @module IngestLog
 *
 * Port of ``client/src/components/ingest/IngestLog.tsx``. The log follows the
 * tail only while the reader is already at the tail: pulling the view back
 * down while someone reads history is worse than missing a line.
 */

import { useCallback, useEffect, useRef } from "react";
import {
  ScrollView,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from "react-native";

import { formatClock, logLabel, logTone } from "@/lib/pipelineBoard";
import { Eyebrow, Panel } from "@/ui/Panel";
import type { IngestFrame } from "@/types/ingest";

/** How close to the bottom, in points, still counts as being at the tail. */
const TAIL_SLACK = 8;

/**
 * Renders the log.
 *
 * @param props - The frames, oldest first, and the repository id for the label.
 * @returns The log panel.
 */
export function IngestLog({
  frames,
  repoId,
}: {
  frames: readonly IngestFrame[];
  repoId?: string;
}) {
  const scroller = useRef<ScrollView>(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    if (stickToBottom.current) scroller.current?.scrollToEnd({ animated: false });
  }, [frames.length]);

  const onScroll = useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, layoutMeasurement, contentSize } = event.nativeEvent;
    stickToBottom.current =
      contentOffset.y + layoutMeasurement.height >= contentSize.height - TAIL_SLACK;
  }, []);

  return (
    <Panel testID="ingest-log" className="overflow-hidden" accessibilityLabel="Live log">
      <View className="flex-row items-center justify-between gap-3 border-b border-border px-4 py-3">
        <Eyebrow>Live log</Eyebrow>
        <Text numberOfLines={1} className="shrink font-pixel text-xs text-zinc-600">
          {repoId ? `task:${repoId.slice(0, 4)}…:logs · ` : ""}
          {frames.length} lines
        </Text>
      </View>
      <ScrollView
        ref={scroller}
        testID="ingest-log-scroll"
        nestedScrollEnabled
        onScroll={onScroll}
        scrollEventThrottle={64}
        style={{ height: 260, backgroundColor: "#060608" }}
        contentContainerStyle={{ paddingHorizontal: 14, paddingVertical: 10 }}
      >
        {frames.length === 0 ? (
          <Text className="font-pixel text-xs text-zinc-600">
            Waiting for the first line…
          </Text>
        ) : (
          frames.map((frame, index) => (
            <View key={index} testID="ingest-log-line" className="py-[3px]">
              <Text className="font-pixel text-[11px] text-zinc-600">
                {formatClock(frame.timestamp)}{" "}
                <Text className="text-zinc-400">{logLabel(frame)}</Text>
              </Text>
              <Text className="font-pixel text-xs" style={{ color: logTone(frame) }}>
                {frame.message}
              </Text>
            </View>
          ))
        )}
      </ScrollView>
    </Panel>
  );
}
