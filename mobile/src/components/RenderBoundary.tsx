/**
 * Catches a render error below it and shows a message in its place.
 *
 * React only offers this as a class. It wraps parts of a screen whose
 * failure should not take the whole screen, or the app, with it -- the 3D
 * graph being the case that matters, since it runs native GL code.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";
import { Text, View } from "react-native";

export interface RenderBoundaryProps {
  children: ReactNode;
  /** The headline shown when something below throws. */
  title?: string;
  /** Called with the error, for logging. */
  onError?: (error: Error) => void;
}

interface RenderBoundaryState {
  error: Error | null;
}

/**
 * An error boundary with a small inline fallback.
 */
export class RenderBoundary extends Component<
  RenderBoundaryProps,
  RenderBoundaryState
> {
  state: RenderBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): RenderBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, _info: ErrorInfo): void {
    this.props.onError?.(error);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <View
        testID="render-boundary-fallback"
        className="flex-1 items-center justify-center p-6"
      >
        <Text className="mb-2 text-base font-semibold text-destructive">
          {this.props.title ?? "Something went wrong"}
        </Text>
        <Text className="text-center text-[13px] text-muted-foreground">
          {error.message}
        </Text>
      </View>
    );
  }
}
