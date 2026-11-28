/**
 * Shimmer placeholder shaped like :component:`RepoCard`.
 *
 * @module RepoCardSkeleton
 *
 * The web shimmer (the ``animate-shimmer`` utility in
 * ``client/src/app/globals.css``) sweeps a gradient horizontally across
 * a placeholder. There is no CSS background-position on native, so the
 * same effect is achieved with a Reanimated ``withRepeat`` /
 * ``withTiming`` loop driving ``translateX`` on an absolutely-positioned
 * gradient strip over a muted base layer.
 */

import { useEffect } from "react";
import { Dimensions, View } from "react-native";
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";

import { useReducedMotion } from "@/hooks/useReducedMotion";
import { colors } from "@/theme/tokens";

const SHIMMER_WIDTH = Dimensions.get("window").width;
const SWEEP_DURATION_MS = 1500;

export interface RepoCardSkeletonProps {
  /** Override the testID; defaults to a stable value for lists. */
  testID?: string;
}

/**
 * Render a single shimmering card outline that matches :component:`RepoCard`.
 *
 * The shimmer is one absolutely-positioned gradient strip driven by a
 * single ``useSharedValue``; the parent layout (a ``FlatList`` item)
 * receives the outer ``View``. ``useEffect`` kicks the loop on mount so
 * the loop does not advance during SSR or while the component is hidden.
 */
export function RepoCardSkeleton({
  testID = "repo-card-skeleton",
}: RepoCardSkeletonProps) {
  const offset = useSharedValue(-SHIMMER_WIDTH);
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    // A reader who has asked for less motion gets a still placeholder.
    if (reducedMotion) {
      offset.value = 0;
      return;
    }
    offset.value = withRepeat(
      withTiming(SHIMMER_WIDTH, {
        duration: SWEEP_DURATION_MS,
        easing: Easing.linear,
      }),
      -1,
      false,
    );

    // An infinite animation keeps driving the UI thread after the card is
    // gone unless it is cancelled; a dashboard that swaps three skeletons
    // for real rows would otherwise leave three loops running.
    return () => {
      cancelAnimation(offset);
    };
  }, [offset, reducedMotion]);

  const sweepStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: offset.value }],
  }));

  return (
    <View
      testID={testID}
      accessibilityLabel="Loading repository"
      accessibilityRole="progressbar"
      className="mb-3 overflow-hidden rounded-sm border border-border bg-card"
    >
      <View className="h-[112px] border-b border-border bg-[#060608]" />

      <View className="gap-3 p-4">
        <View className="h-[24px] w-3/5 overflow-hidden rounded-sm bg-muted">
          <Animated.View
            style={[sweepBarStyle.sweep, sweepBarStyle.sweepTitle, sweepStyle]}
          />
        </View>

        <View className="gap-2">
          <View className="h-[14px] w-full overflow-hidden rounded-sm bg-muted">
            <Animated.View
              style={[sweepBarStyle.sweep, sweepBarStyle.sweepLine, sweepStyle]}
            />
          </View>
          <View className="h-[14px] w-[70%] overflow-hidden rounded-sm bg-muted">
            <Animated.View
              style={[sweepBarStyle.sweep, sweepBarStyle.sweepLine, sweepStyle]}
            />
          </View>
        </View>

        <View className="flex-row gap-1.5">
          <View className="h-[24px] w-[64px] overflow-hidden rounded-[3px] bg-muted">
            <Animated.View
              style={[sweepBarStyle.sweep, sweepBarStyle.sweepChip, sweepStyle]}
            />
          </View>
          <View className="h-[24px] w-[64px] overflow-hidden rounded-[3px] bg-muted">
            <Animated.View
              style={[sweepBarStyle.sweep, sweepBarStyle.sweepChip, sweepStyle]}
            />
          </View>
        </View>
      </View>
    </View>
  );
}

// The sweep strip is a single absolutely-positioned ``Animated.View``.
// NativeWind can't describe ``position: absolute`` + a runtime-driven
// ``translateX`` together, so the bar keeps an inline style. Width is
// a function of the screen so the strip can be fully off-screen at the
// loop's endpoints.
const sweepBarStyle = {
  sweep: {
    position: "absolute" as const,
    top: 0,
    bottom: 0,
    width: SHIMMER_WIDTH * 0.6,
    backgroundColor: colors.background,
    opacity: 0.45,
  },
  sweepTitle: { opacity: 0.55 },
  sweepLine: { opacity: 0.45 },
  sweepChip: { opacity: 0.45 },
};
