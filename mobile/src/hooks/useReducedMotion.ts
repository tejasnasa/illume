/**
 * The operating system's "reduce motion" setting.
 *
 * @module useReducedMotion
 *
 * The web client honours ``prefers-reduced-motion`` through the animation
 * library's own hook. React Native has no media queries, but the same
 * setting exists under a different name: Android calls it "Remove
 * animations" and iOS calls it "Reduce Motion", and both surface through
 * ``AccessibilityInfo``.
 *
 * The setting can be changed while the app is running, so this subscribes
 * to the change rather than reading it once.
 */

import { useEffect, useState } from "react";
import { AccessibilityInfo } from "react-native";

/**
 * Whether the reader has asked the system for less motion.
 *
 * Starts as ``false`` and settles once the platform has answered, because
 * the setting is asynchronous and the first frame should not wait on it.
 *
 * @returns ``true`` when motion should be suppressed.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void AccessibilityInfo.isReduceMotionEnabled()
      .then((value) => {
        if (!cancelled) setReduced(value);
      })
      .catch(() => {
        // A platform that cannot answer is treated as "no preference".
      });

    const subscription = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      setReduced,
    );

    return () => {
      cancelled = true;
      subscription.remove();
    };
  }, []);

  return reduced;
}
