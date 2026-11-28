/**
 * A pixel-labelled button with filled, outlined and destructive variants.
 *
 * Port of ``client/src/components/ui/Button.tsx``.
 */

import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, Text } from "react-native";

import { colors } from "@/theme/tokens";

export type ButtonVariant = "primary" | "ghost" | "danger";
export type ButtonSize = "xs" | "sm" | "md" | "lg";

export interface ButtonProps {
  children: ReactNode;
  onPress?: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner and ignores presses. */
  loading?: boolean;
  disabled?: boolean;
  /** Extra classes for the surface. */
  className?: string;
  testID?: string;
  accessibilityLabel?: string;
}

const SIZES: Record<ButtonSize, string> = {
  xs: "h-8 px-2.5",
  sm: "h-10 px-3.5",
  md: "h-11 px-5",
  lg: "h-12 px-6",
};

const TEXT_SIZES: Record<ButtonSize, string> = {
  xs: "text-[11px]",
  sm: "text-xs",
  md: "text-[13px]",
  lg: "text-sm",
};

const SURFACES: Record<ButtonVariant, string> = {
  primary: "border-transparent bg-primary",
  ghost: "border-input bg-transparent",
  danger: "border-destructive/40 bg-transparent",
};

const LABELS: Record<ButtonVariant, string> = {
  primary: "text-primary-foreground",
  ghost: "text-zinc-300",
  danger: "text-destructive",
};

/**
 * Renders the button.
 *
 * @param props - Label, handler, variant, size and state.
 * @returns The pressable.
 */
export function Button({
  children,
  onPress,
  variant = "primary",
  size = "md",
  loading = false,
  disabled = false,
  className = "",
  testID,
  accessibilityLabel,
}: ButtonProps) {
  const inactive = loading || disabled;
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled: inactive, busy: loading }}
      disabled={inactive}
      onPress={onPress}
      className={`flex-row items-center justify-center gap-2 rounded-sm border active:opacity-80 ${SURFACES[variant]} ${SIZES[size]} ${inactive ? "opacity-50" : ""} ${className}`}
    >
      {loading ? (
        <ActivityIndicator size="small" color={colors.foreground} />
      ) : null}
      {typeof children === "string" ? (
        <Text
          className={`font-pixel uppercase tracking-[0.9px] ${LABELS[variant]} ${TEXT_SIZES[size]}`}
        >
          {children}
        </Text>
      ) : (
        children
      )}
    </Pressable>
  );
}
