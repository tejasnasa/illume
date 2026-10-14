/**
 * Authenticated-route guard.
 *
 * Reads token state from :func:`useAuth`; redirects to ``/login`` when there
 * is no session, shows a splash while the cold-start validation is in
 * flight, and renders the protected stack once the token is known good.
 */

import { Redirect, Stack } from "expo-router";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { useAuth } from "@/hooks/useAuth";
import { colors } from "@/theme/tokens";

export default function AppLayout() {
  const { token, loading } = useAuth();

  if (loading) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" color={colors.foreground} />
        <Text style={styles.splashText}>Illume</Text>
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

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.background,
  },
  splashText: {
    color: colors.foreground,
    fontSize: 24,
    fontWeight: "700",
    marginTop: 16,
  },
});
