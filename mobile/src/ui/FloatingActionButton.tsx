/**
 * Floating action button.
 *
 * @module FloatingActionButton
 *
 * The dashboard's "add a repository" affordance. It floats above the list
 * in the bottom-right corner, the position a thumb reaches on a phone --
 * the inline button it replaced sat above the list content, so it was
 * both off the thumb's arc and competing with the "Your Indexed Libraries"
 * heading for space.
 *
 * The button is a 56pt square in the primary colour with a pink border, like
 * the repository dock's Ask button, and sits
 * above the bottom safe-area inset so it never lands under the gesture
 * bar or the home indicator.
 */

import { Pressable, Text, View } from "react-native";

import { PIXEL_FONT } from "@/lib/fonts";
import { colors } from "@/theme/tokens";

/** Props for the floating action button. */
export interface FloatingActionButtonProps {
  /** Press handler. */
  onPress: () => void;
  /** Accessible description of the action. */
  accessibilityLabel: string;
  /** Distance from the bottom of the screen, in points. */
  bottom: number;
  /** Distance from the right edge, in points. */
  right?: number;
  /** The glyph rendered inside the button. */
  glyph?: string;
  /** Test hook. */
  testID?: string;
}

/** Side of the button, in points. */
const SIZE = 56;

/**
 * Render a square floating action button.
 *
 * @param props - Button configuration.
 * @returns The rendered button.
 */
export function FloatingActionButton({
  onPress,
  accessibilityLabel,
  bottom,
  right = 16,
  glyph = "+",
  testID,
}: FloatingActionButtonProps) {
  return (
    <View
      pointerEvents="box-none"
      style={{ position: "absolute", right, bottom }}
    >
      <Pressable
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel}
        onPress={onPress}
        android_ripple={{ color: "rgba(255, 255, 255, 0.2)" }}
        style={({ pressed }) => ({
          width: SIZE,
          height: SIZE,
          borderRadius: 6,
          borderWidth: 2,
          borderColor: colors.accent,
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: colors.primary,
          opacity: pressed ? 0.85 : 1,
        })}
      >
        <Text
          style={{
            fontFamily: PIXEL_FONT,
            color: colors.primaryForeground,
            fontSize: 28,
            lineHeight: 32,
          }}
        >
          {glyph}
        </Text>
      </Pressable>
    </View>
  );
}
