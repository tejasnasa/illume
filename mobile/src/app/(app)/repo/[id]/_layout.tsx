import { Stack } from "expo-router";

import { colors } from "@/theme/tokens";

/**
 * Layout for a single repository. Hosts the in-repo navigation
 * (overview, explorer, glossary, graph) once the navbar ships.
 *
 * The Navigator's ``contentStyle`` is a native ``ViewStyle`` prop
 * (it sets the background of the screen surface, not a React node),
 * so it stays inline rather than going through NativeWind. The
 * colors come from the same tokens every other file reads.
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
