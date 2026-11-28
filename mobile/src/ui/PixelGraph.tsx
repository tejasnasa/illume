/**
 * A slowly turning pixel constellation, for the backdrop of onboarding and
 * sign-in.
 *
 * @module PixelGraph
 *
 * Port of the idea behind ``client/src/components/PixelGraph.tsx``, kept
 * light for a phone: the scene is built once, and a timer at about ten frames
 * a second re-projects it. With the system's reduce-motion setting on, the
 * timer never starts and one still frame is drawn.
 */

import { useEffect, useMemo, useState } from "react";
import { View } from "react-native";
import Svg, { Line, Rect } from "react-native-svg";

import { useReducedMotion } from "@/hooks/useReducedMotion";
import {
  buildConstellation,
  projectConstellation,
} from "@/lib/pixelConstellation";

/** Milliseconds between frames. */
const FRAME_MS = 100;
/** Radians turned per frame. */
const STEP = 0.012;

export interface PixelGraphProps {
  width: number;
  height: number;
  /** Seed for the scatter. */
  seed?: number;
  /** Side of one pixel. */
  cell?: number;
}

/**
 * Renders the constellation.
 *
 * @param props - The box it fills and its seed.
 * @returns The drawing.
 */
export function PixelGraph({ width, height, seed = 7, cell = 4 }: PixelGraphProps) {
  const reduced = useReducedMotion();
  const scene = useMemo(() => buildConstellation(seed), [seed]);
  const [angle, setAngle] = useState(0.6);

  useEffect(() => {
    if (reduced) return;
    const timer = setInterval(() => setAngle((a) => a + STEP), FRAME_MS);
    return () => clearInterval(timer);
  }, [reduced]);

  const { pixels, edges } = useMemo(
    () => projectConstellation(scene, angle, width, height, cell),
    [scene, angle, width, height, cell],
  );

  return (
    <View
      testID="pixel-graph"
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      <Svg width={width} height={height}>
        {edges.map((edge, i) => (
          <Line
            key={`e${i}`}
            x1={edge.x1}
            y1={edge.y1}
            x2={edge.x2}
            y2={edge.y2}
            stroke="#94a3b8"
            strokeOpacity={edge.opacity}
            strokeWidth={1}
          />
        ))}
        {pixels.map((pixel, i) => (
          <Rect
            key={`p${i}`}
            x={pixel.x}
            y={pixel.y}
            width={pixel.size}
            height={pixel.size}
            fill={pixel.color}
            opacity={pixel.opacity}
          />
        ))}
      </Svg>
    </View>
  );
}
