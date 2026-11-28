/**
 * A faint field of pixel stars for the backdrop of a screen.
 *
 * Port of ``client/src/components/Starfield.tsx``. The web version twinkles
 * on a canvas; here the field is drawn once as SVG rectangles and held
 * still, which costs nothing per frame and matches the web's reduced-motion
 * rendering.
 */

import { useMemo } from "react";
import { StyleSheet, useWindowDimensions, View } from "react-native";
import Svg, { Rect } from "react-native-svg";

import { buildStars, STAR_CELL } from "@/lib/starfield";

/**
 * Renders the stars absolutely behind its siblings; it never takes touches.
 *
 * @returns The star layer.
 */
export function Starfield() {
  const { width, height } = useWindowDimensions();
  const stars = useMemo(() => buildStars(width, height), [width, height]);

  return (
    <View
      testID="starfield"
      pointerEvents="none"
      style={StyleSheet.absoluteFill}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      <Svg width={width} height={height}>
        {stars.map((star, index) => (
          <Rect
            key={index}
            x={star.x * width}
            y={star.y * height}
            width={STAR_CELL}
            height={STAR_CELL}
            fill="#fafafa"
            opacity={0.05 + 0.06 * star.b}
          />
        ))}
      </Svg>
    </View>
  );
}
