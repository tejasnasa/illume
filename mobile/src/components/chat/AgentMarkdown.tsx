/**
 * Markdown for streamed agent text, with citation keys as tappable chips.
 *
 * @module AgentMarkdown
 *
 * The answer is rewritten by {@link decorateAnswer} so every citation key
 * becomes a link whose target carries the key. Here such a link is drawn as a
 * short pixel-font label in the accent colour and, once the answer has
 * settled, opens the source. While the answer streams the labels are quiet
 * text, so they do not appear and vanish as a sentence is written.
 */

import { useMemo } from "react";
import { Linking, Platform, Text, View } from "react-native";

import {
  decorateAnswer,
  keysFromHref,
  shortKeyLabel,
  trimPartialMarkup,
} from "@/lib/agent/answer";
import { parseMarkdownBlocks, type MarkdownRun } from "@/lib/markdownBlocks";
import { colors } from "@/theme/tokens";

const MONOSPACE = Platform.select({
  ios: "Menlo",
  android: "monospace",
  default: "monospace",
});

export interface AgentMarkdownProps {
  /** The raw text as the model wrote it. */
  text: string;
  /** True while the text is still arriving. */
  live?: boolean;
  /** True once chips may be tapped. */
  settled?: boolean;
  /** Called with a citation key when a chip is tapped. */
  onOpenKey?: (key: string) => void;
  /** Smaller type, for the activity block. */
  compact?: boolean;
}

/** Draws the inline runs of one block. */
function Runs({
  runs,
  settled,
  onOpenKey,
}: {
  runs: MarkdownRun;
  settled: boolean;
  onOpenKey?: (key: string) => void;
}) {
  return (
    <>
      {runs.map((run, index) => {
        const keys = keysFromHref(run.href);
        if (keys) {
          return (
            <Text key={index}>
              {keys.map((key) => (
                <Text
                  key={key}
                  testID={`cite-${key}`}
                  onPress={
                    settled && onOpenKey ? () => onOpenKey(key) : undefined
                  }
                  className={`font-pixel text-[11px] ${
                    settled ? "text-accent" : "text-muted-foreground"
                  }`}
                >
                  {" "}[{shortKeyLabel(key)}]
                </Text>
              ))}
            </Text>
          );
        }
        return (
          <Text
            key={`${index}-${run.text.slice(0, 12)}`}
            style={
              run.code
                ? { fontFamily: MONOSPACE, color: colors.chart1 }
                : run.bold
                  ? { fontWeight: "bold" }
                  : run.italic
                    ? { fontStyle: "italic" }
                    : run.href
                      ? { color: colors.accent }
                      : undefined
            }
            onPress={
              run.href ? () => void Linking.openURL(run.href as string) : undefined
            }
          >
            {run.text}
          </Text>
        );
      })}
    </>
  );
}

/**
 * Renders agent text.
 *
 * @param props - The text and its state.
 * @returns The rendered blocks.
 */
export function AgentMarkdown({
  text,
  live = false,
  settled = true,
  onOpenKey,
  compact = false,
}: AgentMarkdownProps) {
  const blocks = useMemo(
    () =>
      parseMarkdownBlocks(decorateAnswer(live ? trimPartialMarkup(text) : text)),
    [text, live],
  );
  const body = compact ? "text-[12px] leading-[18px]" : "text-[14px] leading-[22px]";

  return (
    <View testID="agent-markdown">
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          return (
            <Text
              key={index}
              className="mb-1 mt-2 font-pixel text-[14px] text-foreground"
            >
              <Runs runs={block.runs} settled={settled} onOpenKey={onOpenKey} />
            </Text>
          );
        }
        if (block.type === "list") {
          return (
            <View key={index} className="mb-2">
              {block.items.map((item, i) => (
                <View key={i} className="mb-1 flex-row">
                  <Text className={`mr-2 w-5 text-muted-foreground ${body}`}>
                    {block.ordered ? `${i + 1}.` : "▪"}
                  </Text>
                  <Text className={`flex-1 text-zinc-300 ${body}`}>
                    <Runs runs={item} settled={settled} onOpenKey={onOpenKey} />
                  </Text>
                </View>
              ))}
            </View>
          );
        }
        if (block.type === "code") {
          return (
            <View
              key={index}
              className="mb-2 rounded-sm border border-border bg-background p-2"
            >
              <Text
                style={{ fontFamily: MONOSPACE }}
                className="text-[11px] leading-[15px] text-foreground"
              >
                {block.code}
              </Text>
            </View>
          );
        }
        return (
          <Text key={index} className={`mb-2 text-zinc-300 ${body}`}>
            <Runs runs={block.runs} settled={settled} onOpenKey={onOpenKey} />
          </Text>
        );
      })}
      {live ? <Text className="font-pixel text-accent">▌</Text> : null}
    </View>
  );
}
