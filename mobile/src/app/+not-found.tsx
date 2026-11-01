/**
 * The screen an unknown route lands on.
 *
 * Without this file expo-router renders its own developer-facing
 * "Unmatched Route" panel, which is confusing in a release build and has
 * no way back. A deep link that no longer resolves -- an old notification,
 * a repository that has been deleted -- is the common way to arrive here.
 *
 * @module NotFoundScreen
 */

import { Pressable, Text, View } from "react-native";
import { router } from "expo-router";

export default function NotFoundScreen() {
  return (
    <View className="flex-1 items-center justify-center bg-background p-6">
      <Text className="mb-2 text-lg font-bold text-foreground">
        This screen does not exist
      </Text>
      <Text className="mb-6 max-w-[280px] text-center text-[13px] text-muted-foreground">
        The link may be out of date, or the repository it pointed at has been
        removed.
      </Text>
      <Pressable
        testID="not-found-home"
        accessibilityRole="button"
        accessibilityLabel="Go to the dashboard"
        onPress={() => router.replace("/(app)/dashboard")}
        className="min-h-[44px] justify-center rounded bg-primary px-5 py-2.5"
      >
        <Text className="text-sm font-semibold text-primary-foreground">
          Go to the dashboard
        </Text>
      </Pressable>
    </View>
  );
}
