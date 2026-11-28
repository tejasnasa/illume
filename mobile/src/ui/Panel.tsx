/**
 * The labelled surface the redesigned screens are built from.
 *
 * Port of the web's ``.panel`` and ``.eyebrow`` classes: a thin border, a flat
 * card fill and a small radius, with an uppercase pixel label for titles.
 */

import type { ReactNode } from "react";
import { Text, View, type ViewProps } from "react-native";

export interface PanelProps extends ViewProps {
  children?: ReactNode;
  /** Extra classes appended to the surface. */
  className?: string;
}

/**
 * A bordered card surface.
 *
 * @param props - View props and extra classes.
 * @returns The surface.
 */
export function Panel({ className = "", children, ...rest }: PanelProps) {
  return (
    <View
      {...rest}
      className={`rounded-md border border-border bg-card ${className}`}
    >
      {children}
    </View>
  );
}

export interface EyebrowProps {
  children: ReactNode;
  /** Extra classes appended to the label. */
  className?: string;
}

/**
 * A small uppercase pixel label for card titles and metadata.
 *
 * @param props - The label and extra classes.
 * @returns The label.
 */
export function Eyebrow({ children, className = "" }: EyebrowProps) {
  return (
    <Text
      className={`font-pixel text-xs uppercase tracking-[1.4px] text-muted-foreground ${className}`}
    >
      {children}
    </Text>
  );
}
