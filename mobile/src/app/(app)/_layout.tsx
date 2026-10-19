/**
 * Authenticated-route guard.
 *
 * Reads token state from :func:`useAuth`; redirects to ``/login`` when there
 * is no session, shows a splash while the cold-start validation is in
 * flight, and renders the protected stack once the token is known good.
 */

import { Redirect, Stack } from "expo-router";
import { ActivityIndicator, Text, View } from "react-native";

import { useAuth } from "@/hooks/useAuth";
import { colors } from "@/theme/tokens";

export default function AppLayout() {
  const { token, loading } = useAuth();

  if (loading) {
    return (
      <View className="flex-1 items-center justify-center bg-background">
        <ActivityIndicator size="large" color={colors.foreground} />
        <Text className="mt-4 text-2xl font-bold text-foreground">Illume</Text>
      </View>
    );
  }

  if (!token) {
    return <Redirect href="/login" />;
  }

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
