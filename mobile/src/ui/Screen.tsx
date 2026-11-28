/**
 * The page shell every screen sits in: background, starfield and top inset.
 */

import type { ReactNode } from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Starfield } from "@/ui/Starfield";

export interface ScreenProps {
  children: ReactNode;
  /** Skip the top safe-area padding, for screens that draw their own header. */
  bare?: boolean;
  /** Extra classes for the content container. */
  className?: string;
}

/**
 * Wraps a screen's content over the starfield.
 *
 * @param props - Content and options.
 * @returns The shell.
 */
export function Screen({ children, bare = false, className = "" }: ScreenProps) {
  const insets = useSafeAreaInsets();
  return (
    <View className="flex-1 bg-background">
      <Starfield />
      <View
        className={`flex-1 ${className}`}
        style={bare ? undefined : { paddingTop: insets.top }}
      >
        {children}
      </View>
    </View>
  );
}
