import { Text, View } from "react-native";

import { colors } from "@/theme/tokens";

interface PlaceholderScreenProps {
  /** Route name shown centred on the screen. */
  title: string;
}

/**
 * Stub content for screens that have been scaffolded but not yet
 * implemented. Renders the route name in the design foreground colour
 * over the design background so a navigated screen is always visually
 * distinct from a broken screen.
 */
export function PlaceholderScreen({ title }: PlaceholderScreenProps) {
  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: colors.background,
        padding: 24,
      }}
    >
      <Text
        style={{
          color: colors.foreground,
          fontSize: 20,
          fontWeight: "600",
        }}
      >
        {title}
      </Text>
      <Text
        style={{
          color: colors.mutedForeground,
          fontSize: 14,
          marginTop: 8,
          textAlign: "center",
        }}
      >
        Placeholder screen
      </Text>
    </View>
  );
}
