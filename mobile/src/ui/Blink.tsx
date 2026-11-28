/**
 * A wrapper that fades its content in and out on a loop.
 *
 * @module Blink
 *
 * Port of the web client's ``.blink`` utility: a stepped pulse for live
 * indicators and loading labels. A reader who has asked the system for less
 * motion gets the content held still.
 */

import { useEffect, type ReactNode } from "react";
import type { StyleProp, ViewStyle } from "react-native";
import Animated, {
  cancelAnimation,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";

import { useReducedMotion } from "@/hooks/useReducedMotion";

/** Props for the {@link Blink} component. */
export interface BlinkProps {
  children: ReactNode;
  /** Whether to pulse; ``false`` renders the content steady. */
  active?: boolean;
  /** Style for the wrapping view. */
  style?: StyleProp<ViewStyle>;
  /** Test hook. */
  testID?: string;
}

/** Time for one fade in either direction, in milliseconds. */
const HALF_PERIOD_MS = 600;

/**
 * Pulse the children between full and dim opacity.
 *
 * @param props - The content and whether to pulse.
 * @returns The wrapper.
 */
export function Blink({ children, active = true, style, testID }: BlinkProps) {
  const reduced = useReducedMotion();
  const opacity = useSharedValue(1);
  const pulsing = active && !reduced;

  useEffect(() => {
    if (!pulsing) {
      opacity.value = 1;
      return;
    }
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.25, { duration: HALF_PERIOD_MS }),
        withTiming(1, { duration: HALF_PERIOD_MS }),
      ),
      -1,
      false,
    );
    return () => {
      cancelAnimation(opacity);
    };
  }, [pulsing, opacity]);

  const animated = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <Animated.View testID={testID} style={[style, animated]}>
      {children}
    </Animated.View>
  );
}

export default Blink;
