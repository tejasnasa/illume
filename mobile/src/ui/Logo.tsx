/**
 * The Illume mark: a blue hub with three spokes, one of them ending in pink.
 *
 * Port of ``client/src/components/ui/Logo.tsx``, drawn with
 * ``react-native-svg`` so it scales without a bitmap.
 */

import { Text, View } from "react-native";
import Svg, { Circle, G, Line } from "react-native-svg";

import { colors } from "@/theme/tokens";

export interface LogoProps {
  /** Rendered width and height in density-independent pixels. */
  size?: number;
}

/**
 * Renders the mark. Decorative: every caller places it next to the word
 * "illume" or inside a labelled control.
 *
 * @param props - The size.
 * @returns The logo mark.
 */
export function Logo({ size = 30 }: LogoProps) {
  return (
    <Svg
      testID="logo"
      width={size}
      height={size}
      viewBox="0 0 120 120"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      <G stroke={colors.foreground} strokeWidth={6} strokeLinecap="round">
        <Line x1="60" y1="60" x2="24" y2="28" />
        <Line x1="60" y1="60" x2="98" y2="34" />
        <Line x1="60" y1="60" x2="50" y2="102" />
      </G>
      <Circle cx="24" cy="28" r="10" fill={colors.foreground} />
      <Circle cx="50" cy="102" r="10" fill={colors.foreground} />
      <Circle cx="98" cy="34" r="10" fill={colors.accent} />
      <Circle cx="60" cy="60" r="19" fill={colors.selected} />
    </Svg>
  );
}

/**
 * The mark followed by the lowercase wordmark, as used in the top bars.
 *
 * @param props - The mark size; the word scales with it.
 * @returns The lockup.
 */
export function Wordmark({ size = 28 }: LogoProps) {
  return (
    <View className="flex-row items-center gap-2.5">
      <Logo size={size} />
      <Text
        className="font-pixel text-foreground"
        style={{ fontSize: Math.round(size * 0.75), lineHeight: size }}
      >
        illume
      </Text>
    </View>
  );
}
