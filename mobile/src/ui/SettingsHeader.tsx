/**
 * The top bar of a settings sub-screen: a back control and a pixel title.
 */

import { Pressable, Text, View } from "react-native";
import { router } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

/**
 * Renders the header.
 *
 * @param props - The title.
 * @returns The bar.
 */
export function SettingsHeader({ title }: { title: string }) {
  const insets = useSafeAreaInsets();
  return (
    <View
      className="flex-row items-center border-b border-border px-2 pb-2"
      style={{ paddingTop: insets.top + 8 }}
    >
      <Pressable
        testID="settings-back"
        accessibilityRole="button"
        accessibilityLabel="Back"
        onPress={() => router.back()}
        className="h-11 w-11 items-center justify-center"
      >
        <Text className="font-pixel text-lg text-foreground">‹</Text>
      </Pressable>
      <Text className="flex-1 font-pixel text-base text-foreground">{title}</Text>
    </View>
  );
}
