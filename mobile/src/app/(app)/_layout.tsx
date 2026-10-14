import { Stack } from "expo-router";

import { colors } from "@/theme/tokens";

/**
 * Layout for the authenticated area. Phase 1 wires navigation only;
 * the auth-guard redirect to /login lives here in a later milestone.
 */
export default function AppLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
