import { Stack } from "expo-router";

import { colors } from "@/theme/tokens";

/**
 * Layout for a single repository. Hosts the in-repo navigation
 * (overview, explorer, glossary, graph) once the navbar ships.
 */
export default function RepoLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
