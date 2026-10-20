/**
 * Renders a markdown string as styled runs of text.
 *
 * @module MarkdownText
 *
 * React Native has no markdown renderer, so the architecture summary --
 * which the web client pipes through ``ReactMarkdown`` -- is split into
 * inline runs by :func:`parseInlineMarkdown` and rendered as nested
 * ``Text`` elements.
 *
 * Links open in the system browser rather than in-app: they point at
 * GitHub, and the reader wants the real page.
 */

import { Linking, Platform, Text } from "react-native";

import { parseInlineMarkdown } from "@/lib/markdown";
import { colors } from "@/theme/tokens";

/** The monospace face used for code spans. */
const MONOSPACE = Platform.select({
  ios: "Menlo",
  android: "monospace",
  default: "monospace",
});

/** Props for the {@link MarkdownText} component. */
export interface MarkdownTextProps {
  /** The markdown string to render. */
  source: string;
  /** Extra classes applied to the wrapping text node. */
  className?: string;
}

/**
 * Render a markdown string.
 *
 * @param props - The source string and optional class names.
 * @returns The rendered text.
 */
export function MarkdownText({ source, className }: MarkdownTextProps) {
  const segments = parseInlineMarkdown(source);

  return (
    <Text className={className}>
      {segments.map((segment, index) => {
        const href = segment.href;
        return (
          <Text
            key={`${index}-${segment.text.slice(0, 12)}`}
            style={
              segment.code
                ? { fontFamily: MONOSPACE, color: colors.chart1 }
                : segment.bold
                  ? { fontWeight: "bold" }
                  : segment.italic
                    ? { fontStyle: "italic" }
                    : undefined
            }
            onPress={href ? () => void Linking.openURL(href) : undefined}
          >
            {segment.text}
          </Text>
        );
      })}
    </Text>
  );
}

export default MarkdownText;
