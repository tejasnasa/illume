/**
 * Collapsible raw ingestion log.
 *
 * @module IngestLogDrawer
 *
 * Port of ``client/src/components/IngestLogDrawer.tsx``.
 *
 * The animation is the primary view, but the raw stream stays one tap away:
 * an animation cannot tell you why something broke, and the text can.
 *
 * On the web the drawer is a section at the bottom of the page that expands
 * in place. On a phone there is not enough height for that, so it is a
 * bottom sheet over the canvas -- it slides up from the bottom edge, dims
 * what is behind it, and closes again on a tap outside.
 *
 * The log's colours are the web client's terminal palette rather than the
 * app's theme tokens. A log is a readout, not a surface: the colours carry
 * meaning (an error line, a finished stage, a running stage) and they have
 * to read the same way the web one does.
 */

import { useCallback, useEffect, useRef } from "react";
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";

import { colors } from "@/theme/tokens";
import type { IngestFrame } from "@/types/ingest";

/** The height of the collapsed summary bar, in points. */
const BAR_HEIGHT = 44;

/** How long the sheet takes to slide, in milliseconds. */
const SHEET_DURATION_MS = 220;

/** How much of the screen the expanded log covers. */
const SHEET_FRACTION = 0.45;

/**
 * The log's terminal palette.
 *
 * Copied from the web drawer so a line reads the same on both platforms.
 * These are literal values rather than theme tokens for the same reason the
 * timeline's rail colours are: the palette is categorical, not semantic.
 */
const LOG_COLORS = {
  error: "#fca5a5",
  success: colors.success,
  started: "#60a5fa",
  status: "#facc15",
  default: "#c9d1d9",
} as const;

/**
 * Map a frame's event to its terminal colour.
 *
 * @param type - The frame's event name.
 * @returns The colour to draw the line in.
 */
export function getLogColor(type: string): string {
  if (type === "error" || type.includes("failed")) return LOG_COLORS.error;
  if (type === "success" || type === "done") return LOG_COLORS.success;
  if (type.includes("started")) return LOG_COLORS.started;
  if (type.includes("complete")) return LOG_COLORS.success;
  if (type === "status_update") return LOG_COLORS.status;
  return LOG_COLORS.default;
}

/**
 * Render a frame's timestamp as a wall clock, falling back to nothing.
 *
 * @param timestamp - The frame's ISO timestamp.
 * @returns The time of day, or an empty string for an unparseable one.
 */
export function formatTime(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleTimeString([], {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Props for {@link IngestLogDrawer}. */
export interface IngestLogDrawerProps {
  /** Every line received so far, oldest first. */
  frames: IngestFrame[];
  /** Whether the sheet is expanded. */
  open: boolean;
  /** Called when the summary bar is tapped, or when the scrim is tapped. */
  onToggle: () => void;
}

/**
 * The drawer.
 *
 * @param props - The frames and the drawer's open state.
 * @returns The drawer, collapsed to a summary bar or expanded to a log pane.
 */
export function IngestLogDrawer({
  frames,
  open,
  onToggle,
}: IngestLogDrawerProps) {
  const { height: windowHeight } = useWindowDimensions();
  const sheetHeight = Math.round(windowHeight * SHEET_FRACTION);

  const listRef = useRef<FlatList<IngestFrame>>(null);
  /**
   * Whether the reader is at the bottom of the log.
   *
   * Follow the tail only while they are already there. Yanking the viewport
   * back down while someone is scrolling through history is worse than
   * missing a line.
   */
  const stickToBottom = useRef(true);

  const progress = useSharedValue(open ? 1 : 0);
  useEffect(() => {
    progress.value = withTiming(open ? 1 : 0, {
      duration: SHEET_DURATION_MS,
      easing: Easing.out(Easing.ease),
    });
  }, [open, progress]);

  const sheetStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: (1 - progress.value) * sheetHeight }],
  }));

  /**
   * Track whether the reader has scrolled away from the tail.
   *
   * @param event - The scroll event.
   */
  const handleScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    stickToBottom.current =
      contentOffset.y + layoutMeasurement.height >= contentSize.height - 8;
  };

  /**
   * Follow the tail when new lines arrive, but only if the reader was
   * already there.
   */
  const handleContentSizeChange = useCallback(() => {
    if (!stickToBottom.current) return;
    listRef.current?.scrollToEnd({ animated: false });
  }, []);

  const latest = frames.length > 0 ? frames[frames.length - 1].message : "";

  return (
    <View
      testID="ingest-log-drawer"
      pointerEvents="box-none"
      style={styles.root}
    >
      {open ? (
        <Pressable
          testID="ingest-log-scrim"
          accessibilityRole="button"
          accessibilityLabel="Close ingest logs"
          onPress={onToggle}
          style={styles.scrim}
        />
      ) : null}

      <Animated.View
        testID="ingest-log-sheet"
        pointerEvents={open ? "auto" : "none"}
        style={[styles.sheet, { height: sheetHeight }, sheetStyle]}
      >
        <FlatList
          ref={listRef}
          testID="ingest-log-list"
          data={frames}
          keyExtractor={(frame, index) => `${index}-${frame.timestamp}`}
          onScroll={handleScroll}
          scrollEventThrottle={16}
          onContentSizeChange={handleContentSizeChange}
          contentContainerStyle={styles.listContent}
          ListEmptyComponent={
            <Text className="text-[11px] text-muted-foreground">
              No output yet.
            </Text>
          }
          renderItem={({ item }) => (
            <View style={styles.row}>
              <Text style={[styles.timestamp, styles.muted]}>
                [{formatTime(item.timestamp)}]
              </Text>
              <Text style={[styles.prompt, styles.muted]}>&gt;</Text>
              <Text
                style={[styles.message, { color: getLogColor(item.event) }]}
              >
                {item.message}
              </Text>
            </View>
          )}
        />
      </Animated.View>

      <Pressable
        testID="ingest-log-toggle"
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={`Ingest logs, ${frames.length} lines`}
        onPress={onToggle}
        style={styles.bar}
      >
        <Text style={styles.caret}>{open ? "▾" : "▸"}</Text>
        <Text style={styles.icon}>▤</Text>
        <Text style={styles.title}>Ingest logs ({frames.length})</Text>
        {!open && latest ? (
          <Text
            testID="ingest-log-latest"
            numberOfLines={1}
            style={[styles.latest, styles.muted]}
          >
            {latest}
          </Text>
        ) : null}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },
  scrim: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0, 0, 0, 0.45)",
  },
  sheet: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: BAR_HEIGHT,
    backgroundColor: colors.background,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  listContent: {
    paddingHorizontal: 12,
    paddingTop: 8,
    paddingBottom: 12,
  },
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    paddingVertical: 1,
  },
  timestamp: {
    fontSize: 10,
    fontFamily: "monospace",
  },
  prompt: {
    fontSize: 10,
    fontFamily: "monospace",
    marginHorizontal: 8,
  },
  message: {
    flex: 1,
    fontSize: 11,
    fontFamily: "monospace",
    lineHeight: 16,
  },
  muted: {
    color: colors.mutedForeground,
  },
  bar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: BAR_HEIGHT,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    backgroundColor: colors.background,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  caret: {
    color: colors.mutedForeground,
    fontSize: 12,
    width: 14,
  },
  icon: {
    color: colors.primary,
    fontSize: 13,
    marginRight: 8,
  },
  title: {
    color: colors.mutedForeground,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1,
  },
  latest: {
    flex: 1,
    marginLeft: 8,
    fontSize: 10,
    fontFamily: "monospace",
  },
});

export default IngestLogDrawer;
