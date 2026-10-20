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
 * The button keeps a 56pt touch target (the Material FAB size) and sits
 * above the bottom safe-area inset so it never lands under the gesture
 * bar or the home indicator.
 */

import { Pressable, Text, View } from "react-native";

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

/** Diameter of the button, in points. */
const SIZE = 56;

/**
 * Render a circular floating action button.
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
        style={({ pressed }) => [
          {
            width: SIZE,
            height: SIZE,
            borderRadius: SIZE / 2,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: colors.primary,
            // A soft elevation so the button reads as floating above the
            // list rather than being painted into it.
            elevation: 8,
            shadowColor: "#000000",
            shadowOpacity: 0.3,
            shadowRadius: 8,
            shadowOffset: { width: 0, height: 4 },
            opacity: pressed ? 0.85 : 1,
          },
        ]}
      >
        <Text
          className="font-light"
          style={{
            color: colors.primaryForeground,
            fontSize: 30,
            lineHeight: 34,
            marginTop: -2,
          }}
        >
          {glyph}
        </Text>
      </Pressable>
    </View>
  );
}
