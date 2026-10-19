/**
 * Stub content for screens that have been scaffolded but not yet
 * implemented.
 *
 * Uses NativeWind ``className`` for layout + colour so the visual
 * language matches the rest of the app -- a placeholder should look
 * intentional, not like a broken screen.
 */
import { Text, View } from "react-native";

interface PlaceholderScreenProps {
  /** Route name shown centred on the screen. */
  title: string;
}

export function PlaceholderScreen({ title }: PlaceholderScreenProps) {
  return (
    <View className="flex-1 items-center justify-center bg-background p-6">
      <Text className="text-foreground text-xl font-semibold">{title}</Text>
      <Text className="mt-2 text-center text-sm text-muted-foreground">
        Placeholder screen
      </Text>
    </View>
  );
}
